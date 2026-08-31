from __future__ import annotations

import json

import pytest

from cs2pov.domain.assets import DemoAssetRef
from cs2pov.domain.models import PipelineConfig
from cs2pov.pipeline.manifest import PipelineManifest


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
