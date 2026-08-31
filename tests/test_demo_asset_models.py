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
import cs2pov.domain.assets as assets_module


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


def valid_zst_asset() -> DemoAsset:
    asset = valid_asset().to_dict()
    asset["source_format"] = "dem.zst"
    asset["source_relative_path"] = f"library/demos/{asset['asset_id']}/source.dem.zst"
    return DemoAsset(**asset)


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


def test_demo_asset_ref_round_trips_and_requires_exact_safe_reference_schema():
    asset = valid_asset()
    ref = asset.to_ref()

    from_dict = getattr(DemoAssetRef, "from_dict", None)
    assert callable(from_dict)
    assert from_dict(ref.to_dict()) == ref
    invalid_values = [
        {**ref.to_dict(), "extra": "nope"},
        {"asset_id": ref.asset_id},
        {"asset_manifest_relative_path": ref.asset_manifest_relative_path},
        {"asset_id": "A" * 64, "asset_manifest_relative_path": ref.asset_manifest_relative_path},
        {"asset_id": ref.asset_id, "asset_manifest_relative_path": "D:/outside/asset.json"},
        {"asset_id": ref.asset_id, "asset_manifest_relative_path": "library/demos/other/asset.json"},
    ]
    for value in invalid_values:
        with pytest.raises(ValueError):
            from_dict(value)


def test_display_name_validation_is_shared_domain_entry_point():
    validate_display_name = getattr(assets_module, "validate_display_name", None)
    assert callable(validate_display_name)
    assert validate_display_name("match.dem.zst") == "match.dem.zst"
    with pytest.raises(ValueError):
        validate_display_name("nested/match.dem")


def test_all_dtos_are_json_serializable_and_inspection_cache_missing_is_ok():
    asset = valid_asset()
    compressed_asset = valid_zst_asset()
    values = [
        asset.to_dict(),
        asset.to_ref().to_dict(),
        DemoImportResult(asset, "imported", 128).to_dict(),
        DemoAssetSummary(asset.asset_id, asset.display_name, "dem", 14, 14, asset.imported_at, True, None).to_dict(),
        DemoAssetInspection(compressed_asset, True, "missing", ()).to_dict(),
    ]

    for value in values:
        json.dumps(value, ensure_ascii=False)
    inspection = DemoAssetInspection(compressed_asset, True, "missing", ())
    assert inspection.ok is True
    assert inspection.to_dict()["ok"] is True
    assert DemoAssetInspection(asset, False, "not_applicable", ("demo_asset_integrity_failed",)).ok is False
    assert DemoAssetInspection(compressed_asset, True, "corrupt", ("demo_cache_rebuild_required",)).ok is True


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
        ("display_name", " leading.dem"),
        ("display_name", "trailing.dem "),
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


def test_reused_import_result_cannot_claim_persistent_bytes():
    with pytest.raises(ValueError):
        DemoImportResult(valid_asset(), "reused", 1)


@pytest.mark.parametrize(
    "healthy,issue_code",
    [(True, "demo_asset_integrity_failed"), (False, None), (False, "")],
)
def test_asset_summary_requires_consistent_health_and_issue(healthy, issue_code):
    asset = valid_asset()
    with pytest.raises(ValueError):
        DemoAssetSummary(asset.asset_id, asset.display_name, "dem", 14, 14, asset.imported_at, healthy, issue_code)


@pytest.mark.parametrize("cache_status", ["", "missing-cache", "corrupted"])
def test_inspection_rejects_unknown_cache_status(cache_status):
    with pytest.raises(ValueError):
        DemoAssetInspection(valid_zst_asset(), True, cache_status, ())


def test_corrupt_cache_does_not_make_persistent_asset_unhealthy():
    inspection = DemoAssetInspection(valid_zst_asset(), True, "corrupt", ("demo_cache_rebuild_required",))

    assert inspection.ok is True


def test_persistent_integrity_issue_cannot_be_hidden_by_source_ok():
    with pytest.raises(ValueError):
        DemoAssetInspection(valid_zst_asset(), True, "valid", ("demo_asset_integrity_failed",))


@pytest.mark.parametrize(
    "asset,cache_status",
    [(valid_asset(), "missing"), (valid_asset(), "corrupt"), (valid_zst_asset(), "not_applicable")],
)
def test_inspection_rejects_incompatible_source_format_and_cache_status(asset, cache_status):
    with pytest.raises(ValueError):
        DemoAssetInspection(asset, True, cache_status, ())


@pytest.mark.parametrize("issues", [(), ("demo_cache_rebuild_required",)])
def test_source_not_ok_requires_a_persistent_source_issue(issues):
    with pytest.raises(ValueError):
        DemoAssetInspection(valid_asset(), False, "not_applicable", issues)
