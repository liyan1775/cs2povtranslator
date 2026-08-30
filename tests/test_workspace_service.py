import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from cs2pov.workspace.errors import (
    WorkspaceConfigError,
    WorkspaceInitializationError,
    WorkspaceInsufficientSpaceError,
    WorkspaceLayoutError,
    WorkspaceNotWritableError,
)
from cs2pov.workspace.models import WorkspaceConfig
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService


class _FailingProbe:
    def __init__(self, wrapped):
        self._wrapped = wrapped

    def write(self, _value):
        raise OSError("probe write failed")

    def close(self):
        return self._wrapped.close()

    @property
    def name(self):
        return self._wrapped.name


def test_config_round_trip_and_fixed_schema():
    value = WorkspaceConfig(1, 1, "12345678-1234-5678-1234-567812345678", "2026-08-30T12:34:56.123456Z")
    assert list(value.to_dict()) == ["schema_version", "layout_version", "workspace_id", "created_at"]
    assert WorkspaceConfig.from_dict(value.to_dict()) == value
    shuffled = {"created_at": value.created_at, "workspace_id": value.workspace_id,
                "layout_version": value.layout_version, "schema_version": value.schema_version}
    assert WorkspaceConfig.from_dict(shuffled) == value
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
    assert list(outside.iterdir()) == []
    assert not (root / "workspace.json").exists()
    assert not (root / "library").exists()


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


def test_schema_versions_are_exact_int_not_bool_and_direct_config_is_validated():
    base = {"schema_version": 1, "layout_version": 1,
            "workspace_id": "12345678-1234-5678-1234-567812345678",
            "created_at": "2026-08-30T12:34:56.123456Z"}
    for key in ("schema_version", "layout_version"):
        with pytest.raises(WorkspaceConfigError):
            WorkspaceConfig.from_dict({**base, key: True})
        with pytest.raises(WorkspaceConfigError):
            WorkspaceConfig(1 if key == "schema_version" else True,
                            1 if key == "layout_version" else True,
                            base["workspace_id"], base["created_at"])


def test_invalid_id_clock_and_usage_never_write_config(tmp_path):
    paths = WorkspacePaths(tmp_path / "ws")
    with pytest.raises(WorkspaceConfigError):
        WorkspaceService(paths, minimum_free_bytes=0, id_factory=lambda: "bad").initialize()
    assert not paths.config_file.exists()
    with pytest.raises(WorkspaceConfigError):
        WorkspaceService(paths, minimum_free_bytes=0, clock=lambda: datetime(2026, 1, 1)).initialize()
    assert not paths.config_file.exists()


def test_missing_root_diagnose_validates_space_and_orders_low_space(tmp_path):
    paths = WorkspacePaths(tmp_path / "missing")
    low = WorkspaceService(paths, minimum_free_bytes=100, disk_usage=lambda _: (0, 0, 99)).diagnose()
    assert [issue.code for issue in low.issues] == ["workspace_missing", "workspace_space_low"]
    invalid = WorkspaceService(paths, minimum_free_bytes=0, disk_usage=lambda _: object()).diagnose()
    assert [issue.code for issue in invalid.issues] == ["workspace_missing", "workspace_inspection_failed"]


def test_probe_write_failure_leaves_no_probe_files(tmp_path, monkeypatch):
    paths = WorkspacePaths(tmp_path / "ws")
    real_open = tempfile.NamedTemporaryFile
    calls = {"probe": 0}
    def failing_probe(*args, **kwargs):
        if kwargs.get("prefix") == ".workspace-probe-":
            calls["probe"] += 1
            return _FailingProbe(real_open(*args, **kwargs))
        return real_open(*args, **kwargs)
    monkeypatch.setattr("cs2pov.workspace.service.tempfile.NamedTemporaryFile", failing_probe)
    with pytest.raises(WorkspaceNotWritableError):
        WorkspaceService(paths, minimum_free_bytes=0).initialize()
    assert calls["probe"] == 1
    assert not list(paths.root.glob(".workspace-probe-*"))


def test_replace_failure_cleans_config_temporary_file(tmp_path, monkeypatch):
    paths = WorkspacePaths(tmp_path / "ws")
    monkeypatch.setattr("cs2pov.workspace.service.os.replace", lambda *_: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(WorkspaceInitializationError):
        WorkspaceService(paths, minimum_free_bytes=0).initialize()
    assert not list(paths.root.glob(".workspace-config-*"))


def test_initialize_mkdir_permission_error_is_stable(tmp_path, monkeypatch):
    paths = WorkspacePaths(tmp_path / "ws")
    real_mkdir = Path.mkdir
    def deny_models(self, *args, **kwargs):
        if self == paths.models_dir:
            raise PermissionError("denied")
        return real_mkdir(self, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", deny_models)
    with pytest.raises(WorkspaceLayoutError):
        WorkspaceService(paths, minimum_free_bytes=0).initialize()


def test_diagnose_reports_corrupt_config_missing_layout_readonly_and_low_space_in_order(tmp_path, monkeypatch):
    paths = WorkspacePaths(tmp_path / "ws")
    WorkspaceService(paths, minimum_free_bytes=0).initialize()
    paths.config_file.write_text("{}", encoding="utf-8")
    paths.audio_cache_dir.rmdir()
    monkeypatch.setattr("cs2pov.workspace.service.os.access", lambda *_: False)
    diagnostic = WorkspaceService(paths, minimum_free_bytes=100, disk_usage=lambda _: (0, 0, 99)).diagnose()
    assert [issue.code for issue in diagnostic.issues] == [
        "workspace_config_invalid", "workspace_layout_missing", "workspace_not_writable", "workspace_space_low"
    ]


def test_diagnose_missing_root_invalid_free_is_none_and_json_safe(tmp_path):
    paths = WorkspacePaths(tmp_path / "missing")
    diagnostic = WorkspaceService(paths, minimum_free_bytes=0,
                                   disk_usage=lambda _: (0, 0, object())).diagnose()
    assert [issue.code for issue in diagnostic.issues] == ["workspace_missing", "workspace_inspection_failed"]
    assert diagnostic.free_bytes is None
    json.dumps(diagnostic.to_dict())


def test_diagnose_existing_root_invalid_free_is_none_and_json_safe(tmp_path):
    paths = WorkspacePaths(tmp_path / "ws")
    paths.root.mkdir()
    diagnostic = WorkspaceService(paths, minimum_free_bytes=0,
                                   disk_usage=lambda _: (0, 0, object())).diagnose()
    assert "workspace_inspection_failed" in [issue.code for issue in diagnostic.issues]
    assert diagnostic.free_bytes is None
    json.dumps(diagnostic.to_dict())


def test_boolean_capacity_values_are_rejected(tmp_path):
    paths = WorkspacePaths(tmp_path / "ws")
    for value in (False, True):
        with pytest.raises(ValueError):
            WorkspaceService(paths, minimum_free_bytes=value)

        service = WorkspaceService(paths, minimum_free_bytes=0,
                                   disk_usage=lambda _, free=value: (0, 0, free))
        with pytest.raises(WorkspaceInitializationError):
            service.initialize()
        diagnostic = service.diagnose()
        assert "workspace_inspection_failed" in [issue.code for issue in diagnostic.issues]
        assert diagnostic.free_bytes is None


def test_broken_config_symlink_is_invalid_not_missing(tmp_path):
    paths = WorkspacePaths(tmp_path / "ws")
    paths.root.mkdir()
    try:
        paths.config_file.symlink_to(paths.root / "missing-config-target.json")
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")

    diagnostic = WorkspaceService(paths, minimum_free_bytes=0).diagnose()

    codes = [issue.code for issue in diagnostic.issues]
    assert "workspace_config_invalid" in codes
    assert "workspace_config_missing" not in codes
