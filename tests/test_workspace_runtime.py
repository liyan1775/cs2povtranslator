import os
from pathlib import Path

import pytest

from cs2pov.application.workspace import WorkspaceSelection
from cs2pov.application.workspace_runtime import WorkspaceRuntimeError, WorkspaceRuntimeResolver
from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService


def prepare_workspace(tmp_path):
    root = tmp_path / "中文 工作区"
    WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()
    return root


def test_resolve_selected_requires_selection(tmp_path):
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    with pytest.raises(WorkspaceRuntimeError) as caught:
        WorkspaceRuntimeResolver(store).resolve_selected()
    assert caught.value.code == "workspace_selection_required"


def test_selected_missing_workspace_is_unhealthy_with_diagnostic(tmp_path):
    root = tmp_path / "gone"
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    with pytest.raises(WorkspaceRuntimeError) as caught:
        WorkspaceRuntimeResolver(store).resolve_selected()
    assert caught.value.code == "workspace_unhealthy"
    assert caught.value.diagnostic.issues[0].code == "workspace_missing"


def test_healthy_runtime_is_immutable_and_uses_one_root(tmp_path):
    root = prepare_workspace(tmp_path)
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    runtime = WorkspaceRuntimeResolver(store).resolve_for_write()
    assert runtime.root == root.resolve()
    assert runtime.workspace_id
    assert (runtime.paths.whisper_cache_dir).is_relative_to(runtime.root)
    assert runtime.paths.jobs_dir.is_relative_to(runtime.root)
    with pytest.raises((AttributeError, TypeError)):
        runtime.root = Path("other")


def test_runtime_snapshot_survives_selection_switch_and_environment_isolated(tmp_path):
    first, second = prepare_workspace(tmp_path / "first"), prepare_workspace(tmp_path / "second")
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(first)))
    runtime = WorkspaceRuntimeResolver(store).resolve_selected()
    store.save(WorkspaceSelection(1, str(second)))
    assert runtime.root == first.resolve()
    overrides = runtime.environment_overrides()
    overrides["TMP"] = "mutated"
    assert runtime.environment_overrides()["TMP"] != "mutated"
    before = os.environ.copy()
    child = runtime.subprocess_environment({"UNRELATED": "keep", "TMP": "old"})
    assert child["UNRELATED"] == "keep"
    assert child["TMP"] == str(runtime.paths.temp_dir)
    assert os.environ.copy() == before


def test_resolver_does_not_mask_unexpected_runtime_error(tmp_path):
    class BadService:
        def diagnose(self):
            raise RuntimeError("programming bug")
    root = prepare_workspace(tmp_path)
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    with pytest.raises(RuntimeError, match="programming bug"):
        WorkspaceRuntimeResolver(store, workspace_service_factory=lambda _: BadService()).resolve_selected()
