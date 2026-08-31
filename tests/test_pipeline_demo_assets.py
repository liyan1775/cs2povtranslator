from __future__ import annotations

import json
from pathlib import Path

import pytest

from cs2pov.application.demo_assets import DemoAssetApplicationService, DemoAssetUseCaseError
from cs2pov.application.workspace_runtime import WorkspaceRuntime
from cs2pov.application.job_runtime import JobRuntimeError
from cs2pov.domain.assets import DemoAssetRef
from cs2pov.domain.models import DemoInfo, PipelineConfig, StageName
from cs2pov.pipeline.engine import PipelineEngine
from cs2pov.pipeline.manifest import PipelineManifest
from cs2pov.services.demo_service import DemoService
from cs2pov.storage.artifact_store import ArtifactStore


def make_manifest() -> PipelineManifest:
    return PipelineManifest.create("job-demo-asset", PipelineConfig())


def make_ref() -> DemoAssetRef:
    asset_id = "a" * 64
    return DemoAssetRef(asset_id, f"library/demos/{asset_id}/asset.json")


def test_bind_demo_asset_writes_stable_reference_and_safe_display_name():
    manifest = make_manifest()
    ref = make_ref()

    manifest.bind_demo_asset(ref, "match.dem.zst")

    assert manifest.demo == {
        "input_mode": "demo_asset",
        "asset_id": ref.asset_id,
        "asset_manifest": ref.asset_manifest_relative_path,
        "display_name": "match.dem.zst",
    }
    assert "demo_path" not in manifest.artifacts
    json.dumps(manifest.to_public_dict())


def test_demo_asset_reference_round_trips_without_absolute_paths(tmp_path):
    manifest = make_manifest()
    ref = make_ref()
    manifest.bind_demo_asset(ref, "match.dem")
    manifest.demo.update({"map_name": "de_mirage", "server_name": "server", "players": 10})
    path = tmp_path / "manifest.json"

    manifest.save(path)
    loaded = PipelineManifest.load(path)

    assert loaded.demo_asset_ref() == ref
    assert loaded.demo_asset_display_name() == "match.dem"
    assert loaded.demo["map_name"] == "de_mirage"
    assert loaded.demo["server_name"] == "server"
    assert loaded.demo["players"] == 10
    assert str(tmp_path) not in path.read_text("utf-8")


@pytest.mark.parametrize("display_name", ["", " leading.dem", "nested/match.dem", "nested\\match.dem", "bad\nname.dem"])
def test_bind_demo_asset_rejects_unsafe_display_name(display_name):
    with pytest.raises(ValueError):
        make_manifest().bind_demo_asset(make_ref(), display_name)


@pytest.mark.parametrize(
    "demo",
    [
        {"input_mode": "demo_asset", "display_name": "match.dem"},
        {"input_mode": "demo_asset", "asset_id": "a" * 64, "asset_manifest": "bad", "display_name": "match.dem"},
        {"input_mode": "demo_asset", "asset_id": "A" * 64, "asset_manifest": f"library/demos/{'a' * 64}/asset.json", "display_name": "match.dem"},
        {"input_mode": "mystery"},
    ],
)
def test_demo_asset_ref_read_rejects_invalid_manifest_shape(demo):
    manifest = make_manifest()
    manifest.demo = demo
    with pytest.raises(ValueError):
        manifest.demo_asset_ref()


def test_mark_legacy_demo_input_only_sets_legacy_mode():
    manifest = make_manifest()
    manifest.mark_legacy_demo_input()
    assert manifest.demo == {"input_mode": "legacy_job_copy"}


def test_demo_input_modes_cannot_silently_reclassify_each_other():
    managed = make_manifest()
    managed.bind_demo_asset(make_ref(), "match.dem")
    managed_before = dict(managed.demo)

    with pytest.raises(ValueError, match="demo_asset"):
        managed.mark_legacy_demo_input()
    assert managed.demo == managed_before

    legacy = make_manifest()
    legacy.mark_legacy_demo_input()
    legacy_before = dict(legacy.demo)

    with pytest.raises(ValueError, match="legacy"):
        legacy.bind_demo_asset(make_ref(), "match.dem")
    assert legacy.demo == legacy_before


def test_managed_demo_rejects_unknown_or_ambiguous_fields_before_publish_and_load(tmp_path):
    manifest = make_manifest()
    manifest.bind_demo_asset(make_ref(), "match.dem")
    manifest.demo["source_path"] = "D:/private/source.dem"

    with pytest.raises(ValueError, match="字段"):
        manifest.demo_asset_ref()
    with pytest.raises(ValueError, match="字段"):
        manifest.to_public_dict()

    raw = {
        "schema_version": 1,
        "job_id": "job-demo-asset",
        "created_at": manifest.created_at,
        "updated_at": manifest.updated_at,
        "config": PipelineManifest.create("other", PipelineConfig()).to_public_dict()["config"],
        "stages": {},
        "artifacts": {},
        "demo": dict(manifest.demo),
        "notes": [],
    }
    path = tmp_path / "invalid-manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="字段"):
        PipelineManifest.load(path)


def test_legacy_mode_rejects_managed_identity_fields_instead_of_ignoring_them():
    manifest = make_manifest()
    manifest.mark_legacy_demo_input()
    manifest.demo["asset_id"] = "a" * 64

    with pytest.raises(ValueError, match="legacy"):
        manifest.demo_asset_ref()
    with pytest.raises(ValueError, match="legacy"):
        manifest.to_public_dict()


def test_missing_input_mode_cannot_hide_managed_asset_identity(tmp_path):
    manifest = make_manifest()
    manifest.bind_demo_asset(make_ref(), "match.dem")
    manifest.demo.pop("input_mode")

    with pytest.raises(ValueError, match="input_mode"):
        manifest.demo_asset_ref()
    with pytest.raises(ValueError, match="input_mode"):
        manifest.to_public_dict()

    raw = {
        **PipelineManifest.create("old", PipelineConfig()).to_public_dict(),
        "demo": dict(manifest.demo),
    }
    path = tmp_path / "ambiguous-manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="input_mode"):
        PipelineManifest.load(path)


def test_old_manifest_without_input_mode_remains_readable_and_is_not_rewritten(tmp_path):
    manifest = make_manifest()
    path = tmp_path / "manifest.json"
    manifest.save(path)
    before = path.read_bytes()

    loaded = PipelineManifest.load(path)

    assert loaded.demo_asset_ref() is None
    assert loaded.demo_asset_display_name() is None
    assert path.read_bytes() == before


class RecordingAssetService:
    def __init__(self, runtime: WorkspaceRuntime, resolved: object):
        self.bound_runtime = runtime
        self.resolved = resolved
        self.calls: list[DemoAssetRef] = []

    def resolve_asset(self, ref: DemoAssetRef):
        self.calls.append(ref)
        if isinstance(self.resolved, BaseException):
            raise self.resolved
        return self.resolved


class InspectAdapter:
    def inspect(self, demo_path, original_input):
        return DemoInfo(input_path=str(original_input), demo_path=str(demo_path), map_name="de_mirage")


class FailingInspectAdapter:
    def inspect(self, demo_path, original_input):
        raise RuntimeError(f"cannot inspect {demo_path}")


def runtime_for(tmp_path):
    root = tmp_path / "workspace"
    return WorkspaceRuntime(root, "workspace", 1, 1)


def managed_engine(tmp_path, *, resolved=None, manifest=None, ref=None, display_name="match.dem"):
    runtime = runtime_for(tmp_path)
    store = ArtifactStore.create(runtime.paths.jobs_dir, job_id="job-1")
    ref = ref or make_ref()
    asset_service = RecordingAssetService(runtime, resolved or (tmp_path / "workspace" / "library" / "demos" / "demo.dem"))
    engine = PipelineEngine(
        PipelineConfig(),
        store=store,
        manifest=manifest,
        runtime=runtime,
        demo_asset_ref=ref,
        demo_asset_display_name=display_name,
        demo_assets=asset_service,
    )
    return engine, asset_service, ref


def test_managed_prepare_resolves_asset_without_copying_into_job_input(tmp_path):
    resolved = tmp_path / "workspace" / "library" / "demos" / "source.dem"
    resolved.parent.mkdir(parents=True)
    resolved.write_bytes(b"demo")
    engine, service, ref = managed_engine(tmp_path, resolved=resolved)
    engine.demo_service = DemoService()
    engine.demo_service.prepare_input = lambda *_: pytest.fail("managed mode must not prepare into Job/input")

    engine.run(None, to_stage=StageName.PREPARE_INPUT)

    assert service.calls == [ref]
    assert engine.demo_path == resolved
    assert not list(engine.store.input_dir.iterdir())
    assert "demo_path" not in engine.manifest.artifacts
    assert engine.manifest.demo_asset_ref() == ref


def test_managed_prepare_revalidates_even_when_an_entry_preflight_path_exists(tmp_path):
    resolved = tmp_path / "workspace" / "library" / "demos" / "source.dem"
    resolved.parent.mkdir(parents=True)
    resolved.write_bytes(b"demo")
    engine, service, ref = managed_engine(tmp_path, resolved=resolved)
    engine.demo_path = resolved

    engine.run(None, to_stage=StageName.PREPARE_INPUT)

    assert service.calls == [ref]
    assert engine.demo_path == resolved


def test_managed_prepare_rejects_persistent_source_tampered_after_entry_preflight(tmp_path):
    from cs2pov.workspace.service import WorkspaceService

    runtime = runtime_for(tmp_path)
    WorkspaceService(runtime.paths, minimum_free_bytes=0).initialize()
    source = tmp_path / "external.dem"
    source.write_bytes(b"original-demo")
    assets = DemoAssetApplicationService.for_runtime(runtime)
    result = assets.import_demo(source)
    ref = result.asset.to_ref()
    preflight_path = assets.resolve_asset(ref)
    engine = PipelineEngine(
        PipelineConfig(),
        runtime=runtime,
        demo_asset_ref=ref,
        demo_asset_display_name=result.asset.display_name,
        demo_assets=assets,
    )
    preflight_path.write_bytes(b"tampered-demo")

    with pytest.raises(DemoAssetUseCaseError) as caught:
        engine.run(None, to_stage=StageName.PREPARE_INPUT)

    assert caught.value.code == "demo_asset_integrity_failed"
    assert engine.manifest.stages[StageName.PREPARE_INPUT.value] == "failed"


def test_managed_zst_prepare_re_resolves_when_cache_was_deleted(tmp_path):
    resolved = tmp_path / "workspace" / "cache" / "decompressed_demos" / "asset.dem"
    resolved.parent.mkdir(parents=True)
    resolved.write_bytes(b"demo")
    engine, service, _ = managed_engine(tmp_path, resolved=resolved)
    engine.run(None, to_stage=StageName.PREPARE_INPUT)
    resolved.unlink()
    replacement = resolved.with_name("rebuilt.dem")
    replacement.write_bytes(b"demo")
    service.resolved = replacement

    engine.demo_path = None
    engine.run(None, from_stage=StageName.PREPARE_INPUT, to_stage=StageName.PREPARE_INPUT)

    assert engine.demo_path == replacement
    assert not list(engine.store.input_dir.iterdir())


def test_managed_inspect_persists_only_display_name_and_asset_token(tmp_path):
    resolved = tmp_path / "workspace" / "library" / "demos" / "source.dem"
    resolved.parent.mkdir(parents=True)
    resolved.write_bytes(b"demo")
    engine, service, ref = managed_engine(tmp_path, resolved=resolved, display_name="safe.dem")
    engine.demo_service = DemoService(InspectAdapter())

    engine.run(None, to_stage=StageName.INSPECT_DEMO)

    text = engine.store.demo_info_path.read_text(encoding="utf-8")
    assert "safe.dem" in text
    assert f"demo-asset:{ref.asset_id}" in text
    assert str(tmp_path) not in text
    assert "demo_path" not in engine.manifest.artifacts
    assert service.calls == [ref]


def test_managed_auto_rename_keeps_resolved_asset_path_and_no_job_copy(tmp_path):
    resolved = tmp_path / "workspace" / "library" / "demos" / "source.dem"
    resolved.parent.mkdir(parents=True)
    resolved.write_bytes(b"demo")
    engine, _, _ = managed_engine(tmp_path, resolved=resolved, display_name="safe.dem")
    engine.demo_service = DemoService(InspectAdapter())
    engine.config.job_id = None

    engine.run(None, to_stage=StageName.INSPECT_DEMO)

    assert engine.demo_path == resolved
    assert str(resolved) not in engine.store.demo_info_path.read_text(encoding="utf-8")
    assert not list(engine.store.input_dir.iterdir())


@pytest.mark.parametrize(
    "kwargs",
    [
        {"demo_asset_ref": make_ref()},
        {"demo_asset_display_name": "match.dem"},
        {"demo_assets": object()},
    ],
)
def test_managed_dependency_arguments_must_be_all_or_none_before_job_creation(tmp_path, kwargs):
    runtime = runtime_for(tmp_path)
    with pytest.raises(JobRuntimeError, match="DemoAsset"):
        PipelineEngine(PipelineConfig(), runtime=runtime, **kwargs)
    assert not (tmp_path / "workspace" / "jobs").exists()


def test_managed_service_must_be_bound_to_same_runtime(tmp_path):
    runtime = runtime_for(tmp_path)
    other = WorkspaceRuntime(tmp_path / "other", "other", 1, 1)
    service = RecordingAssetService(other, tmp_path / "other" / "demo.dem")
    with pytest.raises(JobRuntimeError) as caught:
        PipelineEngine(
            PipelineConfig(), runtime=runtime, demo_asset_ref=make_ref(),
            demo_asset_display_name="match.dem", demo_assets=service,
        )
    assert caught.value.code == "demo_asset_runtime_mismatch"


def test_managed_resolve_failure_is_stable_and_does_not_fallback_to_job_input(tmp_path):
    error = DemoAssetUseCaseError("demo_asset_not_found", "当前工作区找不到 Demo。", "请切回原工作区。")
    engine, _, _ = managed_engine(tmp_path, resolved=error)
    fake = engine.store.input_dir / "should-not-be-used.dem"
    fake.write_bytes(b"fake")

    with pytest.raises(DemoAssetUseCaseError) as caught:
        engine.run(None, to_stage=StageName.PREPARE_INPUT)

    assert caught.value.code == "demo_asset_not_found"
    assert fake.exists()


def test_managed_run_rejects_path_and_legacy_run_requires_path(tmp_path):
    engine, _, _ = managed_engine(tmp_path, resolved=tmp_path / "managed.dem")
    with pytest.raises(JobRuntimeError, match="input_path"):
        engine.run(tmp_path / "external.dem", to_stage=StageName.PREPARE_INPUT)

    legacy_store = ArtifactStore.create(tmp_path / "legacy-jobs", job_id="legacy")
    legacy = PipelineEngine(PipelineConfig(), store=legacy_store, runtime=runtime_for(tmp_path / "legacy"))
    with pytest.raises(JobRuntimeError, match="input_path"):
        legacy.run(None, to_stage=StageName.PREPARE_INPUT)


def test_pipeline_demo_helper_imports_and_preflights_once(tmp_path, monkeypatch):
    from cs2pov.cli import pipeline_demo

    runtime = runtime_for(tmp_path)
    ref = make_ref()
    result = type("Result", (), {"asset": type("Asset", (), {"to_ref": lambda self: ref, "display_name": "outside.dem"})(), "disposition": "imported"})()
    calls = []

    class Service:
        bound_runtime = runtime

        def import_demo(self, source):
            calls.append(("import", source))
            return result

        def resolve_asset(self, value):
            calls.append(("resolve", value))
            return tmp_path / "workspace" / "library" / "demos" / "source.dem"

    monkeypatch.setattr(pipeline_demo.DemoAssetApplicationService, "for_runtime", lambda value: calls.append(("bind", value)) or Service())

    preparation = pipeline_demo.prepare_demo_asset(tmp_path / "outside.dem", runtime=runtime)

    assert preparation.runtime is runtime
    assert preparation.service.bound_runtime is runtime
    assert preparation.ref == ref
    assert preparation.display_name == "outside.dem"
    assert preparation.resolved_path == tmp_path / "workspace" / "library" / "demos" / "source.dem"
    assert [name for name, _ in calls] == ["bind", "import", "resolve"]


def test_run_pipeline_passes_bound_asset_and_none_to_engine(monkeypatch, tmp_path, capsys):
    from cs2pov.cli import commands, pipeline_demo

    runtime = runtime_for(tmp_path)
    ref = make_ref()
    service = RecordingAssetService(runtime, tmp_path / "workspace" / "demo.dem")
    preparation = type("Preparation", (), {
        "runtime": runtime, "service": service, "ref": ref, "display_name": "match.dem",
        "resolved_path": tmp_path / "workspace" / "demo.dem",
        "result": type("Result", (), {"disposition": "imported"})(),
    })()
    monkeypatch.setattr(commands, "_resolve_write_runtime", lambda: runtime)
    monkeypatch.setattr(commands, "prepare_demo_asset", lambda source, runtime: preparation)
    seen = {}

    class Engine:
        def __init__(self, config, **kwargs):
            seen["kwargs"] = kwargs
            self.demo_path = None
        def run(self, value, **kwargs):
            seen["run"] = (value, kwargs, self.demo_path)

    monkeypatch.setattr(commands, "PipelineEngine", Engine)
    args = type("Args", (), {
        "whisper_cache_dir": None, "transcription_profile": None, "whisper_model": None,
        "whisper_device": None, "whisper_compute_type": None, "output": None, "map_name": None,
        "pov_steamid": None, "team_number": None, "export_scope": "pov_team", "language": "auto",
        "whisper_vad": None, "transcription_mode": None, "activity_padding": 0.06, "keep_temp_audio": False,
        "llm_base_url": None, "llm_api_key": None, "llm_model": None, "skip_translation": False,
        "dry_run_translation": False, "max_rounds": None, "min_round_duration": 10.0,
        "include_unrecognized_voice": False, "unrecognized_min_duration": 0.35, "filter_hallucinations": None,
        "max_subtitle_segment_seconds": None, "voice_cluster_gap": None, "bilingual_format": None,
        "subtitle_preset": None, "overlap_policy": None, "min_subtitle_duration": None, "glossary": None,
        "player_alias": [], "demo": "outside.dem", "from_stage": None, "to_stage": "prepare_input",
    })()

    assert commands.run_pipeline(args) == 0
    assert seen["kwargs"]["demo_asset_ref"] == ref
    assert seen["kwargs"]["demo_asset_display_name"] == "match.dem"
    assert seen["kwargs"]["demo_assets"] is service
    assert seen["run"] == (None, {"from_stage": None, "to_stage": StageName.PREPARE_INPUT}, None)
    assert "已导入到当前工作区素材库" in capsys.readouterr().out


def test_main_renders_demo_asset_error_without_traceback(monkeypatch, tmp_path, capsys):
    from cs2pov.cli import commands

    runtime = runtime_for(tmp_path)
    monkeypatch.setattr(commands, "_resolve_write_runtime", lambda: runtime)
    monkeypatch.setattr(
        commands,
        "prepare_demo_asset",
        lambda source, runtime: (_ for _ in ()).throw(
            DemoAssetUseCaseError("demo_asset_not_found", "当前工作区找不到 Demo。", "请切回原工作区。")
        ),
    )

    assert commands.main(["run", "outside.dem"]) == 1
    output = capsys.readouterr().out
    assert "demo_asset_not_found" in output
    assert "请切回原工作区" in output
    assert "Traceback" not in output


def test_resume_managed_job_preflights_before_engine_creation(monkeypatch, tmp_path):
    from cs2pov.cli import job_ops

    runtime = runtime_for(tmp_path)
    store = ArtifactStore.create(runtime.paths.jobs_dir, job_id="managed-resume")
    manifest = PipelineManifest.create(store.job_dir.name, PipelineConfig())
    ref = make_ref()
    manifest.bind_demo_asset(ref, "match.dem")
    manifest.save(store.manifest_path)
    events = []

    class Service:
        bound_runtime = runtime
        def resolve_asset(self, value):
            events.append("resolve")
            return tmp_path / "source.dem"

    class Engine:
        def __init__(self, *args, **kwargs):
            events.append("engine")
            self.store = store
            self.demo_path = None
        def run(self, value=None, **kwargs):
            events.append(("run", value, self.demo_path))

    monkeypatch.setattr(job_ops.DemoAssetApplicationService, "for_runtime", lambda value: Service())
    monkeypatch.setattr(job_ops, "PipelineEngine", Engine)
    job_ops.resume_job(store.job_dir, StageName.PREPARE_INPUT, runtime=runtime)

    assert events == ["resolve", "engine", ("run", None, None)]


def test_resume_managed_late_stage_does_not_preflight_missing_asset(monkeypatch, tmp_path):
    from cs2pov.cli import job_ops

    runtime = runtime_for(tmp_path)
    store = ArtifactStore.create(runtime.paths.jobs_dir, job_id="managed-late-resume")
    manifest = PipelineManifest.create(store.job_dir.name, PipelineConfig())
    manifest.bind_demo_asset(make_ref(), "match.dem")
    manifest.save(store.manifest_path)
    calls = []

    class Service:
        bound_runtime = runtime
        def resolve_asset(self, value):
            calls.append("resolve")
            raise DemoAssetUseCaseError("demo_asset_not_found", "找不到", "切回")

    class Engine:
        def __init__(self, *args, **kwargs):
            self.store = store
        def run(self, value=None, **kwargs):
            calls.append(("run", value))

    monkeypatch.setattr(job_ops.DemoAssetApplicationService, "for_runtime", lambda value: Service())
    monkeypatch.setattr(job_ops, "PipelineEngine", Engine)
    job_ops.resume_job(store.job_dir, StageName.TRANSLATE, runtime=runtime)

    assert calls == [("run", None)]


def test_resume_invalid_demo_asset_manifest_uses_stable_error_before_engine(monkeypatch, tmp_path):
    from cs2pov.cli import job_ops

    runtime = runtime_for(tmp_path)
    store = ArtifactStore.create(runtime.paths.jobs_dir, job_id="invalid-resume")
    manifest = PipelineManifest.create(store.job_dir.name, PipelineConfig())
    raw = manifest.to_public_dict()
    raw["demo"] = {"input_mode": "demo_asset", "asset_id": "bad"}
    store.manifest_path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.setattr(job_ops, "PipelineEngine", lambda *args, **kwargs: pytest.fail("engine must not be created"))

    with pytest.raises(JobRuntimeError) as caught:
        job_ops.resume_job(store.job_dir, StageName.PREPARE_INPUT, runtime=runtime)

    assert caught.value.code == "demo_asset_manifest_invalid"


def test_resume_old_job_marks_legacy_without_importing_or_migrating(monkeypatch, tmp_path):
    from cs2pov.cli import job_ops

    runtime = runtime_for(tmp_path)
    store = ArtifactStore.create(runtime.paths.jobs_dir, job_id="old-late-resume")
    manifest = PipelineManifest.create(store.job_dir.name, PipelineConfig())
    manifest.save(store.manifest_path)

    class Engine:
        def __init__(self, *args, manifest, **kwargs):
            assert manifest.demo == {"input_mode": "legacy_job_copy"}
            manifest.save(store.manifest_path)
            self.store = store
        def run(self, value=None, **kwargs):
            assert value == Path(".")

    monkeypatch.setattr(job_ops, "PipelineEngine", Engine)
    monkeypatch.setattr(
        job_ops.DemoAssetApplicationService,
        "for_runtime",
        lambda value: pytest.fail("legacy resume must not create a DemoAsset service"),
    )

    job_ops.resume_job(store.job_dir, StageName.TRANSLATE, runtime=runtime)

    assert PipelineManifest.load(store.manifest_path).demo == {"input_mode": "legacy_job_copy"}


def test_managed_engine_refuses_to_implicitly_migrate_old_manifest(tmp_path):
    runtime = runtime_for(tmp_path)
    store = ArtifactStore.create(runtime.paths.jobs_dir, job_id="old-job")
    old_manifest = PipelineManifest.create("old-job", PipelineConfig())
    service = RecordingAssetService(runtime, runtime.paths.demo_library_dir / "source.dem")

    with pytest.raises(JobRuntimeError) as caught:
        PipelineEngine(
            PipelineConfig(),
            store=store,
            manifest=old_manifest,
            runtime=runtime,
            demo_asset_ref=make_ref(),
            demo_asset_display_name="match.dem",
            demo_assets=service,
        )

    assert caught.value.code == "demo_asset_mode_mismatch"
    assert old_manifest.demo_asset_ref() is None
    assert not store.manifest_path.exists()


def test_managed_progress_and_error_logs_never_publish_workspace_asset_paths(tmp_path):
    resolved = tmp_path / "workspace" / "library" / "demos" / "source.dem"
    resolved.parent.mkdir(parents=True)
    resolved.write_bytes(b"demo")
    engine, _, _ = managed_engine(tmp_path, resolved=resolved, display_name="safe.dem")
    engine.demo_service = DemoService(InspectAdapter())

    engine.run(None, to_stage=StageName.INSPECT_DEMO)

    progress_text = engine.store.progress_log_path.read_text(encoding="utf-8")
    assert str(engine.store.job_dir) not in progress_text
    assert str(resolved) not in progress_text

    failing, _, _ = managed_engine(tmp_path / "failure", resolved=resolved, display_name="safe.dem")
    failing.demo_service = DemoService(FailingInspectAdapter())
    with pytest.raises(RuntimeError, match="cannot inspect"):
        failing.run(None, to_stage=StageName.INSPECT_DEMO)

    combined = failing.store.progress_log_path.read_text(encoding="utf-8")
    combined += failing.store.error_log_path.read_text(encoding="utf-8")
    assert str(failing.demo_assets.bound_runtime.root) not in combined
    assert str(resolved) not in combined
