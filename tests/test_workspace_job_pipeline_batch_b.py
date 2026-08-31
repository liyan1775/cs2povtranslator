from __future__ import annotations

import argparse
import json
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from cs2pov.application.job_runtime import JobRuntime, JobRuntimeError
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
    preparation = type("Preparation", (), {
        "result": type("Result", (), {"disposition": "imported"})(),
        "ref": object(), "display_name": "demo.dem", "service": object(),
        "resolved_path": tmp_path / "workspace" / "library" / "source.dem",
    })()
    monkeypatch.setattr(commands, "prepare_demo_asset", lambda source, runtime: preparation)

    class _Engine:
        def __init__(self, config, **kwargs):
            self.config = config

        def run(self, *args, **kwargs):
            return None

    monkeypatch.setattr(commands, "PipelineEngine", _Engine)
    assert commands.run_pipeline(_run_args(output=str(tmp_path / "legacy-output"))) == 0
    output = capsys.readouterr().out
    assert output.count("旧版外部输出") >= 2


@pytest.mark.parametrize("output", [None, "legacy-output"])
def test_acceptance_warns_only_for_explicit_legacy_output(monkeypatch, tmp_path: Path, capsys, output):
    import scripts.run_acceptance as acceptance
    import sys

    runtime = _runtime(tmp_path)
    resolver = type("Resolver", (), {"resolve_for_write": lambda self: runtime})
    monkeypatch.setattr(acceptance, "WorkspaceRuntimeResolver", lambda _store: resolver())
    monkeypatch.setattr(acceptance, "default_state_file", lambda: tmp_path / "state.json")

    class _Store:
        job_dir = tmp_path / "job"

    class _Engine:
        def __init__(self, config, **kwargs):
            self.config = config

        def run(self, *args, **kwargs):
            return _Store()

    monkeypatch.setattr(acceptance, "PipelineEngine", _Engine)
    monkeypatch.setattr(sys, "argv", ["run_acceptance.py", "--demo", "demo.dem"] + (["--output", output] if output else []))

    assert acceptance.main() == 0
    text = capsys.readouterr().out
    if output is None:
        assert "旧版外部输出" not in text
    else:
        assert text.count("旧版外部输出") == 2


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


def test_renaming_job_uses_next_id_when_target_audio_exists(tmp_path: Path):
    cache_root = tmp_path / "workspace" / "cache" / "audio"
    store = ArtifactStore.create(tmp_path / "jobs", map_name=None, audio_cache_root=cache_root)
    store.temp_audio_dir.mkdir(parents=True)
    (store.temp_audio_dir / "slice.wav").write_bytes(b"audio")
    occupied_audio = cache_root / store.job_dir.name.replace("unknown_map", "de_mirage")
    occupied_audio.mkdir(parents=True)
    (occupied_audio / "old.wav").write_bytes(b"old")

    renamed = store.rename_suffix("de_mirage")

    assert renamed.job_dir.name.endswith("_de_mirage_2")
    assert renamed.temp_audio_dir.name == renamed.job_dir.name
    assert (renamed.temp_audio_dir / "slice.wav").read_bytes() == b"audio"
    assert (occupied_audio / "old.wav").read_bytes() == b"old"


def test_create_vs_rename_claims_same_candidate_without_overwriting_empty_job(tmp_path: Path, monkeypatch):
    root = tmp_path / "jobs"
    source = ArtifactStore.create(root, job_id="same_unknown_map")
    (source.job_dir / "source.txt").write_text("source", encoding="utf-8")
    target = root / "same_de_mirage"
    rename_ready = threading.Event()
    target_ready = threading.Event()
    allow_rename = threading.Event()
    allow_ensure = threading.Event()
    original_rename = Path.rename
    original_ensure = ArtifactStore.ensure_dirs

    def gated_rename(path, destination):
        if path == source.job_dir and destination == target:
            rename_ready.set()
            assert allow_rename.wait(5)
        return original_rename(path, destination)

    def gated_ensure(store):
        if store.job_dir == target:
            target_ready.set()
            assert allow_ensure.wait(5)
        return original_ensure(store)

    monkeypatch.setattr(Path, "rename", gated_rename)
    monkeypatch.setattr(ArtifactStore, "ensure_dirs", gated_ensure)

    with ThreadPoolExecutor(max_workers=2) as pool:
        rename_future = pool.submit(source.rename_suffix, "de_mirage")
        assert rename_ready.wait(5)
        create_future = pool.submit(ArtifactStore.create, root, job_id="same_de_mirage")
        # Without a candidate claim, create can mkdir the empty destination
        # while rename is between its exists check and Path.rename call.
        target_ready.wait(1)
        allow_rename.set()
        allow_ensure.set()
        renamed = rename_future.result()
        created = create_future.result()

    assert renamed.job_dir != created.job_dir
    assert (renamed.job_dir / "source.txt").read_text(encoding="utf-8") == "source"
    assert renamed.job_dir.is_dir() and created.job_dir.is_dir()


def test_job_rename_failure_rolls_audio_back_to_old_directory(tmp_path: Path, monkeypatch):
    cache_root = tmp_path / "workspace" / "cache" / "audio"
    store = ArtifactStore.create(tmp_path / "jobs", map_name=None, audio_cache_root=cache_root)
    store.temp_audio_dir.mkdir(parents=True)
    (store.temp_audio_dir / "slice.wav").write_bytes(b"audio")
    original_job_dir = store.job_dir
    target_job = original_job_dir.with_name(original_job_dir.name.replace("unknown_map", "de_mirage"))
    target_audio = cache_root / target_job.name
    original_rename = Path.rename

    def fail_job_rename(path, destination):
        if path == original_job_dir:
            raise OSError("synthetic job rename failure")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_job_rename)
    with pytest.raises(OSError, match="synthetic job rename failure"):
        store.rename_suffix("de_mirage")

    assert original_job_dir.exists()
    assert (store.temp_audio_dir / "slice.wav").read_bytes() == b"audio"
    assert not target_audio.exists()


def test_audio_rollback_failure_returns_stable_error_without_deleting_caches(tmp_path: Path, monkeypatch):
    cache_root = tmp_path / "workspace" / "cache" / "audio"
    store = ArtifactStore.create(tmp_path / "jobs", map_name=None, audio_cache_root=cache_root)
    store.temp_audio_dir.mkdir(parents=True)
    (store.temp_audio_dir / "slice.wav").write_bytes(b"audio")
    original_job_dir = store.job_dir
    original_audio_dir = store.temp_audio_dir
    original_rename = Path.rename
    target_job = original_job_dir.with_name(original_job_dir.name.replace("unknown_map", "de_mirage"))
    target_audio = cache_root / target_job.name

    def fail_rollback(path, destination):
        if path == original_job_dir:
            raise OSError("synthetic job rename failure")
        if path == target_audio and destination == original_audio_dir:
            raise OSError("synthetic audio rollback failure")
        return original_rename(path, destination)

    monkeypatch.setattr(Path, "rename", fail_rollback)
    with pytest.raises(JobRuntimeError) as caught:
        store.rename_suffix("de_mirage")

    assert caught.value.code == "job_rename_rollback_failed"
    assert original_job_dir.exists()
    assert not original_audio_dir.exists()
    assert target_audio.exists()


def test_successful_rename_removes_old_audio_id_and_cleanup_removes_final(tmp_path: Path):
    from cs2pov.services.transcription_service import _cleanup_temp_audio

    cache_root = tmp_path / "workspace" / "cache" / "audio"
    store = ArtifactStore.create(tmp_path / "jobs", map_name=None, audio_cache_root=cache_root)
    store.temp_audio_dir.mkdir(parents=True)
    (store.temp_audio_dir / "slice.wav").write_bytes(b"audio")

    renamed = store.rename_suffix("de_mirage")
    assert not (cache_root / store.job_dir.name).exists()
    _cleanup_temp_audio(renamed)
    assert not renamed.temp_audio_dir.exists()


def test_pipeline_new_job_requires_explicit_runtime(tmp_path: Path):
    with pytest.raises(JobRuntimeError) as caught:
        PipelineEngine(PipelineConfig(output_root=str(tmp_path / "old-output")))

    assert caught.value.code == "workspace_runtime_required"
    assert not (tmp_path / "old-output").exists()


def test_pipeline_existing_store_requires_runtime_before_manifest_rewrite(tmp_path: Path):
    job_dir = tmp_path / "old-job"
    store = ArtifactStore.create(job_dir.parent, job_id=job_dir.name)
    store.manifest_path.write_bytes(b"{\"legacy\":true}")
    before = store.manifest_path.read_bytes()

    with pytest.raises(JobRuntimeError) as caught:
        PipelineEngine(PipelineConfig(), store=store)

    assert caught.value.code == "workspace_runtime_required"
    assert store.manifest_path.read_bytes() == before


def test_pipeline_rejects_job_runtime_from_different_workspace(tmp_path: Path):
    runtime_a = _runtime(tmp_path / "a")
    runtime_b = _runtime(tmp_path / "b")
    config = PipelineConfig()
    policy_b = JobRuntime.from_config(runtime_b, config)

    with pytest.raises(JobRuntimeError) as caught:
        PipelineEngine(config, runtime=runtime_a, job_runtime=policy_b)

    assert caught.value.code == "workspace_runtime_mismatch"
    assert not runtime_a.paths.jobs_dir.exists() or not list(runtime_a.paths.jobs_dir.iterdir())
    assert not runtime_b.paths.jobs_dir.exists() or not list(runtime_b.paths.jobs_dir.iterdir())


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


class _RecordingDemoAdapter(_CopyingDemoAdapter):
    def __init__(self):
        self.calls = []

    def decompress_if_needed(self, input_path: Path, output_path: Path) -> Path:
        self.calls.append((input_path, output_path))
        return super().decompress_if_needed(input_path, output_path)


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


def test_demo_prepare_is_idempotent_when_source_is_already_job_input(tmp_path: Path):
    store = ArtifactStore.create(tmp_path / "jobs", job_id="job-1")
    source = store.input_dir / "match.dem"
    source.write_bytes(b"demo-content")

    target = DemoService(_CopyingDemoAdapter()).prepare_input(source, store)

    assert target == source
    assert target.read_bytes() == b"demo-content"


def test_demo_prepare_zst_writes_only_dem_into_job_input(tmp_path: Path):
    source = tmp_path / "outside" / "match.dem.zst"
    source.parent.mkdir()
    source.write_bytes(b"compressed-content")
    store = ArtifactStore.create(tmp_path / "jobs", job_id="job-1")
    adapter = _RecordingDemoAdapter()

    target = DemoService(adapter).prepare_input(source, store)

    assert target == store.input_dir / "match.dem"
    assert target.exists() and target.suffix == ".dem"
    assert adapter.calls == [(source.resolve(), target)]
    assert list(source.parent.iterdir()) == [source]


def test_engine_writes_external_manifest_policy_without_absolute_roots(tmp_path: Path):
    runtime = _runtime(tmp_path)
    config = PipelineConfig()
    external = tmp_path / "legacy-output"
    policy = JobRuntime.from_config(runtime, config, output_root=external)
    engine = PipelineEngine(policy.adapt_config(config), runtime=runtime, job_runtime=policy)

    raw = json.loads(engine.store.manifest_path.read_text(encoding="utf-8"))
    serialized = json.dumps(raw, ensure_ascii=False)
    assert raw["path_policy_version"] == 1
    assert raw["legacy_external_output"] is True
    assert str(runtime.root) not in serialized
    assert str(external) not in serialized


def test_engine_default_manifest_is_workspace_managed_without_legacy_warning(tmp_path: Path, capsys):
    runtime = _runtime(tmp_path)
    engine = PipelineEngine(PipelineConfig(), runtime=runtime)

    raw = json.loads(engine.store.manifest_path.read_text(encoding="utf-8"))
    assert raw["path_policy_version"] == 1
    assert raw["legacy_external_output"] is False
    assert "旧版外部输出" not in capsys.readouterr().out


def test_main_path_error_returns_one_without_traceback(monkeypatch, capsys):
    def fail():
        raise JobRuntimeError("workspace_not_writable", "工作区不可写。", "请修复权限后重试。")

    monkeypatch.setattr(commands, "_resolve_write_runtime", fail)

    assert commands.main(["run", "demo.dem"]) == 1
    output = capsys.readouterr().out
    assert "workspace_not_writable" in output
    assert "Traceback" not in output


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
