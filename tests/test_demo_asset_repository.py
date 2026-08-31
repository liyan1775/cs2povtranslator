from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import UUID

import pytest
import zstandard

import cs2pov.storage.demo_asset_repository as demo_asset_repository
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


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("odd\nname.dem", "odd_name.dem"),
        ("odd\\name.dem", "odd_name.dem"),
        ("  readable demo.dem  ", "readable demo.dem"),
    ],
)
def test_display_name_normalization_removes_unsafe_filename_characters(raw, expected):
    assert demo_asset_repository._normalize_display_name(raw) == expected


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


@pytest.mark.skipif(os.name == "nt", reason="Win32 文件名不允许控制字符或反斜线")
@pytest.mark.parametrize("source_name", ["odd\nname.dem", "odd\\name.dem"])
def test_import_dem_normalizes_unsafe_posix_display_name(source_name, tmp_path):
    source = tmp_path / source_name
    source.write_bytes(b"anonymous-demo")
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path), clock=fixed_clock)

    result = repo.import_source(source)

    assert result.asset.display_name == "odd_name.dem"
    manifest_path = repo.paths.demo_library_dir / result.asset.asset_id / "asset.json"
    assert json.loads(manifest_path.read_text("utf-8"))["display_name"] == "odd_name.dem"


def test_import_zst_reports_decompression_failure_for_invalid_source(tmp_path):
    source = tmp_path / "match.dem.zst"
    source.write_bytes(b"not compressed")

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        FileSystemDemoAssetRepository(make_paths(tmp_path)).import_source(source)

    assert exc_info.value.code == "demo_decompression_failed"


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


def test_import_dem_treats_enotempty_directory_race_as_reused_winner(tmp_path, monkeypatch):
    source = tmp_path / "match.dem"
    source.write_bytes(b"same-logical-demo")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths, clock=fixed_clock)
    original_rename = Path.rename

    def emulate_posix_competing_winner(self, target):
        if self.name == "asset":
            shutil.copytree(self, target)
            raise OSError(errno.ENOTEMPTY, "competing directory is not empty")
        return original_rename(self, target)

    monkeypatch.setattr(Path, "rename", emulate_posix_competing_winner)

    result = repo.import_source(source)

    assert result.disposition == "reused"
    assert result.persistent_bytes_added == 0
    asset_dir = paths.demo_library_dir / result.asset.asset_id
    assert {path.name for path in asset_dir.iterdir()} == {"asset.json", "source.dem"}
    assert (asset_dir / "source.dem").read_bytes() == source.read_bytes()


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


class _FailingWriter:
    def __init__(self, wrapped, error_number):
        self._wrapped = wrapped
        self._error_number = error_number

    def __enter__(self):
        self._wrapped.__enter__()
        return self

    def __exit__(self, *args):
        return self._wrapped.__exit__(*args)

    def write(self, data):
        raise OSError(self._error_number, "destination write failure")

    def __getattr__(self, name):
        return getattr(self._wrapped, name)


@pytest.mark.parametrize(
    "failure_errno,expected_code",
    [(errno.ENOSPC, "demo_import_space_insufficient"), (errno.EACCES, "demo_asset_commit_failed")],
)
def test_import_dem_maps_destination_write_failure(failure_errno, expected_code, tmp_path, monkeypatch):
    source = tmp_path / "match.dem"
    payload = b"unchanged-source"
    source.write_bytes(payload)
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path))
    original_open = Path.open

    def wrap_destination_open(self, mode="r", *args, **kwargs):
        handle = original_open(self, mode, *args, **kwargs)
        if self.name == "source.dem" and "w" in mode:
            return _FailingWriter(handle, failure_errno)
        return handle

    monkeypatch.setattr(Path, "open", wrap_destination_open)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(source)

    assert exc_info.value.code == expected_code
    assert source.read_bytes() == payload
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


def test_list_assets_sorts_by_imported_at_then_asset_id_deterministically(tmp_path):
    payloads = [b"later", b"same-b", b"same-a"]
    sources = []
    for index, payload in enumerate(payloads):
        source = tmp_path / f"{index}.dem"
        source.write_bytes(payload)
        sources.append(source)
    timestamps = iter(
        [
            datetime(2026, 8, 31, 0, 0, 2, tzinfo=timezone.utc),
            datetime(2026, 8, 31, 0, 0, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 31, 0, 0, 1, tzinfo=timezone.utc),
        ]
    )
    repo = FileSystemDemoAssetRepository(make_paths(tmp_path), clock=lambda: next(timestamps))
    results = [repo.import_source(source) for source in sources]

    first = repo.list_assets()
    second = repo.list_assets()
    same_time_ids = sorted(
        result.asset.asset_id
        for result in results
        if result.asset.imported_at == "2026-08-31T00:00:01.000000Z"
    )

    assert first == second
    assert [item.imported_at for item in first] == [
        "2026-08-31T00:00:01.000000Z",
        "2026-08-31T00:00:01.000000Z",
        "2026-08-31T00:00:02.000000Z",
    ]
    assert [item.asset_id for item in first[:2]] == same_time_ids


def _create_directory_link(link: Path, target: Path):
    if os.name == "nt":
        completed = subprocess.run(
            [os.environ.get("ComSpec", "cmd.exe"), "/d", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            pytest.skip("当前系统无法创建 Windows junction")
    else:
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("当前系统不允许创建目录符号链接")


def _remove_directory_link(link: Path):
    if link.exists() or link.is_symlink():
        link.rmdir() if os.name == "nt" else link.unlink()


def test_legal_asset_directory_link_is_not_listed_and_inspect_rejects(tmp_path):
    paths = make_paths(tmp_path)
    paths.demo_library_dir.mkdir(parents=True)
    outside = tmp_path / "outside-asset"
    outside.mkdir()
    asset_id = hashlib.sha256(b"linked-asset").hexdigest()
    link = paths.demo_library_dir / asset_id
    _create_directory_link(link, outside)
    before = _tree_snapshot(outside)
    try:
        repo = FileSystemDemoAssetRepository(paths)
        assert repo.list_assets() == ()
        with pytest.raises(DemoAssetRepositoryError) as exc_info:
            repo.inspect_asset(asset_id)
        assert exc_info.value.code == "demo_asset_path_escape"
        assert _tree_snapshot(outside) == before
    finally:
        _remove_directory_link(link)


def test_manifest_symlink_is_rejected_without_following_external_file(tmp_path):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    asset_dir = paths.demo_library_dir / result.asset.asset_id
    manifest = asset_dir / "asset.json"
    external_manifest = tmp_path / "external-asset.json"
    external_manifest.write_bytes(manifest.read_bytes())
    manifest.unlink()
    try:
        manifest.symlink_to(external_manifest)
    except (OSError, NotImplementedError):
        pytest.skip("当前系统不允许创建文件符号链接")
    before = external_manifest.read_bytes()
    try:
        with pytest.raises(DemoAssetRepositoryError) as exc_info:
            repo.inspect_asset(result.asset.asset_id)
        assert exc_info.value.code == "demo_asset_manifest_invalid"
        assert external_manifest.read_bytes() == before
    finally:
        if manifest.exists() or manifest.is_symlink():
            manifest.unlink()


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


def test_list_reports_missing_manifest_as_unhealthy_summary(tmp_path):
    source = tmp_path / "match.dem"
    source.write_bytes(b"match")
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    (paths.demo_library_dir / result.asset.asset_id / "asset.json").unlink()

    listed = repo.list_assets()

    assert len(listed) == 1
    assert listed[0].asset_id == result.asset.asset_id
    assert listed[0].display_name is None
    assert listed[0].healthy is False
    assert listed[0].issue_code == "demo_asset_manifest_invalid"


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


def _zst_payload(logical: bytes, level: int) -> bytes:
    return zstandard.ZstdCompressor(level=level).compress(logical)


def test_import_zst_deduplicates_by_logical_content_and_preserves_first_source(tmp_path):
    logical = bytes(range(256)) * 4096
    zst_a = _zst_payload(logical, 1)
    zst_b = _zst_payload(logical, 9)
    assert zst_a != zst_b
    path_a = tmp_path / "alpha.dem.zst"
    path_b = tmp_path / "beta.dem.zst"
    plain = tmp_path / "plain.dem"
    path_a.write_bytes(zst_a)
    path_b.write_bytes(zst_b)
    plain.write_bytes(logical)
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)

    first = repo.import_source(path_a)
    second = repo.import_source(path_b)
    third = repo.import_source(plain)

    expected_id = hashlib.sha256(logical).hexdigest()
    assert {first.asset.asset_id, second.asset.asset_id, third.asset.asset_id} == {expected_id}
    assert first.disposition == "imported"
    assert second.disposition == "reused"
    assert third.disposition == "reused"
    asset_dir = paths.demo_library_dir / expected_id
    assert first.asset.source_format == "dem.zst"
    assert first.asset.logical_sha256 == expected_id
    assert first.asset.source_sha256 == hashlib.sha256(zst_a).hexdigest()
    assert (asset_dir / "source.dem.zst").read_bytes() == zst_a
    assert not (asset_dir / "source.dem").exists()
    assert (paths.decompressed_demos_cache_dir / f"{expected_id}.dem").read_bytes() == logical
    assert first.persistent_bytes_added == sum(
        path.stat().st_size for path in (asset_dir / "source.dem.zst", asset_dir / "asset.json")
    )
    assert path_a.read_bytes() == zst_a


def test_import_dem_first_keeps_plain_source_when_zst_is_reused(tmp_path):
    logical = b"plain-first" * 1024
    plain = tmp_path / "plain.dem"
    compressed = tmp_path / "compressed.dem.zst"
    plain.write_bytes(logical)
    compressed.write_bytes(_zst_payload(logical, 3))
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)

    first = repo.import_source(plain)
    second = repo.import_source(compressed)

    asset_dir = paths.demo_library_dir / first.asset.asset_id
    assert second.disposition == "reused"
    assert first.asset.source_format == "dem"
    assert (asset_dir / "source.dem").read_bytes() == logical
    assert not (asset_dir / "source.dem.zst").exists()


def test_inspect_zst_cache_is_read_only_and_resolve_rebuilds_missing_or_corrupt_cache(tmp_path):
    logical = b"cache-content" * 1024
    source = tmp_path / "cache.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    cache = paths.decompressed_demos_cache_dir / f"{result.asset.asset_id}.dem"
    before = _tree_snapshot(paths.root)

    valid = repo.inspect_asset(result.asset.asset_id)
    assert valid.source_ok is True
    assert valid.cache_status == "valid"
    assert valid.ok is True
    assert _tree_snapshot(paths.root) == before

    cache.unlink()
    missing_before = _tree_snapshot(paths.root)
    missing = repo.inspect_asset(result.asset.asset_id)
    assert missing.cache_status == "missing"
    assert missing.ok is True
    assert _tree_snapshot(paths.root) == missing_before

    resolved = repo.resolve_asset(result.asset.to_ref())
    assert resolved == cache
    assert cache.read_bytes() == logical

    cache.write_bytes(b"x" * len(logical))
    corrupt = repo.inspect_asset(result.asset.asset_id)
    assert corrupt.cache_status == "corrupt"
    assert corrupt.ok is True
    assert repo.resolve_asset(result.asset.to_ref()) == cache
    assert cache.read_bytes() == logical


def test_resolve_zst_validates_persistent_source_before_using_cache(tmp_path):
    logical = b"source-integrity" * 512
    source = tmp_path / "source.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    stored = paths.demo_library_dir / result.asset.asset_id / "source.dem.zst"
    stored.write_bytes(b"damaged-source")
    cache = paths.decompressed_demos_cache_dir / f"{result.asset.asset_id}.dem"
    cache_before = cache.read_bytes()

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.resolve_asset(result.asset.to_ref())

    assert exc_info.value.code == "demo_asset_integrity_failed"
    assert cache.read_bytes() == cache_before


def test_zst_consistent_source_manifest_tamper_cannot_change_content_identity(tmp_path):
    logical = b"original-logical-content" * 512
    replacement_logical = b"different-logical-content" * 512
    source = tmp_path / "source.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    result = repo.import_source(source)
    asset_dir = paths.demo_library_dir / result.asset.asset_id
    stored = asset_dir / "source.dem.zst"
    manifest_path = asset_dir / "asset.json"
    replacement_source = _zst_payload(replacement_logical, 1)
    stored.write_bytes(replacement_source)
    manifest = json.loads(manifest_path.read_text("utf-8"))
    manifest["source_sha256"] = hashlib.sha256(replacement_source).hexdigest()
    manifest["source_size_bytes"] = len(replacement_source)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    asset_before = _tree_snapshot(asset_dir)
    cache = paths.decompressed_demos_cache_dir / f"{result.asset.asset_id}.dem"
    cache_before = cache.read_bytes()

    inspection = repo.inspect_asset(result.asset.asset_id)
    listed = repo.list_assets()

    assert inspection.source_ok is False
    assert inspection.issues == ("demo_asset_integrity_failed",)
    assert len(listed) == 1
    assert listed[0].healthy is False
    assert listed[0].issue_code == "demo_asset_integrity_failed"
    with pytest.raises(DemoAssetRepositoryError) as resolve_error:
        repo.resolve_asset(result.asset.to_ref())
    assert resolve_error.value.code == "demo_asset_integrity_failed"
    with pytest.raises(DemoAssetRepositoryError) as import_error:
        repo.import_source(source)
    assert import_error.value.code == "demo_asset_integrity_failed"
    assert _tree_snapshot(asset_dir) == asset_before
    assert cache.read_bytes() == cache_before


def test_reimport_zst_rebuilds_missing_cache_without_replacing_first_source(tmp_path):
    logical = bytes(range(256)) * 4096
    first_bytes = _zst_payload(logical, 1)
    second_bytes = _zst_payload(logical, 9)
    assert first_bytes != second_bytes
    first_source = tmp_path / "first.dem.zst"
    second_source = tmp_path / "second.dem.zst"
    first_source.write_bytes(first_bytes)
    second_source.write_bytes(second_bytes)
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    imported = repo.import_source(first_source)
    asset_dir = paths.demo_library_dir / imported.asset.asset_id
    cache = paths.decompressed_demos_cache_dir / f"{imported.asset.asset_id}.dem"
    cache.unlink()

    reused = repo.import_source(second_source)

    assert reused.disposition == "reused"
    assert reused.persistent_bytes_added == 0
    assert reused.asset == imported.asset
    assert (asset_dir / "source.dem.zst").read_bytes() == first_bytes
    assert cache.read_bytes() == logical


def test_cache_commit_failure_keeps_persistent_asset_and_retry_repairs_cache(tmp_path, monkeypatch):
    logical = b"persistent-before-cache" * 1024
    source = tmp_path / "match.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    expected_id = hashlib.sha256(logical).hexdigest()

    def fail_cache_commit(*args, **kwargs):
        raise DemoAssetRepositoryError(
            "demo_cache_rebuild_failed",
            "缓存提交失败。",
            "请重试。",
        )

    monkeypatch.setattr(repo, "_commit_cache", fail_cache_commit)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(source)

    assert exc_info.value.code == "demo_cache_rebuild_failed"
    asset_dir = paths.demo_library_dir / expected_id
    assert (asset_dir / "asset.json").is_file()
    assert (asset_dir / "source.dem.zst").read_bytes() == source.read_bytes()
    assert not (paths.decompressed_demos_cache_dir / f"{expected_id}.dem").exists()

    repaired = FileSystemDemoAssetRepository(paths).import_source(source)
    assert repaired.disposition == "reused"
    assert (paths.decompressed_demos_cache_dir / f"{expected_id}.dem").read_bytes() == logical


def test_cache_root_creation_failure_after_asset_commit_has_cache_error(tmp_path, monkeypatch):
    logical = b"cache-root-failure" * 2048
    source = tmp_path / "match.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    expected_id = hashlib.sha256(logical).hexdigest()
    original_mkdir = Path.mkdir

    def fail_cache_root_mkdir(self, *args, **kwargs):
        if self == paths.decompressed_demos_cache_dir:
            raise OSError(errno.EACCES, "cache root denied")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", fail_cache_root_mkdir)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        FileSystemDemoAssetRepository(paths).import_source(source)

    assert exc_info.value.code == "demo_cache_rebuild_failed"
    asset_dir = paths.demo_library_dir / expected_id
    assert (asset_dir / "asset.json").is_file()
    assert (asset_dir / "source.dem.zst").is_file()


def test_resolve_maps_staging_creation_failure_to_cache_error(tmp_path, monkeypatch):
    logical = b"resolve-staging-failure" * 1024
    source = tmp_path / "match.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    result = FileSystemDemoAssetRepository(paths).import_source(source)
    cache = paths.decompressed_demos_cache_dir / f"{result.asset.asset_id}.dem"
    cache.unlink()
    repo = FileSystemDemoAssetRepository(paths)

    def fail_staging(*args, **kwargs):
        raise OSError(errno.ENOSPC, "staging full")

    monkeypatch.setattr(repo, "_make_staging_root", fail_staging)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.resolve_asset(result.asset.to_ref())

    assert exc_info.value.code == "demo_cache_rebuild_failed"
    assert not cache.exists()


def test_concurrent_resolve_rebuilds_one_valid_cache(tmp_path):
    logical = b"threaded-cache-rebuild" * 8192
    source = tmp_path / "match.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    result = FileSystemDemoAssetRepository(paths).import_source(source)
    cache = paths.decompressed_demos_cache_dir / f"{result.asset.asset_id}.dem"
    cache.unlink()

    def resolve_once(_):
        return FileSystemDemoAssetRepository(paths).resolve_asset(result.asset.to_ref())

    with ThreadPoolExecutor(max_workers=8) as pool:
        resolved = list(pool.map(resolve_once, range(16)))

    assert resolved == [cache] * 16
    assert cache.read_bytes() == logical
    assert [path.name for path in paths.decompressed_demos_cache_dir.iterdir()] == [cache.name]


def test_cache_directory_target_is_rejected_without_deleting_it(tmp_path):
    logical = b"directory-cache-target" * 512
    source = tmp_path / "match.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    result = FileSystemDemoAssetRepository(paths).import_source(source)
    cache = paths.decompressed_demos_cache_dir / f"{result.asset.asset_id}.dem"
    cache.unlink()
    cache.mkdir()
    marker = cache / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        FileSystemDemoAssetRepository(paths).resolve_asset(result.asset.to_ref())

    assert exc_info.value.code == "demo_asset_path_escape"
    assert marker.read_text("utf-8") == "keep"


def test_corrupt_cache_replace_failure_preserves_cache_and_persistent_asset(tmp_path, monkeypatch):
    logical = b"replace-failure" * 2048
    source = tmp_path / "match.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    result = FileSystemDemoAssetRepository(paths).import_source(source)
    cache = paths.decompressed_demos_cache_dir / f"{result.asset.asset_id}.dem"
    corrupt_bytes = b"corrupt-cache"
    cache.write_bytes(corrupt_bytes)
    asset_before = _tree_snapshot(paths.demo_library_dir / result.asset.asset_id)
    original_replace = os.replace

    def fail_candidate_replace(source_path, destination_path):
        if Path(source_path).name == "logical.dem" and Path(destination_path) == cache:
            raise OSError(errno.EACCES, "cache replace denied")
        return original_replace(source_path, destination_path)

    monkeypatch.setattr(os, "replace", fail_candidate_replace)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        FileSystemDemoAssetRepository(paths).resolve_asset(result.asset.to_ref())

    assert exc_info.value.code == "demo_cache_rebuild_failed"
    assert cache.read_bytes() == corrupt_bytes
    assert _tree_snapshot(paths.demo_library_dir / result.asset.asset_id) == asset_before


def test_cache_file_symlink_is_rejected_without_touching_external_file(tmp_path):
    logical = b"linked-cache" * 512
    source = tmp_path / "match.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    result = FileSystemDemoAssetRepository(paths).import_source(source)
    cache = paths.decompressed_demos_cache_dir / f"{result.asset.asset_id}.dem"
    cache.unlink()
    external = tmp_path / "external-cache.dem"
    external.write_bytes(b"external-must-stay")
    try:
        cache.symlink_to(external)
    except (OSError, NotImplementedError):
        pytest.skip("当前系统不允许创建文件符号链接")
    before = external.read_bytes()
    try:
        with pytest.raises(DemoAssetRepositoryError) as exc_info:
            FileSystemDemoAssetRepository(paths).resolve_asset(result.asset.to_ref())
        assert exc_info.value.code == "demo_asset_path_escape"
        assert external.read_bytes() == before
    finally:
        if cache.exists() or cache.is_symlink():
            cache.unlink()


def test_valid_empty_or_truncated_zst_never_commits_asset(tmp_path):
    paths = make_paths(tmp_path)
    empty = tmp_path / "empty.dem.zst"
    empty.write_bytes(zstandard.ZstdCompressor().compress(b""))
    truncated = tmp_path / "truncated.dem.zst"
    compressed = zstandard.ZstdCompressor(write_content_size=False).compress(b"content" * 1024)
    truncated.write_bytes(compressed[:-1])

    with pytest.raises(DemoAssetRepositoryError) as empty_error:
        FileSystemDemoAssetRepository(paths).import_source(empty)
    with pytest.raises(DemoAssetRepositoryError) as truncated_error:
        FileSystemDemoAssetRepository(paths).import_source(truncated)

    assert empty_error.value.code == "demo_source_empty"
    assert truncated_error.value.code == "demo_decompression_failed"
    assert not paths.demo_library_dir.exists() or not list(paths.demo_library_dir.iterdir())


def test_import_zst_rejects_source_changed_during_copy(tmp_path, monkeypatch):
    source = tmp_path / "changing.dem.zst"
    source.write_bytes(_zst_payload(b"before" * 1024, 1))
    paths = make_paths(tmp_path)
    repo = FileSystemDemoAssetRepository(paths)
    original_copy = repo._copy_zst

    def copy_then_change(source_path, compressed_destination, logical_destination):
        result = original_copy(source_path, compressed_destination, logical_destination)
        source_path.write_bytes(_zst_payload(b"after" * 2048, 1))
        return result

    monkeypatch.setattr(repo, "_copy_zst", copy_then_change)
    with pytest.raises(DemoAssetRepositoryError) as exc_info:
        repo.import_source(source)

    assert exc_info.value.code == "demo_source_changed"
    assert not paths.demo_library_dir.exists() or not list(paths.demo_library_dir.iterdir())
    assert not paths.decompressed_demos_cache_dir.exists() or not list(paths.decompressed_demos_cache_dir.iterdir())


def test_decompressed_cache_root_junction_is_rejected_without_external_write(tmp_path):
    if os.name != "nt":
        pytest.skip("Windows junction 仅在 Windows 上测试")
    logical = b"junction-cache-root" * 128
    source = tmp_path / "match.dem.zst"
    source.write_bytes(_zst_payload(logical, 1))
    paths = make_paths(tmp_path)
    paths.cache_dir.mkdir(parents=True)
    outside = tmp_path / "outside-cache"
    outside.mkdir()
    link = paths.decompressed_demos_cache_dir
    _create_directory_link(link, outside)
    before = _tree_snapshot(outside)
    try:
        with pytest.raises(DemoAssetRepositoryError) as exc_info:
            FileSystemDemoAssetRepository(paths).import_source(source)
        assert exc_info.value.code == "demo_asset_path_escape"
        assert _tree_snapshot(outside) == before
        assert not paths.demo_library_dir.exists()
    finally:
        _remove_directory_link(link)
