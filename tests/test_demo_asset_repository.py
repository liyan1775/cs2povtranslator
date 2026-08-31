from __future__ import annotations

from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import subprocess
from uuid import UUID

import pytest

from cs2pov.domain.assets import DemoAsset
from cs2pov.domain.assets import DemoAssetRef
from cs2pov.storage.demo_asset_repository import (
    DemoAssetRepositoryError,
    FileSystemDemoAssetRepository,
)
from cs2pov.workspace.paths import WorkspacePaths


def fixed_clock() -> datetime:
    return datetime(2026, 8, 31, tzinfo=timezone.utc)


def make_paths(tmp_path):
    return WorkspacePaths(tmp_path / "workspace")


def test_import_dem_commits_one_content_addressed_asset(tmp_path):
    source = tmp_path / "中文 比赛.dem"
    payload = b"anonymous-demo-v1"
    source.write_bytes(payload)
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths, clock=fixed_clock)

    result = repo.import_source(source)

    expected = hashlib.sha256(payload).hexdigest()
    assert result.disposition == "imported"
    assert result.asset.asset_id == expected
    assert source.read_bytes() == payload
    asset_dir = paths.demo_library_dir / expected
    assert (asset_dir / "source.dem").read_bytes() == payload
    manifest = json.loads((asset_dir / "asset.json").read_text("utf-8"))
    assert DemoAsset.from_dict(manifest) == result.asset
    assert str(source.resolve()) not in json.dumps(manifest, ensure_ascii=False)
    assert result.persistent_bytes_added == sum(
        path.stat().st_size for path in (asset_dir / "source.dem", asset_dir / "asset.json")
    )
    assert not list((paths.temp_dir / "demo_imports").glob("*/asset"))


def test_import_dem_rejects_compressed_suffix_until_task_four(tmp_path):
    source = tmp_path / "match.dem.zst"
    source.write_bytes(b"not compressed")

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        FileSystemDemoAssetRepository(make_paths(tmp_path)).import_source(source)

    assert getattr(exc_info.value, "code", None) == "demo_source_format_unsupported"


def test_import_dem_reuses_same_content_without_replacing_first_source(tmp_path):
    first = tmp_path / "first.dem"
    second = tmp_path / "renamed.dem"
    first.write_bytes(b"same-demo")
    second.write_bytes(b"same-demo")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths, clock=fixed_clock)

    imported = repo.import_source(first)
    reused = repo.import_source(second)

    assert reused.disposition == "reused"
    assert reused.persistent_bytes_added == 0
    assert reused.asset == imported.asset
    assert reused.asset.display_name == "first.dem"
    assert len(list(paths.demo_library_dir.iterdir())) == 1
    assert (paths.demo_library_dir / imported.asset.asset_id / "source.dem").read_bytes() == b"same-demo"


def test_import_dem_refuses_to_reuse_or_overwrite_corrupt_existing_asset(tmp_path):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    imported = repo.import_source(source)
    asset_dir = paths.demo_library_dir / imported.asset.asset_id
    stored_source = asset_dir / "source.dem"
    stored_source.write_bytes(b"corrupted")

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(source)

    assert exc_info.value.code == "demo_asset_integrity_failed"
    assert stored_source.read_bytes() == b"corrupted"


def test_import_dem_uses_content_hash_and_rejects_bad_inputs(tmp_path):
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    valid = tmp_path / "valid.dem"
    valid.write_bytes(b"valid")

    assert repo.import_source(valid).asset.asset_id == hashlib.sha256(b"valid").hexdigest()
    other = tmp_path / "other.dem"
    other.write_bytes(b"other")
    assert repo.import_source(other).asset.asset_id == hashlib.sha256(b"other").hexdigest()

    cases = [
        (None, "demo_source_required"),
        ("", "demo_source_required"),
        (tmp_path / "missing.dem", "demo_source_not_found"),
        (tmp_path, "demo_source_not_file"),
        (tmp_path / "notes.txt", "demo_source_format_unsupported"),
        (tmp_path / "archive.zst", "demo_source_format_unsupported"),
    ]
    for candidate, code in cases:
        if isinstance(candidate, Path) and candidate.name in {"notes.txt", "archive.zst"}:
            candidate.write_bytes(b"x")
        with pytest.raises(DemoAssetRepositoryError) as exc_info:
            repo.import_source(candidate)
        assert getattr(exc_info.value, "code", None) == code

    empty = tmp_path / "empty.dem"
    empty.touch()
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(empty)
    assert getattr(exc_info.value, "code", None) == "demo_source_empty"


@pytest.mark.parametrize("chunk_size", [True, 0, -1, "1"])
def test_repository_rejects_invalid_chunk_size(chunk_size, tmp_path):
    with pytest.raises((TypeError, ValueError)):
        FileSystemDemoAssetRepository(make_paths(tmp_path), chunk_size=chunk_size)


def test_repository_rejects_invalid_clock_and_id_factory(tmp_path):
    with pytest.raises(TypeError):
        FileSystemDemoAssetRepository(make_paths(tmp_path), clock=None)
    with pytest.raises(TypeError):
        FileSystemDemoAssetRepository(make_paths(tmp_path), id_factory=None)

    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path), id_factory=lambda: "unsafe")
    with pytest.raises(TypeError):
        repo.import_source(source)

    repo = FileSystemDemoAssetRepository(make_paths(tmp_path), clock=lambda: datetime(2026, 8, 31))
    with pytest.raises(TypeError):
        repo.import_source(source)


def test_import_dem_rejects_source_changed_during_copy(tmp_path, monkeypatch):
    source = tmp_path / "changing.dem"
    source.write_bytes(b"before")
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path))
    original_copy = repo._copy_dem

    def copy_then_change(source_path, destination):
        result = original_copy(source_path, destination)
        source_path.write_bytes(b"after")
        return result

    monkeypatch.setattr(repo, "_copy_dem", copy_then_change)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(source)
    assert getattr(exc_info.value, "code", None) == "demo_source_changed"
    assert not list(repo.paths.demo_library_dir.glob("*"))


def test_import_dem_maps_no_space_before_asset_commit(tmp_path, monkeypatch):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path))

    def no_space(*args, **kwargs):
        raise OSError(errno.ENOSPC, "no space")

    monkeypatch.setattr(repo, "_copy_dem", no_space)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(source)
    assert getattr(exc_info.value, "code", None) == "demo_import_space_insufficient"
    assert not list(repo.paths.demo_library_dir.glob("*"))


def test_import_dem_maps_commit_failure_without_visible_asset(tmp_path, monkeypatch):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path))
    original_rename = Path.rename

    def fail_asset_rename(self, target):
        if self.name == "asset":
            raise OSError(errno.EACCES, "denied")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", fail_asset_rename)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(source)
    assert getattr(exc_info.value, "code", None) == "demo_asset_commit_failed"
    assert not list(repo.paths.demo_library_dir.glob("*"))


def test_import_dem_precomputes_result_before_commit_stat_boundary(tmp_path, monkeypatch):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    final_dir = paths.demo_library_dir / hashlib.sha256(b"match").hexdigest()
    original_stat = Path.stat

    def fail_post_commit_stat(self, *args, **kwargs):
        if self in {final_dir / "source.dem", final_dir / "asset.json"}:
            raise OSError(errno.EIO, "post-commit stat unavailable")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fail_post_commit_stat)
    result = repo.import_source(source)

    assert result.disposition == "imported"
    assert result.persistent_bytes_added > len(source.read_bytes())
    assert final_dir.is_dir()


@pytest.mark.parametrize(
    "failure_errno,expected_code",
    [(errno.ENOSPC, "demo_import_space_insufficient"), (errno.EACCES, "demo_asset_commit_failed")],
)
def test_import_dem_maps_destination_open_failure(failure_errno, expected_code, tmp_path, monkeypatch):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path))
    original_open = Path.open

    def fail_destination_open(self, mode="r", *args, **kwargs):
        if self.name == "source.dem" and "w" in mode:
            raise OSError(failure_errno, "destination failure")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_destination_open)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(source)

    assert exc_info.value.code == expected_code
    assert not list(repo.paths.demo_library_dir.glob("*"))


def test_import_dem_maps_source_read_failure(tmp_path, monkeypatch):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path))
    original_open = Path.open

    def fail_source_open(self, mode="r", *args, **kwargs):
        if self == source.resolve() and mode == "rb":
            raise OSError(errno.EACCES, "source failure")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_source_open)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(source)

    assert exc_info.value.code == "demo_source_unreadable"
    assert not list(repo.paths.demo_library_dir.glob("*"))


def test_import_dem_rejects_managed_symlink_before_writing(tmp_path):
    paths = make_paths(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    paths.root.mkdir()
    try:
        (paths.root / "library").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前系统不允许创建目录符号链接")
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        FileSystemDemoAssetRepository(paths).import_source(source)

    assert getattr(exc_info.value, "code", None) == "demo_asset_path_escape"
    assert not (outside / "demos").exists()
    assert not (paths.root / "cache").exists()


@pytest.mark.parametrize("managed_target", ["library", "cache/tmp"])
def test_import_dem_rejects_windows_junction_escape(tmp_path, managed_target):
    if os.name != "nt":
        pytest.skip("Windows junction 仅在 Windows 上测试")
    paths = make_paths(tmp_path)
    outside = tmp_path / "outside-junction"
    outside.mkdir()
    paths.root.mkdir()
    link = paths.root / managed_target
    link.parent.mkdir(parents=True, exist_ok=True)
    command = [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", "mklink", "/J", str(link), str(outside)]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        pytest.skip("当前系统无法创建 Windows junction")
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")

    try:
        with pytest.raises(DemoAssetRepositoryError) as exc_info:
            FileSystemDemoAssetRepository(paths).import_source(source)

        assert exc_info.value.code == "demo_asset_path_escape"
        assert not (outside / "demos").exists()
        assert not (outside / "demo_imports").exists()
    finally:
        if link.exists() or link.is_symlink():
            link.rmdir()


def test_import_dem_rejects_temp_symlink_before_writing(tmp_path):
    paths = make_paths(tmp_path)
    outside = tmp_path / "outside-temp"
    outside.mkdir()
    paths.root.mkdir()
    (paths.root / "cache").mkdir()
    try:
        (paths.root / "cache" / "tmp").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("当前系统不允许创建目录符号链接")
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        FileSystemDemoAssetRepository(paths).import_source(source)

    assert exc_info.value.code == "demo_asset_path_escape"
    assert not (outside / "demo_imports").exists()


def _tree_snapshot(root: Path):
    if not root.exists():
        return ()
    entries = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_file():
            entries.append((rel, "file", hashlib.sha256(path.read_bytes()).hexdigest()))
        elif path.is_dir():
            entries.append((rel, "dir", None))
        else:
            entries.append((rel, "other", None))
    return tuple(entries)


def test_inspect_healthy_dem_is_read_only_and_resolves_source(tmp_path):
    source = tmp_path / "match.dem"
    source.write_bytes(b"inspect-me")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    before = _tree_snapshot(paths.root)

    inspection = repo.inspect_asset(result.asset.asset_id)
    resolved = repo.resolve_asset(result.asset.to_ref())

    assert inspection.asset == result.asset
    assert inspection.source_ok is True
    assert inspection.cache_status == "not_applicable"
    assert inspection.issues == ()
    assert inspection.ok is True
    assert resolved == paths.demo_library_dir / result.asset.asset_id / "source.dem"
    assert _tree_snapshot(paths.root) == before


def test_list_ignores_staging_non_asset_and_link_entries(tmp_path):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    (paths.demo_library_dir / "_diagnostic").mkdir()
    (paths.demo_library_dir / "not-an-asset").mkdir()
    (paths.temp_dir / "demo_imports" / "orphan" / "asset").mkdir(parents=True)
    try:
        (paths.demo_library_dir / "linked").symlink_to(source, target_is_directory=False)
    except (OSError, NotImplementedError):
        pass

    listed = repo.list_assets()

    assert [item.asset_id for item in listed] == [result.asset.asset_id]
    assert listed[0].healthy is True
    assert listed[0].issue_code is None


def test_list_isolates_corrupt_assets_and_keeps_valid_summary(tmp_path):
    good_source = tmp_path / "good.dem"
    bad_source = tmp_path / "bad.dem"
    good_source.write_bytes(b"good")
    bad_source.write_bytes(b"bad")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths, clock=fixed_clock)
    good = repo.import_source(good_source)
    bad = repo.import_source(bad_source)
    (paths.demo_library_dir / bad.asset.asset_id / "source.dem").write_bytes(b"tampered")
    invalid_dir = paths.demo_library_dir / ("a" * 64)
    invalid_dir.mkdir()
    (invalid_dir / "asset.json").write_text("{not-json", encoding="utf-8")

    listed = repo.list_assets()

    by_id = {item.asset_id: item for item in listed}
    assert by_id[good.asset.asset_id].healthy is True
    assert by_id[bad.asset.asset_id].healthy is False
    assert by_id[bad.asset.asset_id].issue_code == "demo_asset_integrity_failed"
    assert by_id["a" * 64].healthy is False
    assert by_id["a" * 64].display_name is None
    assert by_id["a" * 64].issue_code == "demo_asset_manifest_invalid"


def test_list_uses_directory_id_when_manifest_identity_is_corrupt(tmp_path):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    asset_dir = paths.demo_library_dir / result.asset.asset_id
    manifest_path = asset_dir / "asset.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["asset_id"] = "a" * 64
    manifest["logical_sha256"] = "a" * 64
    manifest["source_relative_path"] = f"library/demos/{'a' * 64}/source.dem"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    listed = repo.list_assets()

    assert len(listed) == 1
    assert listed[0].asset_id == result.asset.asset_id
    assert listed[0].healthy is False
    assert listed[0].issue_code == "demo_asset_integrity_failed"


def test_inspect_reports_source_hash_mismatch_without_writing(tmp_path):
    source = tmp_path / "match.dem"
    source.write_bytes(b"original")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    stored = paths.demo_library_dir / result.asset.asset_id / "source.dem"
    stored.write_bytes(b"tampered")
    before = _tree_snapshot(paths.root)

    inspection = repo.inspect_asset(result.asset.asset_id)

    assert inspection.source_ok is False
    assert inspection.cache_status == "not_applicable"
    assert inspection.issues == ("demo_asset_integrity_failed",)
    assert inspection.ok is False
    assert _tree_snapshot(paths.root) == before


@pytest.mark.parametrize(
    "manifest_mutation,expected_code",
    [
        (lambda value: {**value, "extra": True}, "demo_asset_manifest_invalid"),
        (lambda value: {key: item for key, item in value.items() if key != "display_name"}, "demo_asset_manifest_invalid"),
        (lambda value: {**value, "source_relative_path": "library/demos/../outside.dem"}, "demo_asset_path_escape"),
    ],
)
def test_inspect_rejects_invalid_manifest_stably(tmp_path, manifest_mutation, expected_code):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    manifest_path = paths.demo_library_dir / result.asset.asset_id / "asset.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest_path.write_text(json.dumps(manifest_mutation(manifest)), encoding="utf-8")

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.inspect_asset(result.asset.asset_id)

    assert exc_info.value.code == expected_code


@pytest.mark.parametrize("asset_id,expected_code", [("bad", "demo_asset_id_invalid"), ("b" * 64, "demo_asset_not_found")])
def test_inspect_rejects_invalid_or_missing_asset_id(tmp_path, asset_id, expected_code):
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path))

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.inspect_asset(asset_id)

    assert exc_info.value.code == expected_code


def test_resolve_asset_rejects_corrupt_source(tmp_path):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    (paths.demo_library_dir / result.asset.asset_id / "source.dem").write_bytes(b"corrupt")

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.resolve_asset(DemoAssetRef(result.asset.asset_id, f"library/demos/{result.asset.asset_id}/asset.json"))

    assert exc_info.value.code == "demo_asset_integrity_failed"
