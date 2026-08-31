from __future__ import annotations

import argparse
import wave
from pathlib import Path

import pytest

from cs2pov.application.job_runtime import JobRuntimeError
from cs2pov.application.workspace import WorkspaceSelection
from cs2pov.application.workspace_runtime import WorkspaceRuntimeResolver
from cs2pov.cli import commands
from cs2pov.domain.models import PipelineConfig
from cs2pov.pipeline.engine import PipelineEngine
from cs2pov.services.demo_service import DemoService
from cs2pov.services.transcription_service import TranscriptionService
from cs2pov.storage.artifact_store import ArtifactStore
from cs2pov.storage.jsonl import write_json, write_jsonl
from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService


def _runtime(tmp_path: Path):
    root = tmp_path / "workspace"
    WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()
    selection = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    selection.save(WorkspaceSelection(1, str(root)))
    return WorkspaceRuntimeResolver(selection).resolve_for_write()


def test_run_parser_leaves_output_unset_when_not_explicit(monkeypatch):
    seen = {}

    def capture(args):
        seen["output"] = args.output
        return 0

    monkeypatch.setattr(commands, "run_pipeline", capture)

    assert commands.main(["run", "demo.dem"]) == 0
    assert seen["output"] is None


def test_run_rejects_legacy_whisper_cache_before_pipeline_creation(monkeypatch, tmp_path: Path):
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(commands, "_resolve_write_runtime", lambda: runtime)
    monkeypatch.setattr(commands, "PipelineEngine", lambda *args, **kwargs: pytest.fail("engine must not be created"))
    args = argparse.Namespace(
        output=None, whisper_cache_dir=str(tmp_path / "old-cache"), demo="demo.dem",
        map_name=None, pov_steamid=None, team_number=None, export_scope="pov_team",
        transcription_profile=None, whisper_model=None, whisper_device=None, whisper_compute_type=None,
        language="auto", whisper_vad=None, transcription_mode=None, activity_padding=0.06,
        keep_temp_audio=False, skip_translation=False, dry_run_translation=False, max_rounds=None,
        min_round_duration=10.0, include_unrecognized_voice=False, unrecognized_min_duration=0.35,
        filter_hallucinations=None, max_subtitle_segment_seconds=None, voice_cluster_gap=None,
        bilingual_format=None, subtitle_preset=None, overlap_policy=None, min_subtitle_duration=None,
        glossary=None, player_alias=[],
    )

    with pytest.raises(JobRuntimeError) as caught:
        commands.run_pipeline(args)

    assert caught.value.code == "legacy_model_cache_override_rejected"
    assert not (tmp_path / "old-cache").exists()


def _run_args(**overrides):
    values = dict(
        output=None, whisper_cache_dir=None, demo="demo.dem", map_name=None, pov_steamid=None,
        from_stage=None, to_stage=None,
        team_number=None, export_scope="pov_team", transcription_profile=None, whisper_model=None,
        whisper_device=None, whisper_compute_type=None, language="auto", whisper_vad=None,
        transcription_mode=None, activity_padding=0.06, keep_temp_audio=False, skip_translation=False,
        dry_run_translation=False, max_rounds=None, min_round_duration=10.0,
        include_unrecognized_voice=False, unrecognized_min_duration=0.35, filter_hallucinations=None,
        max_subtitle_segment_seconds=None, voice_cluster_gap=None, bilingual_format=None,
        subtitle_preset=None, overlap_policy=None, min_subtitle_duration=None, glossary=None,
        player_alias=[],
    )
    values.update(overrides)
    return argparse.Namespace(**values)


def test_explicit_output_warns_before_and_after_run(monkeypatch, tmp_path: Path, capsys):
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(commands, "_resolve_write_runtime", lambda: runtime)

    class _Engine:
        def __init__(self, config, **kwargs):
            self.config = config

        def run(self, *args, **kwargs):
            return None

    monkeypatch.setattr(commands, "PipelineEngine", _Engine)
    assert commands.run_pipeline(_run_args(output=str(tmp_path / "legacy-output"))) == 0
    output = capsys.readouterr().out
    assert output.count("旧版外部输出") >= 2


def test_renaming_job_updates_default_audio_cache_job_id(tmp_path: Path):
    cache_root = tmp_path / "workspace" / "cache" / "audio"
    store = ArtifactStore.create(tmp_path / "jobs", map_name=None, audio_cache_root=cache_root)
    store.temp_audio_dir.mkdir(parents=True)
    (store.temp_audio_dir / "slice.wav").write_bytes(b"audio")

    renamed = store.rename_suffix("de_mirage")

    assert renamed.temp_audio_dir == cache_root / renamed.job_dir.name
    assert (renamed.temp_audio_dir / "slice.wav").read_bytes() == b"audio"
    assert not (cache_root / store.job_dir.name).exists()


def test_renaming_job_with_collision_uses_final_job_id_for_audio_cache(tmp_path: Path):
    cache_root = tmp_path / "workspace" / "cache" / "audio"
    store = ArtifactStore.create(tmp_path / "jobs", map_name=None, audio_cache_root=cache_root)
    store.temp_audio_dir.mkdir(parents=True)
    (store.temp_audio_dir / "slice.wav").write_bytes(b"audio")
    occupied = store.job_dir.with_name(store.job_dir.name.replace("unknown_map", "de_mirage"))
    occupied.mkdir()

    renamed = store.rename_suffix("de_mirage")

    assert renamed.job_dir.name.endswith("_de_mirage_2")
    assert renamed.temp_audio_dir == cache_root / renamed.job_dir.name
    assert (renamed.temp_audio_dir / "slice.wav").read_bytes() == b"audio"


def test_pipeline_new_job_requires_explicit_runtime(tmp_path: Path):
    with pytest.raises(JobRuntimeError) as caught:
        PipelineEngine(PipelineConfig(output_root=str(tmp_path / "old-output")))

    assert caught.value.code == "workspace_runtime_required"
    assert not (tmp_path / "old-output").exists()


def test_pipeline_runtime_adapts_new_job_to_workspace_paths(tmp_path: Path):
    runtime = _runtime(tmp_path)
    config = PipelineConfig(output_root=str(tmp_path / "old-output"), whisper_cache_dir=str(tmp_path / "old-cache"))

    engine = PipelineEngine(config, runtime=runtime)

    assert engine.store.job_dir.parent == runtime.paths.jobs_dir.resolve()
    assert engine.config.output_root == str(runtime.paths.jobs_dir.resolve())
    assert engine.config.whisper_cache_dir == str(runtime.paths.whisper_cache_dir.resolve())
    assert engine.manifest.config.output_root == engine.config.output_root
    assert engine.manifest.config.whisper_cache_dir == engine.config.whisper_cache_dir
    assert config.output_root != engine.config.output_root
    assert not (tmp_path / "old-output").exists()
    assert not (tmp_path / "old-cache").exists()


class _CopyingDemoAdapter:
    def decompress_if_needed(self, input_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(input_path.read_bytes())
        return output_path


def test_demo_prepare_copies_external_dem_into_job_input_only(tmp_path: Path):
    source = tmp_path / "outside" / "match.dem"
    source.parent.mkdir()
    source.write_bytes(b"demo-content")
    store = ArtifactStore.create(tmp_path / "jobs", job_id="job-1")

    target = DemoService(_CopyingDemoAdapter()).prepare_input(source, store)

    assert target == store.input_dir / "match.dem"
    assert target.read_bytes() == b"demo-content"
    assert source.read_bytes() == b"demo-content"
    assert list(source.parent.iterdir()) == [source]


def _voice_store(tmp_path: Path, *, keep_temp_audio: bool = False, audio_cache_root: Path | None = None) -> ArtifactStore:
    store = ArtifactStore.create(
        tmp_path / "jobs",
        job_id="job-1",
        audio_cache_root=audio_cache_root,
        keep_temp_audio=keep_temp_audio,
    )
    wav_path = store.voice_dir / "7656119_p.wav"
    with wave.open(str(wav_path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(1000)
        output.writeframes(b"\x00\x00" * 1000)
    packet_path = store.voice_dir / "7656119_p.packets.json"
    write_json(packet_path, [{"demo_start": 0.0, "demo_end": 1.0, "wav_offset": 0.0, "duration": 1.0}])
    write_json(store.voice_manifest_path, {"players": [{"steamid": "7656119", "name": "p", "team_number": 2, "wav_path": str(wav_path), "packet_info_path": str(packet_path)}]})
    write_jsonl(store.voice_activity_path, [{"steamid": "7656119", "player_name": "p", "team_number": 2, "start_time": 0.1, "end_time": 0.5}])
    return store


class _RecordingAdapter:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def transcribe(self, path: Path):
        return [{"start": 0.0, "end": 0.2, "text": "hello"}]


class _FailingAdapter(_RecordingAdapter):
    def transcribe(self, path: Path):
        raise RuntimeError("synthetic transcription failure")


def test_default_transcription_audio_uses_workspace_cache_and_cleans_job_dir(tmp_path: Path):
    cache_root = tmp_path / "workspace" / "cache" / "audio"
    store = _voice_store(tmp_path, audio_cache_root=cache_root)
    TranscriptionService(adapter_factory=_RecordingAdapter).transcribe_all(store, model_name="tiny", transcription_mode="activity")

    assert store.temp_audio_dir == cache_root / "job-1"
    assert not store.temp_audio_dir.exists()
    assert not (store.job_dir / "artifacts" / "temp_audio").exists()


def test_transcription_failure_cleans_only_current_workspace_audio_job(tmp_path: Path):
    cache_root = tmp_path / "workspace" / "cache" / "audio"
    other = cache_root / "other-job"
    other.mkdir(parents=True)
    (other / "keep.wav").write_bytes(b"keep")
    store = _voice_store(tmp_path, audio_cache_root=cache_root)

    with pytest.raises(RuntimeError, match="synthetic transcription failure"):
        TranscriptionService(adapter_factory=_FailingAdapter).transcribe_all(store, model_name="tiny", transcription_mode="activity")

    assert not store.temp_audio_dir.exists()
    assert (other / "keep.wav").exists()


def test_keep_temp_audio_starts_in_job_debug_directory(tmp_path: Path):
    store = _voice_store(tmp_path, keep_temp_audio=True, audio_cache_root=tmp_path / "workspace" / "cache" / "audio")
    TranscriptionService(adapter_factory=_RecordingAdapter).transcribe_all(store, model_name="tiny", transcription_mode="activity", keep_temp_audio=True)

    assert store.temp_audio_dir == store.job_dir / "debug" / "temp_audio"
    assert list(store.temp_audio_dir.rglob("*.wav"))
