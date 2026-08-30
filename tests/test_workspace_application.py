import json
from pathlib import Path

import pytest

from cs2pov.application.workspace import (
    ForgetWorkspaceResult,
    WorkspaceApplicationService,
    WorkspaceSelection,
    WorkspaceUseCaseError,
)
from cs2pov.workspace.models import WorkspaceDiagnostic


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
    json.dumps(view.to_dict())


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
    assert port.forgotten == 1


def test_application_preserves_selection_store_error_code(tmp_path):
    class FailingPort(FakePort):
        def load(self):
            error = RuntimeError("x")
            error.code = "selection_state_read_failed"
            error.message_zh = "读取失败"
            error.suggestion_zh = "请重试"
            raise error
    service = WorkspaceApplicationService(FailingPort(), workspace_service_factory=factory(FakeWorkspace(tmp_path)))
    with pytest.raises(WorkspaceUseCaseError) as caught:
        service.show_current()
    assert caught.value.code == "selection_state_read_failed"
