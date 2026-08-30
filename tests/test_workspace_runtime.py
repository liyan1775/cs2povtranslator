import os
from pathlib import Path

import pytest

from cs2pov.application.workspace import WorkspaceSelection
from cs2pov.application.workspace import WorkspaceSelectionPortError
from cs2pov.workspace.errors import WorkspaceConfigError
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


def test_environment_overrides_cover_all_managed_keys_and_are_copies(tmp_path):
    root = prepare_workspace(tmp_path)
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    runtime = WorkspaceRuntimeResolver(store).resolve_selected()
    expected = {
        "HF_HOME": str(runtime.paths.huggingface_cache_dir),
        "HF_HUB_CACHE": str(runtime.paths.huggingface_hub_cache_dir),
        "HUGGINGFACE_HUB_CACHE": str(runtime.paths.huggingface_hub_cache_dir),
        "TMP": str(runtime.paths.temp_dir), "TEMP": str(runtime.paths.temp_dir),
        "TMPDIR": str(runtime.paths.temp_dir),
    }
    assert runtime.environment_overrides() == expected
    changed = runtime.environment_overrides(); changed["HF_HOME"] = "changed"
    assert runtime.environment_overrides() == expected
    parent = os.environ.copy(); os.environ["RUNTIME_TEST_PARENT"] = "keep"
    try:
        child = runtime.subprocess_environment(None)
        assert child["RUNTIME_TEST_PARENT"] == "keep"
        assert {key: child[key] for key in expected} == expected
        assert os.environ["RUNTIME_TEST_PARENT"] == "keep"
    finally:
        os.environ.clear(); os.environ.update(parent)


def test_resolver_does_not_mask_unexpected_runtime_error(tmp_path):
    class BadService:
        def diagnose(self):
            raise RuntimeError("programming bug")
    root = prepare_workspace(tmp_path)
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    with pytest.raises(RuntimeError, match="programming bug"):
        WorkspaceRuntimeResolver(store, workspace_service_factory=lambda _: BadService()).resolve_selected()


def test_resolver_does_not_mask_port_runtime_error(tmp_path):
    class BadPort:
        def load(self):
            raise RuntimeError("port bug")
    with pytest.raises(RuntimeError, match="port bug"):
        WorkspaceRuntimeResolver(BadPort()).resolve_selected()


def test_resolver_does_not_mask_load_runtime_error(tmp_path):
    root = prepare_workspace(tmp_path)
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    class BadService:
        def diagnose(self):
            return WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).diagnose()
        def load_config(self):
            raise RuntimeError("load bug")
    with pytest.raises(RuntimeError, match="load bug"):
        WorkspaceRuntimeResolver(store, workspace_service_factory=lambda _: BadService()).resolve_selected()


def test_selection_store_error_preserves_structured_contract(tmp_path):
    class BadStore:
        def load(self):
            raise WorkspaceSelectionPortError("selection_state_read_failed", "读取失败", "请重试")
    with pytest.raises(WorkspaceRuntimeError) as caught:
        WorkspaceRuntimeResolver(BadStore()).resolve_selected()
    assert (caught.value.code, caught.value.message_zh, caught.value.suggestion_zh) == ("selection_state_read_failed", "读取失败", "请重试")


@pytest.mark.parametrize("config_mode", ["missing", "corrupt"])
def test_real_config_failures_are_unhealthy_with_diagnostic(tmp_path, config_mode):
    root = prepare_workspace(tmp_path)
    config = root / "workspace.json"
    if config_mode == "missing":
        config.unlink()
    else:
        config.write_text("{}", encoding="utf-8")
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    with pytest.raises(WorkspaceRuntimeError) as caught:
        WorkspaceRuntimeResolver(store).resolve_selected()
    assert caught.value.code == "workspace_unhealthy"
    assert caught.value.diagnostic is not None
    assert caught.value.diagnostic.ok is False
    assert caught.value.diagnostic.initialized is False
    assert caught.value.diagnostic.issues[0].code == ("workspace_config_missing" if config_mode == "missing" else "workspace_config_invalid")


@pytest.mark.parametrize("failure", ["layout", "writable", "space"])
def test_resolve_for_write_rejects_unhealthy_without_repair_or_selection_change(tmp_path, monkeypatch, failure):
    root = prepare_workspace(tmp_path)
    paths = WorkspacePaths(root)
    original = WorkspaceSelection(1, str(root))
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(original)
    if failure == "layout":
        paths.models_dir.rmdir()
    elif failure == "writable":
        monkeypatch.setattr(os, "access", lambda *_: False)
    factory = (lambda p: WorkspaceService(p, minimum_free_bytes=100, disk_usage=lambda _: (0, 0, 1))) if failure == "space" else WorkspaceService
    with pytest.raises(WorkspaceRuntimeError) as caught:
        WorkspaceRuntimeResolver(store, workspace_service_factory=factory).resolve_for_write()
    assert caught.value.code == "workspace_unhealthy"
    assert store.load() == original
    assert not (root / "new-output").exists()
    if failure == "layout":
        assert not paths.models_dir.exists()


def test_read_resolution_allows_low_space_and_unwritable_health(tmp_path, monkeypatch):
    root = prepare_workspace(tmp_path)
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    low = WorkspaceRuntimeResolver(store, workspace_service_factory=lambda p: WorkspaceService(p, minimum_free_bytes=100, disk_usage=lambda _: (0, 0, 1))).resolve_selected()
    assert low.root == root.resolve()
    monkeypatch.setattr(os, "access", lambda *_: False)
    writable = WorkspaceRuntimeResolver(store).resolve_selected()
    assert writable.workspace_id == low.workspace_id


def test_runtime_metadata_and_all_paths_are_exact_snapshot(tmp_path):
    root = prepare_workspace(tmp_path)
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    runtime = WorkspaceRuntimeResolver(store).resolve_selected()
    config = WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).load_config()
    assert (runtime.workspace_id, runtime.workspace_schema_version, runtime.workspace_layout_version, runtime.path_policy_version) == (config.workspace_id, 1, 1, 1)
    assert all(path.is_relative_to(runtime.root) for path in runtime.paths.all_directories())


def test_config_disappearing_after_diagnosis_maps_to_unhealthy(tmp_path):
    root = prepare_workspace(tmp_path)
    store = JsonWorkspaceSelectionStore(tmp_path / "state.json")
    store.save(WorkspaceSelection(1, str(root)))
    class RacyService:
        def __init__(self):
            self.inner = WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0)
            self.first = True
        def diagnose(self):
            diagnostic = self.inner.diagnose()
            if self.first:
                self.first = False
                (root / "workspace.json").unlink()
            return diagnostic
        def load_config(self):
            return self.inner.load_config()
    service = RacyService()
    with pytest.raises(WorkspaceRuntimeError) as caught:
        WorkspaceRuntimeResolver(store, workspace_service_factory=lambda _: service).resolve_selected()
    assert caught.value.code == "workspace_unhealthy"
    assert caught.value.diagnostic is not None
    assert caught.value.diagnostic.ok is False
    assert caught.value.diagnostic.initialized is False
    assert caught.value.diagnostic.issues[0].code == "workspace_config_missing"
