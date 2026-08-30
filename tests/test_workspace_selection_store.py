import json
import os
from pathlib import Path

import pytest

from cs2pov.application.workspace import WorkspaceSelection
from cs2pov.storage.workspace_selection_store import (
    JsonWorkspaceSelectionStore,
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
