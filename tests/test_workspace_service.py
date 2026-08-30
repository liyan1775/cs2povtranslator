import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from cs2pov.workspace.errors import (
    WorkspaceConfigError,
    WorkspaceInitializationError,
    WorkspaceInsufficientSpaceError,
    WorkspaceLayoutError,
)
from cs2pov.workspace.models import WorkspaceConfig
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService


def test_config_round_trip_and_fixed_schema():
    value = WorkspaceConfig(1, 1, "12345678-1234-5678-1234-567812345678", "2026-08-30T12:34:56.123456Z")
    assert list(value.to_dict()) == ["schema_version", "layout_version", "workspace_id", "created_at"]
    assert WorkspaceConfig.from_dict(value.to_dict()) == value
    for bad in [
        {**value.to_dict(), "extra": 1},
        {**value.to_dict(), "schema_version": 2},
        {**value.to_dict(), "workspace_id": "not-uuid"},
        {**value.to_dict(), "created_at": "2026-08-30T12:34:56"},
        {**value.to_dict(), "created_at": "2026-08-30T12:34:56+08:00"},
    ]:
        with pytest.raises(WorkspaceConfigError):
            WorkspaceConfig.from_dict(bad)


def test_initialize_creates_layout_and_safe_config(tmp_path):
    paths = WorkspacePaths(tmp_path / "中文 工作区")
    config = WorkspaceService(paths, minimum_free_bytes=0).initialize()
    assert paths.root.exists()
    assert all(directory.is_dir() for directory in paths.all_directories())
    assert json.loads(paths.config_file.read_text(encoding="utf-8")) == config.to_dict()
    raw = paths.config_file.read_text(encoding="utf-8")
    assert "root" not in raw.lower() and "path" not in raw.lower() and "key" not in raw.lower() and "steamid" not in raw.lower()
    assert raw.endswith("\n")


def test_initialize_is_idempotent_and_repairs_managed_directory(tmp_path):
    paths = WorkspacePaths(tmp_path / "ws")
    service = WorkspaceService(paths, minimum_free_bytes=0)
    first = service.initialize()
    paths.audio_cache_dir.rmdir()
    second = service.initialize()
    assert second == first
    assert paths.audio_cache_dir.is_dir()


def test_initialize_preserves_unmanaged_file(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    marker = root / "keep.txt"
    marker.write_bytes(b"keep")
    WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()
    assert marker.read_bytes() == b"keep"


def test_corrupt_existing_config_is_not_overwritten_or_repaired(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    config = root / "workspace.json"
    original = b'{"schema_version": 999}'
    config.write_bytes(original)
    with pytest.raises(WorkspaceConfigError):
        WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()
    assert config.read_bytes() == original
    assert not (root / "models").exists()


def test_root_file_fails(tmp_path):
    root = tmp_path / "not-directory"
    root.write_text("x", encoding="utf-8")
    with pytest.raises(WorkspaceLayoutError):
        WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()


def test_low_space_rejects_before_creating_missing_root(tmp_path):
    root = tmp_path / "new-root"
    service = WorkspaceService(WorkspacePaths(root), minimum_free_bytes=100, disk_usage=lambda _: (0, 0, 99))
    with pytest.raises(WorkspaceInsufficientSpaceError):
        service.initialize()
    assert not root.exists()


def test_external_managed_symlink_never_receives_directories(tmp_path):
    root, outside = tmp_path / "ws", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "models").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")
    with pytest.raises(WorkspaceLayoutError):
        WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()
    assert not (outside / "library").exists()


def test_diagnose_is_read_only_and_reports_missing_config_layout_and_space(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    paths = WorkspacePaths(root)
    service = WorkspaceService(paths, minimum_free_bytes=100, disk_usage=lambda _: (0, 0, 99))
    before = list(tmp_path.rglob("*"))
    diagnostic = service.diagnose()
    assert not diagnostic.ok
    assert "workspace_missing" in {issue.code for issue in diagnostic.issues}
    assert list(tmp_path.rglob("*")) == before

    root.mkdir()
    diagnostic = service.diagnose()
    codes = [issue.code for issue in diagnostic.issues]
    assert codes == ["workspace_config_missing", "workspace_layout_missing", "workspace_space_low"]


def test_diagnose_dict_is_json_safe_and_has_no_root(tmp_path):
    paths = WorkspacePaths(tmp_path / "ws")
    diagnostic = WorkspaceService(paths, minimum_free_bytes=0).diagnose()
    encoded = json.dumps(diagnostic.to_dict(), ensure_ascii=False)
    assert str(paths.root) not in encoded


def test_load_config_and_service_construction_have_no_side_effect(tmp_path):
    paths = WorkspacePaths(tmp_path / "ws")
    service = WorkspaceService(paths, minimum_free_bytes=0)
    assert not paths.root.exists()
    with pytest.raises(WorkspaceConfigError):
        service.load_config()
    assert not paths.root.exists()


def test_invalid_minimum_and_disk_usage_are_programming_errors(tmp_path):
    with pytest.raises(ValueError):
        WorkspaceService(WorkspacePaths(tmp_path / "ws"), minimum_free_bytes=-1)
    service = WorkspaceService(WorkspacePaths(tmp_path / "ws"), minimum_free_bytes=0, disk_usage=lambda _: object())
    with pytest.raises(WorkspaceInitializationError):
        service.initialize()
