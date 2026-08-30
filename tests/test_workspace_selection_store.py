import json
import os
from pathlib import Path

import pytest

from cs2pov.application.workspace import WorkspaceSelection
from cs2pov.storage.workspace_selection_store import (
    JsonWorkspaceSelectionStore,
    WorkspaceSelectionStoreError,
    default_state_file,
)


def selection(path):
    return WorkspaceSelection(1, str(path))


def test_selection_schema_roundtrip_and_normalized_absolute_path(tmp_path):
    value = WorkspaceSelection(1, str(tmp_path / "中文 工作区" / ".." / "ws"))
    assert value.selected_workspace == str((tmp_path / "ws").resolve())
    assert list(value.to_dict()) == ["schema_version", "selected_workspace"]
    assert WorkspaceSelection.from_dict(value.to_dict()) == value


def test_selection_rejects_unknown_keys_bool_version_and_bad_paths(tmp_path):
    base = {"schema_version": 1, "selected_workspace": str(tmp_path)}
    for value in [{**base, "extra": 1}, {**base, "schema_version": True},
                  {**base, "selected_workspace": ""},
                  {**base, "selected_workspace": "relative"}]:
        with pytest.raises(Exception):
            WorkspaceSelection.from_dict(value)


def test_load_missing_is_read_only_and_save_is_atomic(tmp_path):
    state = tmp_path / "state" / "state.json"
    store = JsonWorkspaceSelectionStore(state)
    assert store.load() is None
    assert not state.parent.exists()
    store.save(selection(tmp_path / "workspace"))
    assert json.loads(state.read_text(encoding="utf-8"))["schema_version"] == 1
    assert not list(state.parent.glob(".state-*"))


def test_invalid_json_directory_and_symlink_are_rejected(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("{", encoding="utf-8")
    store = JsonWorkspaceSelectionStore(state)
    with pytest.raises(Exception):
        store.load()
    state.unlink()
    state.mkdir()
    with pytest.raises(Exception):
        JsonWorkspaceSelectionStore(state).load()


def test_invalid_utf8_is_selection_state_invalid(tmp_path):
    state = tmp_path / "state.json"
    state.write_bytes(b"\xff\xfe")
    with pytest.raises(Exception) as caught:
        JsonWorkspaceSelectionStore(state).load()
    assert caught.value.code == "selection_state_invalid"


def test_forget_only_removes_state_and_is_idempotent(tmp_path):
    state = tmp_path / "state" / "state.json"
    other = state.parent / "other.txt"
    other.parent.mkdir()
    other.write_text("keep", encoding="utf-8")
    store = JsonWorkspaceSelectionStore(state)
    assert store.forget() is False
    store.save(selection(tmp_path / "workspace"))
    assert store.forget() is True
    assert store.forget() is False
    assert other.read_text(encoding="utf-8") == "keep"
    assert state.parent.exists()


def test_default_state_file_requires_explicit_absolute_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CS2POV_STATE_FILE", str(tmp_path / "state.json"))
    assert default_state_file().is_absolute()
    monkeypatch.setenv("CS2POV_STATE_FILE", "relative.json")
    with pytest.raises(Exception):
        default_state_file()
    monkeypatch.delenv("CS2POV_STATE_FILE")
    with pytest.raises(Exception) as caught:
        default_state_file(environ={}, home="relative-home", platform="linux")
    assert caught.value.code == "selection_state_location_unavailable"


def test_selection_rejects_path_object_directly(tmp_path):
    with pytest.raises(Exception):
        WorkspaceSelection(1, tmp_path)


def test_load_symlink_rejected_without_touching_target(tmp_path):
    state, target = tmp_path / "state.json", tmp_path / "target.json"
    target.write_bytes(b"original")
    try:
        state.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")
    with pytest.raises(WorkspaceSelectionStoreError) as caught:
        JsonWorkspaceSelectionStore(state).load()
    assert caught.value.code == "selection_state_invalid"
    assert target.read_bytes() == b"original"


@pytest.mark.parametrize("payload", [
    {"schema_version": 1, "selected_workspace": "x", "extra": 1},
    {"schema_version": True, "selected_workspace": "C:/x"},
    {"schema_version": 1, "selected_workspace": []},
    {"schema_version": 1, "selected_workspace": "relative"},
])
def test_load_invalid_schema_is_typed_error(tmp_path, payload):
    state = tmp_path / "state.json"
    state.write_text(json.dumps(payload, default=str), encoding="utf-8")
    with pytest.raises(WorkspaceSelectionStoreError) as caught:
        JsonWorkspaceSelectionStore(state).load()
    assert caught.value.code == "selection_state_invalid"


def test_load_oserror_is_read_failed(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("denied")))
    with pytest.raises(WorkspaceSelectionStoreError) as caught:
        JsonWorkspaceSelectionStore(state).load()
    assert caught.value.code == "selection_state_read_failed"


def test_save_fsync_and_replace_fail_preserve_old_state_and_cleanup(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    store = JsonWorkspaceSelectionStore(state)
    store.save(selection(tmp_path / "old"))
    original = state.read_bytes()
    monkeypatch.setattr("cs2pov.storage.workspace_selection_store.os.fsync", lambda _: (_ for _ in ()).throw(OSError("fsync")))
    with pytest.raises(WorkspaceSelectionStoreError) as caught:
        store.save(selection(tmp_path / "new"))
    assert caught.value.code == "selection_state_write_failed"
    assert state.read_bytes() == original
    assert not list(state.parent.glob(".state-*"))
    monkeypatch.undo()
    monkeypatch.setattr("cs2pov.storage.workspace_selection_store.os.replace", lambda *_: (_ for _ in ()).throw(OSError("replace")))
    with pytest.raises(WorkspaceSelectionStoreError) as caught:
        store.save(selection(tmp_path / "new"))
    assert caught.value.code == "selection_state_write_failed"
    assert state.read_bytes() == original
    assert not list(state.parent.glob(".state-*"))


def test_forget_symlink_only_removes_link(tmp_path):
    state, target = tmp_path / "state.json", tmp_path / "target.json"
    target.write_bytes(b"target")
    try:
        state.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")
    assert JsonWorkspaceSelectionStore(state).forget() is True
    assert target.read_bytes() == b"target"


def test_forget_unlink_failure_preserves_state(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text("x", encoding="utf-8")
    original = state.read_bytes()
    monkeypatch.setattr(Path, "unlink", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no")))
    with pytest.raises(WorkspaceSelectionStoreError) as caught:
        JsonWorkspaceSelectionStore(state).forget()
    assert caught.value.code == "selection_state_forget_failed"
    assert state.exists()
    assert state.read_bytes() == original


def test_default_state_file_all_platform_branches_are_absolute_and_isolated(tmp_path):
    explicit = tmp_path / "explicit" / "state.json"
    assert default_state_file(environ={"CS2POV_STATE_FILE": str(explicit)}, platform="linux") == explicit
    local = tmp_path / "local"
    assert default_state_file(environ={"LOCALAPPDATA": str(local)}, platform="win32") == local / "CS2POV" / "state.json"
    xdg = tmp_path / "xdg"
    assert default_state_file(environ={"XDG_STATE_HOME": str(xdg)}, platform="linux") == xdg / "cs2pov" / "state.json"
    home = tmp_path / "home"
    assert default_state_file(environ={}, home=home, platform="linux") == home / ".local" / "state" / "cs2pov" / "state.json"
    for environ, platform, supplied_home in [
        ({"CS2POV_STATE_FILE": ""}, "linux", home), ({"CS2POV_STATE_FILE": "relative"}, "linux", home),
        ({"LOCALAPPDATA": "relative"}, "win32", home), ({"LOCALAPPDATA": ""}, "win32", home),
        ({"XDG_STATE_HOME": "relative"}, "linux", home), ({}, "linux", "relative")]:
        with pytest.raises(WorkspaceSelectionStoreError) as caught:
            default_state_file(environ=environ, home=supplied_home, platform=platform)
        assert caught.value.code == "selection_state_location_unavailable"


def test_save_replaces_state_symlink_without_writing_target(tmp_path):
    state = tmp_path / "state" / "state.json"
    target = tmp_path / "target.json"
    state.parent.mkdir()
    target.write_text("old", encoding="utf-8")
    try:
        state.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symbolic links unavailable")
    JsonWorkspaceSelectionStore(state).save(selection(tmp_path / "workspace"))
    assert not state.is_symlink()
    assert target.read_text(encoding="utf-8") == "old"
