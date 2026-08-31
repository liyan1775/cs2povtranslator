from __future__ import annotations

import hashlib
import json

import pytest

from cs2pov.domain.assets import (
    DemoAsset,
    DemoAssetInspection,
    DemoAssetRef,
    DemoAssetSummary,
    DemoImportResult,
)


def valid_asset() -> DemoAsset:
    asset_id = hashlib.sha256(b"anonymous-demo").hexdigest()
    return DemoAsset(
        schema_version=1,
        asset_id=asset_id,
        logical_sha256=asset_id,
        logical_size_bytes=14,
        source_sha256=asset_id,
        source_size_bytes=14,
        source_format="dem",
        source_relative_path=f"library/demos/{asset_id}/source.dem",
        display_name="match.dem",
        imported_at="2026-08-31T00:00:00.000000Z",
    )


def test_demo_asset_round_trips_exact_schema():
    asset = valid_asset()

    assert DemoAsset.from_dict(asset.to_dict()) == asset
    assert set(asset.to_dict()) == {
        "schema_version",
        "asset_id",
        "logical_sha256",
        "logical_size_bytes",
        "source_sha256",
        "source_size_bytes",
        "source_format",
        "source_relative_path",
        "display_name",
        "imported_at",
    }


def test_demo_asset_ref_has_exact_stable_schema():
    asset = valid_asset()
    ref = asset.to_ref()

    assert ref == DemoAssetRef(asset.asset_id, f"library/demos/{asset.asset_id}/asset.json")
    assert ref.to_dict() == {
        "asset_id": asset.asset_id,
        "asset_manifest_relative_path": f"library/demos/{asset.asset_id}/asset.json",
    }


def test_all_dtos_are_json_serializable_and_inspection_cache_missing_is_ok():
    asset = valid_asset()
    values = [
        asset.to_dict(),
        asset.to_ref().to_dict(),
        DemoImportResult(asset, "imported", 128).to_dict(),
        DemoAssetSummary(asset.asset_id, asset.display_name, "dem", 14, 14, asset.imported_at, True, None).to_dict(),
        DemoAssetInspection(asset, True, "missing", ()).to_dict(),
    ]

    for value in values:
        json.dumps(value, ensure_ascii=False)
    inspection = DemoAssetInspection(asset, True, "missing", ())
    assert inspection.ok is True
    assert inspection.to_dict()["ok"] is True
    assert DemoAssetInspection(asset, False, "missing", ()).ok is False
    assert DemoAssetInspection(asset, True, "valid", ("demo_asset_integrity_failed",)).ok is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("asset_id", "A" * 64),
        ("asset_id", "0" * 63),
        ("logical_sha256", "1" * 64),
        ("source_sha256", "not-a-hash"),
        ("logical_size_bytes", True),
        ("logical_size_bytes", -1),
        ("source_size_bytes", False),
        ("source_size_bytes", -1),
        ("source_format", "zip"),
        ("source_relative_path", "library\\demos\\bad\\source.dem"),
        ("source_relative_path", "D:/outside/source.dem"),
        ("source_relative_path", "library/demos//source.dem"),
        ("source_relative_path", "library/demos/./source.dem"),
        ("source_relative_path", "library/demos/../source.dem"),
        ("display_name", ""),
        ("display_name", "name/with-slash.dem"),
        ("display_name", "name\\with-slash.dem"),
        ("display_name", "bad\nname.dem"),
        ("display_name", "x" * 256),
        ("imported_at", "2026-08-31T00:00:00Z"),
        ("imported_at", "2026-08-31T00:00:00.000000+00:00"),
        ("imported_at", "2026-08-31T00:00:00.000000+0800"),
    ],
)
def test_demo_asset_rejects_invalid_field(field, value):
    with pytest.raises(ValueError):
        DemoAsset(**{**valid_asset().to_dict(), field: value})


def test_demo_asset_rejects_mismatched_identity_and_suffix():
    asset = valid_asset()
    with pytest.raises(ValueError):
        DemoAsset(**{**asset.to_dict(), "logical_sha256": "0" * 64})
    with pytest.raises(ValueError):
        DemoAsset(**{**asset.to_dict(), "source_relative_path": f"library/demos/{asset.asset_id}/source.dem.zst"})
    with pytest.raises(ValueError):
        DemoAsset(**{**asset.to_dict(), "source_format": "dem.zst"})


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {**valid_asset().to_dict(), "future": 1},
        {key: value for key, value in valid_asset().to_dict().items() if key != "display_name"},
    ],
)
def test_demo_asset_from_dict_requires_exact_mapping(value):
    with pytest.raises(ValueError):
        DemoAsset.from_dict(value)


@pytest.mark.parametrize("disposition", ["", "import", "reused "])
def test_import_result_rejects_unknown_disposition(disposition):
    with pytest.raises(ValueError):
        DemoImportResult(valid_asset(), disposition, 0)


@pytest.mark.parametrize("cache_status", ["", "missing-cache", "corrupted"])
def test_inspection_rejects_unknown_cache_status(cache_status):
    with pytest.raises(ValueError):
        DemoAssetInspection(valid_asset(), True, cache_status, ())
