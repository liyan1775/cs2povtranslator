"""Cross-process acceptance check for the current Job pipeline.

The check deliberately uses a temporary workspace and fixture adapters.  It
does not need CS2, a GPU, or a network provider.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import wave


JOB_ID = "current-pipeline-e2e"


def _env(source_root: Path, state_file: Path) -> dict[str, str]:
    env = dict(os.environ)
    env.update(
        {
            "PYTHONUTF8": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join((str(source_root / "src"), str(source_root))),
            "CS2POV_STATE_FILE": str(state_file),
        }
    )
    return env


def _run(source_root: Path, workspace: Path, state_file: Path, phase: str, calls: Path) -> dict:
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", phase, str(workspace), str(state_file), str(calls)],
        cwd=source_root,
        env=_env(source_root, state_file),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"子进程 {phase} 失败:\n{completed.stdout}\n{completed.stderr}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"子进程未返回 JSON: {completed.stdout!r}") from exc


def _fixture_values(asset_id: str):
    # This is the repository's canonical synthetic language fixture.  Importing
    # it keeps this acceptance probe aligned with the current domain schema.
    from tests.test_job_repository_language_shards_v1 import _language_values

    return _language_values(asset_id)


class FakeParser:
    def __init__(self, timeline):
        self.timeline = timeline
        self.calls = 0

    def parse_timeline(self, demo_path, demo_asset_id, **kwargs):
        assert demo_path.is_file() and demo_asset_id == self.timeline.descriptor.demo_asset_id
        self.calls += 1
        return self.timeline


class FakeExtractor:
    def __init__(self, extraction):
        self.extraction = extraction
        self.calls = 0

    def extract(self, demo_path, target_dir, *, tick_rate):
        assert demo_path.is_file() and target_dir.is_dir() and tick_rate.numerator > 0
        self.calls += 1
        return self.extraction


class FakeASR:
    def __init__(self, segment):
        self.segment = segment
        self.calls = 0

    def transcribe(self, window):
        assert window.audio_path.parent.is_dir()
        self.calls += 1
        return (self.segment,)


class FakeProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def chat_json(self, configuration, system_prompt, user_prompt):
        assert configuration.snapshot_id and system_prompt and "output_contract" in user_prompt
        self.calls += 1
        return self.payload


def _create(workspace: Path, state_file: Path, calls_path: Path) -> dict:
    from cs2pov.application.pipeline_ports import CurrentJobTimelineApplicationService
    from cs2pov.application.pipeline_ports import _next_timestamp
    from cs2pov.application.round_scheduler import RoundSchedulerSettings
    from cs2pov.application.translation_ports import (
        CurrentJobTranslationApplicationService,
        LegacyRoundTranslationWorker,
    )
    from cs2pov.application.voice_asr_ports import (
        ASRSegment,
        CurrentJobVoiceAsrApplicationService,
        VoiceExtractionResult,
        VoicePacket,
        VoiceStream,
    )
    from cs2pov.domain.job import JobPhase
    from cs2pov.domain.job_state import advance_job_phase
    from cs2pov.domain.job import CreateJobRequest, JobDemoSource
    from cs2pov.domain.job_tasks import RetryPolicy
    from cs2pov.domain.timeline import DemoTimeline
    from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
    from cs2pov.storage.job_repository import FileSystemJobRepository
    from cs2pov.workspace.paths import WorkspacePaths

    workspace.mkdir(parents=True, exist_ok=True)
    paths = WorkspacePaths(workspace)
    source = workspace.parent / "synthetic.dem"
    source.write_bytes(b"synthetic fixture demo; never sent to CS2")
    assets = FileSystemDemoAssetRepository(paths, clock=lambda: datetime.now(timezone.utc))
    asset = assets.import_source(source).asset
    values = _fixture_values(asset.asset_id)
    timeline, _, asr_config, _, _, llm_config, _, _ = values
    base_timeline = DemoTimeline(timeline.descriptor, timeline.rounds, ())
    repository = FileSystemJobRepository(paths, assets, clock=lambda: datetime.now(timezone.utc))
    request = CreateJobRequest(JOB_ID, "Synthetic current Job", JobDemoSource(asset.asset_id, f"library/demos/{asset.asset_id}/asset.json", asset.display_name))
    parser = FakeParser(base_timeline)
    CurrentJobTimelineApplicationService(repository, parser).create_job_with_timeline(request, source)

    # Exercise the current voice/ASR application service with fixture adapters.
    audio_path = paths.temp_dir / "voice" / "player-alpha.wav"
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(audio_path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24_000)
        audio.writeframes(b"\x00\x00" * 24_000)
    fake_extractor = FakeExtractor(
        VoiceExtractionResult(
            (
                VoiceStream(
                    "player-alpha",
                    "Alpha",
                    2,
                    24_000,
                    audio_path,
                    (VoicePacket(0, 12_000, timeline.rounds.rounds[0].time_range),),
                ),
            )
        )
    )
    fake_asr = FakeASR(ASRSegment(0, 12_000, "one jungle", "en", 0.9))
    voice_report = CurrentJobVoiceAsrApplicationService(
        repository, fake_extractor, fake_asr
    ).run(JOB_ID, source, asr_config, paths.temp_dir)
    assert voice_report.completed_round_ids == ("round-001",)
    transcript = repository.load_transcript_round(JOB_ID, "round-001")[0]

    # Context assembly is not a separate port yet.  Advance its explicit Job
    # phase, then run the real current translation scheduler and worker.
    with repository.acquire_write(JOB_ID, lease_us=60_000_000) as session:
        current = repository.load_job(JOB_ID)
        current = repository.register_model_configuration(
            JOB_ID,
            llm_config,
            current.manifest.content_fingerprint(),
            session.claim,
        )
        context_ready = advance_job_phase(
            current.manifest,
            JobPhase.CONTEXT_READY,
            at=_next_timestamp(repository.clock, current.manifest.updated_at),
        )
        repository.replace_manifest(
            JOB_ID, current.manifest.content_fingerprint(), context_ready, session.claim
        )

    provider = FakeProvider(
        {
            "results": [
                {
                    "id": transcript.cue_id,
                    "translated_text": "警家一个",
                    "interpreted_source": "one jungle",
                    "confidence": 0.93,
                }
            ]
        }
    )
    translation_report = CurrentJobTranslationApplicationService(
        repository,
        LegacyRoundTranslationWorker(
            provider, invocation_id_factory=lambda: "invoke-e2e-provider"
        ),
        settings=RoundSchedulerSettings(
            max_concurrency=1,
            claim_lease_us=60_000_000,
            heartbeat_interval_us=10_000_000,
            retry_policy=RetryPolicy(1, 1, 8_000_000),
        ),
    )
    translation_report = translation_report.run(
        JOB_ID, configuration_snapshot_id=llm_config.snapshot_id
    )
    assert translation_report.tasks[0].status.value == "succeeded", translation_report.tasks[0].to_dict()

    # Compose and publish the current Draft from the reopened language graph.
    from cs2pov.domain.validation import compose_draft_timeline
    language = repository.load_language_graph(JOB_ID)
    draft = compose_draft_timeline(
        language.timeline,
        language.transcripts,
        language.understanding_documents,
        language.configurations,
        language.invocations,
    )
    with repository.acquire_write(JOB_ID, lease_us=60_000_000) as session:
        repository.save_draft_timeline(JOB_ID, draft, session.claim)
        current = repository.load_job(JOB_ID)
        draft_ready = advance_job_phase(
            current.manifest,
            JobPhase.DRAFT_TIMELINE_READY,
            at=_next_timestamp(repository.clock, current.manifest.updated_at),
        )
        repository.replace_manifest(
            JOB_ID, current.manifest.content_fingerprint(), draft_ready, session.claim
        )

    calls_path.write_text(json.dumps({"parser": parser.calls, "extractor": fake_extractor.calls, "asr": fake_asr.calls, "provider": provider.calls}), encoding="utf-8")
    job_root = repository.load_job(JOB_ID).paths.job_dir
    manifest = json.loads((job_root / "job.json").read_text(encoding="utf-8"))
    assert [path for path in paths.jobs_dir.iterdir() if path.is_dir()] == [job_root]
    return {"phase": "create", "job": JOB_ID, "phase_value": manifest["phase"], "calls": json.loads(calls_path.read_text(encoding="utf-8"))}


def _resume(workspace: Path, calls_path: Path) -> dict:
    from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
    from cs2pov.storage.job_repository import FileSystemJobRepository
    from cs2pov.workspace.paths import WorkspacePaths

    paths = WorkspacePaths(workspace)
    repository = FileSystemJobRepository(paths, FileSystemDemoAssetRepository(paths))
    graph = repository.load_language_graph(JOB_ID)
    draft = repository.load_draft_timeline(JOB_ID)
    before = json.loads(calls_path.read_text(encoding="utf-8"))
    assert graph.transcripts and draft.cues and before == {"parser": 1, "extractor": 1, "asr": 1, "provider": 1}
    return {"phase": "resume", "reused": True, "cue_count": len(draft.cues), "calls": before}


def _export(workspace: Path) -> dict:
    from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
    from cs2pov.storage.job_repository import FileSystemJobRepository
    from cs2pov.workspace.paths import WorkspacePaths
    from cs2pov.application.subtitle_ports import CurrentJobSubtitleApplicationService

    paths = WorkspacePaths(workspace)
    repository = FileSystemJobRepository(paths, FileSystemDemoAssetRepository(paths))
    report = CurrentJobSubtitleApplicationService(repository).export(JOB_ID, source="draft", preset="editing")
    job_root = paths.jobs_dir / JOB_ID
    manifest = repository.load_job(JOB_ID).manifest
    assert report.artifacts and len(report.artifacts) == len(manifest.final_artifacts)
    for entry in report.artifacts:
        path = job_root / entry.relative_path
        assert path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry.content_sha256
    return {"phase": "export", "artifacts": len(report.artifacts), "manifest_hashes_match": True, "job_phase": manifest.phase.value}


def _child(argv: list[str]) -> int:
    phase, workspace, state_file, calls = argv[2], Path(argv[3]), Path(argv[4]), Path(argv[5])
    result = _create(workspace, state_file, calls) if phase == "create" else _resume(workspace, calls) if phase == "resume" else _export(workspace)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    source_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="current-job-pipeline-e2e-") as temp:
        base = Path(temp)
        workspace, state_file, calls = base / "workspace", base / "state.json", base / "calls.json"
        created = _run(source_root, workspace, state_file, "create", calls)
        resumed = _run(source_root, workspace, state_file, "resume", calls)
        exported = _run(source_root, workspace, state_file, "export", calls)
        assert created["calls"] == resumed["calls"]
        assert exported["manifest_hashes_match"] is True
    print("current Job pipeline E2E passed: independent create/reopen/resume/subtitle export processes")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(_child(sys.argv) if "--child" in sys.argv else main())
    except Exception as exc:
        print(f"current Job pipeline E2E failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
