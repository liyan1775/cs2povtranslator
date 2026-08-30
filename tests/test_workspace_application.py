import json
from pathlib import Path

import pytest

from cs2pov.application.workspace import (
    ForgetWorkspaceResult,
    WorkspaceApplicationService,
    WorkspaceSelection,
    WorkspaceSelectionPortError,
    WorkspaceUseCaseError,
)
from cs2pov.workspace.models import WorkspaceDiagnostic
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService
from cs2pov.workspace.errors import (WorkspaceConfigError, WorkspaceInitializationError,
                                     WorkspaceInsufficientSpaceError, WorkspaceLayoutError,
                                     WorkspaceNotWritableError)
from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore
from cs2pov.application.workspace import WorkspaceSelectionPortError


class FakePort:
    def __init__(self, value=None):
        self.value = value
        self.saved = []
        self.forgotten = 0

    def load(self):
        return self.value

    def save(self, selection):
        self.saved.append(selection)
        self.value = selection

    def forget(self):
        self.forgotten += 1
        had = self.value is not None
        self.value = None
        return had


class FakeWorkspace:
    def __init__(self, root, ok=True):
        self.root = Path(root)
        self.ok = ok
        self.initialized = 0

    def initialize(self):
        self.initialized += 1

    def load_config(self):
        return object()

    def diagnose(self):
        return WorkspaceDiagnostic(self.ok, self.ok, True, 10, 0, ())


def factory(fake):
    return lambda paths: fake


def test_initialize_then_diagnose_then_save(tmp_path):
    port = FakePort()
    fake = FakeWorkspace(tmp_path / "ws")
    service = WorkspaceApplicationService(port, workspace_service_factory=factory(fake))
    view = service.initialize_and_select(tmp_path / "ws")
    assert fake.initialized == 1
    assert port.saved[0].selected_workspace == str((tmp_path / "ws").resolve())
    assert view.to_dict() == {
        "selected_workspace": str((tmp_path / "ws").resolve()),
        "diagnostic": {"ok": True, "initialized": True, "writable": True,
                        "free_bytes": 10, "required_free_bytes": 0, "issues": []},
    }


def test_unhealthy_initialize_does_not_save_old_selection(tmp_path):
    old = WorkspaceSelection(1, str(tmp_path / "old"))
    port = FakePort(old)
    fake = FakeWorkspace(tmp_path / "ws", ok=False)
    service = WorkspaceApplicationService(port, workspace_service_factory=factory(fake))
    with pytest.raises(WorkspaceUseCaseError):
        service.initialize_and_select(tmp_path / "ws")
    assert port.value == old


def test_select_existing_never_initializes_or_creates_directory(tmp_path):
    root = tmp_path / "missing"
    port = FakePort()
    fake = FakeWorkspace(root)
    service = WorkspaceApplicationService(port, workspace_service_factory=factory(fake))
    service.select_existing(root)
    assert fake.initialized == 0
    assert not root.exists()


def test_show_without_selection_and_forget_are_stable(tmp_path):
    port = FakePort()
    service = WorkspaceApplicationService(port, workspace_service_factory=factory(FakeWorkspace(tmp_path)))
    with pytest.raises(WorkspaceUseCaseError) as error:
        service.show_current()
    assert error.value.code == "selection_missing"
    result = service.forget_current()
    assert result == ForgetWorkspaceResult(False)
    assert result.to_dict() == {"forgotten": False}
    assert port.forgotten == 1


def test_application_preserves_selection_store_error_code(tmp_path):
    class FailingPort(FakePort):
        def load(self):
            raise WorkspaceSelectionPortError("selection_state_read_failed", "读取失败", "请重试")
    service = WorkspaceApplicationService(FailingPort(), workspace_service_factory=factory(FakeWorkspace(tmp_path)))
    with pytest.raises(WorkspaceUseCaseError) as caught:
        service.show_current()
    assert caught.value.code == "selection_state_read_failed"


def test_show_and_diagnose_return_unhealthy_view_when_selected_workspace_missing(tmp_path):
    root = tmp_path / "gone"
    state = WorkspaceSelection(1, str(root))
    port = FakePort(state)
    service = WorkspaceApplicationService(port, workspace_service_factory=lambda paths: WorkspaceService(paths, minimum_free_bytes=0))
    view = service.show_current()
    assert view.selected_workspace == str(root.resolve())
    assert view.diagnostic.ok is False
    assert view.diagnostic.issues[0].code == "workspace_missing"
    assert port.value == state


def test_select_existing_real_service_never_repairs_missing_bad_or_incomplete_workspace(tmp_path):
    old = WorkspaceSelection(1, str(tmp_path / "old"))
    for kind in ("missing", "bad", "incomplete"):
        root = tmp_path / kind
        config_bytes = None
        if kind == "bad":
            root.mkdir()
            config_bytes = b"{}\n"
            (root / "workspace.json").write_bytes(config_bytes)
        elif kind == "incomplete":
            WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()
            config_bytes = (root / "workspace.json").read_bytes()
            (root / "models").rmdir()
        port = FakePort(old)
        app = WorkspaceApplicationService(port)
        with pytest.raises(WorkspaceUseCaseError):
            app.select_existing(root)
        assert port.value == old
        if kind == "missing":
            assert not root.exists()
        elif kind == "bad":
            assert (root / "workspace.json").read_bytes() == config_bytes
            assert not (root / "models").exists()
        else:
            assert (root / "workspace.json").read_bytes() == config_bytes
            assert not (root / "models").exists()


def test_initialize_save_failure_preserves_real_workspace_and_can_recover(tmp_path):
    root = tmp_path / "new"
    old = WorkspaceSelection(1, str(tmp_path / "old"))
    old_snapshot = old
    class FailingPort(FakePort):
        def save(self, selection):
            raise WorkspaceSelectionPortError("selection_state_write_failed", "写入失败", "重试")
    failing_port = FailingPort(old)
    app = WorkspaceApplicationService(failing_port)
    with pytest.raises(WorkspaceUseCaseError):
        app.initialize_and_select(root)
    assert (root / "workspace.json").exists()
    config_bytes = (root / "workspace.json").read_bytes()
    assert failing_port.value == old_snapshot
    assert all(path.is_dir() for path in WorkspacePaths(root).all_directories())
    store = JsonWorkspaceSelectionStore(tmp_path / "state" / "state.json")
    recovered = WorkspaceApplicationService(store).select_existing(root)
    assert recovered.selected_workspace == str(root.resolve())
    assert (root / "workspace.json").read_bytes() == config_bytes


def test_explicit_diagnose_does_not_change_selection_even_when_unhealthy(tmp_path):
    selected = tmp_path / "selected"
    target = tmp_path / "target"
    WorkspaceService(WorkspacePaths(selected), minimum_free_bytes=0).initialize()
    old = WorkspaceSelection(1, str(selected))
    port = FakePort(old)
    view = WorkspaceApplicationService(port).diagnose(target)
    assert view.diagnostic.ok is False
    assert port.value == old


def test_show_low_space_returns_unhealthy_view_and_keeps_selection(tmp_path):
    root = tmp_path / "selected"
    WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()
    old = WorkspaceSelection(1, str(root))
    port = FakePort(old)
    app = WorkspaceApplicationService(port, workspace_service_factory=lambda paths: WorkspaceService(paths, minimum_free_bytes=100, disk_usage=lambda _: (0, 0, 1)))
    view = app.show_current()
    assert view.diagnostic.ok is False
    assert view.diagnostic.issues[-1].code == "workspace_space_low"
    assert port.value == old


def test_forget_real_store_does_not_touch_workspace_or_marker(tmp_path):
    root = tmp_path / "workspace"
    WorkspaceService(WorkspacePaths(root), minimum_free_bytes=0).initialize()
    marker = root / "marker.txt"
    marker.write_bytes(b"keep")
    state = tmp_path / "state" / "state.json"
    store = JsonWorkspaceSelectionStore(state)
    store.save(WorkspaceSelection(1, str(root)))
    result = WorkspaceApplicationService(store).forget_current()
    assert result.to_dict() == {"forgotten": True}
    assert not state.exists()
    assert (root / "workspace.json").exists()
    assert marker.read_bytes() == b"keep"


@pytest.mark.parametrize("failure, expected", [
    (WorkspaceInsufficientSpaceError("low"), "workspace_space_low"),
    (WorkspaceNotWritableError("no"), "workspace_not_writable"),
    (WorkspaceConfigError("bad"), "workspace_config_invalid"),
    (WorkspaceLayoutError("layout"), "workspace_layout_invalid"),
    (WorkspaceInitializationError("other"), "workspace_initialization_failed"),
])
def test_workspace_errors_map_to_stable_application_codes(tmp_path, failure, expected):
    class FailingWorkspace(FakeWorkspace):
        def initialize(self):
            raise failure
    app = WorkspaceApplicationService(FakePort(), workspace_service_factory=lambda paths: FailingWorkspace(paths.root))
    with pytest.raises(WorkspaceUseCaseError) as caught:
        app.initialize_and_select(tmp_path / "root")
    assert caught.value.code == expected
    assert caught.value.message_zh == str(failure)
    assert caught.value.suggestion_zh
    assert caught.value.diagnostic is None


def test_unexpected_port_runtime_error_is_not_disguised(tmp_path):
    class BadPort(FakePort):
        def load(self):
            raise RuntimeError("programming bug")
    with pytest.raises(RuntimeError, match="programming bug"):
        WorkspaceApplicationService(BadPort()).show_current()


@pytest.mark.parametrize("root", ["", "relative-root"])
def test_invalid_root_maps_to_concrete_workspace_root_error(tmp_path, root):
    with pytest.raises(WorkspaceUseCaseError) as caught:
        WorkspaceApplicationService(FakePort()).initialize_and_select(root)
    assert caught.value.code == "workspace_root_invalid"
    assert caught.value.message_zh
    assert caught.value.suggestion_zh
