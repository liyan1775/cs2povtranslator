from __future__ import annotations

import json

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


def runtime_for(tmp_path):
    root = tmp_path / "workspace"
    return WorkspaceRuntime(root, "workspace", 1, 1)


def managed_engine(tmp_path, *, resolved=None, manifest=None, ref=None, display_name="match.dem"):
    runtime = runtime_for(tmp_path)
    store = ArtifactStore.create(tmp_path / "jobs", job_id="job-1")
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
    engine, _, ref = managed_engine(tmp_path, resolved=resolved, display_name="safe.dem")
    engine.demo_service = DemoService(InspectAdapter())

    engine.run(None, to_stage=StageName.INSPECT_DEMO)

    text = engine.store.demo_info_path.read_text(encoding="utf-8")
    assert "safe.dem" in text
    assert f"demo-asset:{ref.asset_id}" in text
    assert str(tmp_path) not in text
    assert "demo_path" not in engine.manifest.artifacts


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
