from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from uuid import UUID

import pytest

from cs2pov.domain.fingerprint import content_fingerprint
from cs2pov.domain.invocation import (
    ModelCapability,
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)
from cs2pov.domain.job import CreateJobRequest, JobDemoSource
from cs2pov.domain.timebase import SourceClock, TimeAnchor, TimeRange
from cs2pov.domain.timeline import (
    DemoDescriptor,
    DemoTimeline,
    MatchPhase,
    PlayerSnapshot,
    Round,
    RoundBoundaryConfidence,
    RoundCollection,
)
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import (
    RoundUnderstandingDocument,
    UnderstandingResult,
)
from cs2pov.domain.voice import VoiceActivityCue
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_repository import FileSystemJobRepository
from cs2pov.workspace.paths import WorkspacePaths


NOW = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
RUN_ID = UUID("44444444-4444-4444-8444-444444444444")


class MutableClock:
    def __init__(self) -> None:
        self.value = NOW

    def __call__(self) -> datetime:
        return self.value

    def advance(self) -> None:
        self.value += timedelta(microseconds=1)


def _snapshot_tree(root: Path):
    rows = []
    for path in sorted((root, *root.rglob("*")), key=lambda value: value.as_posix()):
        state = path.lstat()
        rows.append(
            (
                path.relative_to(root).as_posix(),
                state.st_mode,
                state.st_size,
                state.st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
        )
    return tuple(rows)


def _seed(tmp_path: Path):
    workspace = WorkspacePaths(tmp_path / "workspace")
    source_file = tmp_path / "language.dem"
    source_file.write_bytes(b"language-demo")
    assets = FileSystemDemoAssetRepository(workspace, clock=lambda: NOW)
    asset = assets.import_source(source_file).asset
    source = JobDemoSource(
        asset.asset_id,
        f"library/demos/{asset.asset_id}/asset.json",
        asset.display_name,
    )
    FileSystemJobRepository(workspace, assets, clock=lambda: NOW).create_job(
        CreateJobRequest("job-language", "Language Job", source)
    )
    clock = MutableClock()
    repository = FileSystemJobRepository(
        workspace,
        assets,
        clock=clock,
        run_id_factory=lambda: RUN_ID,
        process_id_supplier=lambda: 6160,
    )
    claim = repository.acquire_write("job-language", lease_us=60_000_000).claim
    return workspace, repository, clock, claim, asset.asset_id


def _language_values(asset_id: str):
    descriptor = DemoDescriptor(
        asset_id,
        "de_mirage",
        None,
        64,
        1,
        (PlayerSnapshot("player-alpha", "Alpha", 2),),
    )
    rounds = RoundCollection(
        (
            Round(
                "round-001",
                1,
                TimeRange(10_000_000, 11_000_000),
                None,
                None,
                MatchPhase.REGULATION_FIRST_HALF,
                "round-parser-v1",
                RoundBoundaryConfidence.EXACT,
                0,
            ),
        )
    )
    anchor = TimeAnchor(
        "anchor-alpha-001",
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        0,
        24_000,
        TimeRange(10_000_000, 11_000_000),
        16_000,
        "voice-extractor-v1",
    )
    timeline = DemoTimeline(descriptor, rounds, (anchor,))
    activity = VoiceActivityCue(
        "activity-alpha-001",
        "player-alpha",
        TimeRange(10_000_000, 10_500_000),
        8,
        (anchor.anchor_id,),
        16_000,
    )
    asr_configuration = ModelConfigurationSnapshot(
        "asr-config-001",
        ModelCapability.ASR,
        "faster-whisper-local",
        None,
        "fixture-asr-model",
        None,
        {"language": "en"},
        (),
        "asr-adapter-v1",
    )
    asr_invocation = ModelInvocationRecord.from_payloads(
        "asr-invoke-001",
        asr_configuration.snapshot_id,
        "asr-batch-001",
        {"audio_content_fingerprint": "9" * 64},
        {"cue_ids": ["cue-alpha-001"]},
    )
    transcript = TranscriptCue.from_source_span(
        "cue-alpha-001",
        "player-alpha",
        "round-001",
        SourceClock.COMPACT_AUDIO_SAMPLE,
        "player-alpha",
        0,
        12_000,
        (anchor,),
        "one jungle",
        "en",
        0.9,
        (activity.activity_id,),
        asr_invocation.invocation_id,
    )
    understanding_configuration = ModelConfigurationSnapshot(
        "llm-config-001",
        ModelCapability.UNDERSTANDING_TRANSLATION,
        "openai-compatible",
        "provider-profile",
        "fixture-model",
        "understanding-v1",
        {"temperature": 0.2},
        (),
        "adapter-v1",
    )
    result = UnderstandingResult(
        transcript.cue_id,
        "round-001",
        transcript.asr_original,
        "one jungle",
        "警家一个",
        0.93,
        ("same-round-context",),
        (),
        "invoke-round-001",
    )
    request = {"round_id": "round-001", "transcript_cues": [transcript.to_dict()]}
    response = {"round_id": "round-001", "results": [result.to_dict()]}
    understanding_invocation = ModelInvocationRecord.from_payloads(
        "invoke-round-001",
        understanding_configuration.snapshot_id,
        "round-001",
        request,
        response,
    )
    document = RoundUnderstandingDocument(
        "round-001",
        content_fingerprint(request),
        understanding_configuration.snapshot_id,
        understanding_invocation.invocation_id,
        (result,),
    )
    return (
        timeline,
        activity,
        asr_configuration,
        asr_invocation,
        transcript,
        understanding_configuration,
        understanding_invocation,
        document,
    )


def _persist_closed_language_graph(tmp_path: Path):
    workspace, repository, clock, claim, asset_id = _seed(tmp_path)
    values = _language_values(asset_id)
    (
        timeline,
        activity,
        asr_configuration,
        asr_invocation,
        transcript,
        understanding_configuration,
        understanding_invocation,
        document,
    ) = values
    opened = repository.load_job("job-language")
    for configuration in (asr_configuration, understanding_configuration):
        clock.advance()
        opened = repository.register_model_configuration(
            "job-language",
            configuration,
            opened.manifest.content_fingerprint(),
            claim,
        )
    repository.save_task_invocations(
        "job-language", "asr-batch-001", (asr_invocation,), claim
    )
    repository.save_task_invocations(
        "job-language", "round-001", (understanding_invocation,), claim
    )
    repository.save_demo_timeline("job-language", timeline, claim)
    repository.save_voice_activities("job-language", (activity,), claim)
    repository.save_transcript_round(
        "job-language", "round-001", (transcript,), claim
    )
    repository.save_unassigned_transcript("job-language", (), claim)
    repository.save_round_understanding("job-language", document, claim)
    return workspace, repository, claim, values


def _assert_integer_demo_times(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.endswith("_us"):
                assert type(child) is int
            _assert_integer_demo_times(child)
    elif isinstance(value, list):
        for child in value:
            _assert_integer_demo_times(child)


def _replace_asr_with_wrong_capability(root: Path) -> None:
    wrong = ModelConfigurationSnapshot(
        "asr-config-001",
        ModelCapability.UNDERSTANDING_TRANSLATION,
        "openai-compatible",
        "provider-profile",
        "fixture-asr-model",
        "understanding-v1",
        {"language": "en"},
        (),
        "adapter-v1",
    )
    (root / "models/snapshots/snapshot_asr-config-001.json").write_text(
        json.dumps(wrong.to_dict()) + "\n",
        encoding="utf-8",
    )


def test_language_graph_round_trips_and_all_reads_are_side_effect_free(tmp_path):
    workspace, repository, _, values = _persist_closed_language_graph(tmp_path)
    timeline, activity, asr_config, asr_call, transcript, llm_config, llm_call, document = values
    root = workspace.jobs_dir / "job-language"
    before = _snapshot_tree(root)

    assert repository.load_demo_timeline("job-language") == timeline
    assert repository.load_transcript_round("job-language", "round-001") == (transcript,)
    assert repository.load_unassigned_transcript("job-language") == ()
    assert repository.load_round_understanding("job-language", "round-001") == document
    graph = repository.load_language_graph("job-language")

    assert graph.timeline == timeline
    assert graph.activities == (activity,)
    assert graph.configurations == (asr_config, llm_config)
    assert graph.invocations == (asr_call, llm_call)
    assert graph.transcripts == (transcript,)
    assert graph.understanding_documents == (document,)
    assert _snapshot_tree(root) == before
    for path in (root / "timeline").glob("*.json*"):
        for line in path.read_text("utf-8").splitlines():
            _assert_integer_demo_times(json.loads(line))


def test_partial_demo_timeline_is_never_filled_and_is_reported(tmp_path):
    workspace, repository, _, _, asset_id = _seed(tmp_path)
    timeline = _language_values(asset_id)[0]
    root = workspace.jobs_dir / "job-language"
    (root / "timeline/demo.json").write_text(
        json.dumps(timeline.descriptor.to_dict()) + "\n", encoding="utf-8"
    )
    before = _snapshot_tree(root)

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_demo_timeline("job-language")

    assert exc_info.value.code == "job_shard_missing"
    inspection = repository.inspect_job("job-language")
    assert any(
        issue.code == "job_shard_missing" and issue.logical_path == "timeline/rounds.json"
        for issue in inspection.entry.issues
    )
    assert _snapshot_tree(root) == before


def test_transcript_partition_and_understanding_filename_identity_are_enforced(tmp_path):
    workspace, repository, _, claim, asset_id = _seed(tmp_path)
    transcript = _language_values(asset_id)[4]
    document = _language_values(asset_id)[7]

    for operation in (
        lambda: repository.save_transcript_round(
            "job-language", "round-002", (transcript,), claim
        ),
        lambda: repository.save_unassigned_transcript(
            "job-language", (transcript,), claim
        ),
        lambda: repository.load_round_understanding("job-language", "Uppercase"),
    ):
        with pytest.raises(JobRepositoryError) as exc_info:
            operation()
        assert exc_info.value.code in {"job_path_escape", "job_shard_invalid", "job_shard_missing"}

    bad_path = workspace.jobs_dir / "job-language/understanding/round_round-002.json"
    bad_path.write_text(json.dumps(document.to_dict()) + "\n", encoding="utf-8")
    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_round_understanding("job-language", "round-002")
    assert exc_info.value.code == "job_shard_invalid"


def test_non_owner_and_invalid_replacement_preserve_existing_transcript(tmp_path):
    workspace, repository, claim, values = _persist_closed_language_graph(tmp_path)
    transcript = values[4]
    path = workspace.jobs_dir / "job-language/transcript/round_round-001.jsonl"
    original = path.read_bytes()
    fake = claim.__class__(
        claim.job_id,
        "run-not-owner",
        claim.process_id,
        claim.acquired_at,
        claim.heartbeat_at,
        claim.lease_expires_at,
    )

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.save_transcript_round(
            "job-language", "round-001", (transcript,), fake
        )
    assert exc_info.value.code == "job_write_interrupted"
    with pytest.raises(JobRepositoryError) as exc_info:
        repository.save_transcript_round(
            "job-language", "round-002", (transcript,), claim
        )
    assert exc_info.value.code == "job_shard_invalid"
    assert path.read_bytes() == original


@pytest.mark.parametrize(
    ("mutate", "error_path"),
    (
        (
            lambda root: (root / "voice/activities.jsonl").write_text("", encoding="utf-8"),
            "voice_activity_ids",
        ),
        (
            _replace_asr_with_wrong_capability,
            "configuration_snapshot_id",
        ),
        (
            lambda root: (root / "models/invocations/task_asr-batch-001.jsonl").write_text("", encoding="utf-8"),
            "asr_invocation_record_id",
        ),
    ),
)
def test_language_graph_rejects_dangling_and_wrong_capability_references(
    tmp_path, mutate, error_path
):
    workspace, repository, _, _ = _persist_closed_language_graph(tmp_path)
    mutate(workspace.jobs_dir / "job-language")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_language_graph("job-language")

    assert exc_info.value.code == "job_shard_invalid"
    cause = exc_info.value.__cause__
    assert cause is not None
    assert getattr(cause, "path", None) == error_path


@pytest.mark.parametrize(
    ("payload", "expected_code"),
    (
        ('{"schema_version":2}\n', "job_schema_unsupported"),
        ('{"schema_version":true}\n', "job_shard_invalid"),
        ('{"schema_version":1,"cue_id":"a","cue_id":"b"}\n', "job_shard_invalid"),
    ),
)
def test_transcript_schema_failures_map_stably(tmp_path, payload, expected_code):
    workspace, repository, _, _, _ = _seed(tmp_path)
    path = workspace.jobs_dir / "job-language/transcript/round_round-001.jsonl"
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_transcript_round("job-language", "round-001")

    assert exc_info.value.code == expected_code


def test_inspection_reports_damaged_known_shard_without_hiding_healthy_sibling(tmp_path):
    workspace, repository, _, claim, asset_id = _seed(tmp_path)
    activity = _language_values(asset_id)[1]
    repository.save_voice_activities("job-language", (activity,), claim)
    bad = workspace.jobs_dir / "job-language/transcript/round_round-001.jsonl"
    bad.write_text('{"schema_version":true}\n', encoding="utf-8")

    inspection = repository.inspect_job("job-language")

    assert any(
        issue.code == "job_shard_invalid"
        and issue.logical_path is not None
        and issue.logical_path.startswith("transcript/round_round-001.jsonl")
        for issue in inspection.entry.issues
    )
    assert repository.load_voice_activities("job-language") == (activity,)


def test_round_filename_ids_are_lowercase_and_casefold_safe(tmp_path):
    workspace, repository, _, claim, asset_id = _seed(tmp_path)
    repository.save_demo_timeline(
        "job-language", _language_values(asset_id)[0], claim
    )
    path = workspace.jobs_dir / "job-language/transcript/round_ROUND-001.jsonl"
    path.write_text("", encoding="utf-8")

    with pytest.raises(JobRepositoryError) as exc_info:
        repository.load_language_graph("job-language")

    assert exc_info.value.code == "job_path_escape"


def test_unexpected_validator_exception_propagates(tmp_path, monkeypatch):
    _, repository, _, _ = _persist_closed_language_graph(tmp_path)

    def explode(*_args, **_kwargs):
        raise RuntimeError("validator bug")

    monkeypatch.setattr(
        "cs2pov.storage.job_repository.validate_transcript_against_timeline",
        explode,
    )
    with pytest.raises(RuntimeError, match="validator bug"):
        repository.load_language_graph("job-language")
