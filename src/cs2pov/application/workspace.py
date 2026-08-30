from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from cs2pov.workspace.errors import (WorkspaceConfigError, WorkspaceError,
                                     WorkspaceInitializationError,
                                     WorkspaceInsufficientSpaceError,
                                     WorkspaceLayoutError,
                                     WorkspaceNotWritableError,
                                     WorkspaceRootRequiredError)
from cs2pov.workspace.models import WorkspaceDiagnostic
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService

SELECTION_SCHEMA_VERSION = 1


class WorkspaceUseCaseError(WorkspaceError):
    def __init__(self, code, message_zh, suggestion_zh, diagnostic=None):
        self.code, self.message_zh, self.suggestion_zh, self.diagnostic = code, message_zh, suggestion_zh, diagnostic
        super().__init__(message_zh)


@dataclass(frozen=True, slots=True)
class WorkspaceSelection:
    schema_version: int
    selected_workspace: str

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != SELECTION_SCHEMA_VERSION:
            raise ValueError("工作区选择状态版本无效。")
        self_path = WorkspacePaths(self.selected_workspace)
        object.__setattr__(self, "selected_workspace", str(self_path.root))

    def to_dict(self):
        return {"schema_version": self.schema_version, "selected_workspace": self.selected_workspace}

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != {"schema_version", "selected_workspace"}:
            raise ValueError("工作区选择状态字段无效。")
        return cls(value["schema_version"], value["selected_workspace"])


class WorkspaceSelectionPort(Protocol):
    def load(self) -> WorkspaceSelection | None: ...
    def save(self, selection: WorkspaceSelection) -> None: ...
    def forget(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    selected_workspace: str
    diagnostic: WorkspaceDiagnostic

    def to_dict(self):
        return {"selected_workspace": self.selected_workspace, "diagnostic": self.diagnostic.to_dict()}


@dataclass(frozen=True, slots=True)
class ForgetWorkspaceResult:
    forgotten: bool

    def to_dict(self):
        return {"forgotten": self.forgotten}


class WorkspaceApplicationService:
    def __init__(self, selection_port: WorkspaceSelectionPort,
                 *, workspace_service_factory: Callable[[WorkspacePaths], WorkspaceService] = WorkspaceService):
        self.selection_port, self.workspace_service_factory = selection_port, workspace_service_factory

    def _paths(self, root):
        try:
            return WorkspacePaths(root)
        except WorkspaceError as exc:
            raise WorkspaceUseCaseError("workspace_root_invalid", str(exc), "请选择一个绝对工作区目录。") from exc

    def _error(self, exc, diagnostic=None):
        if diagnostic and diagnostic.issues:
            issue = diagnostic.issues[0]
            return WorkspaceUseCaseError(issue.code, issue.message_zh, issue.suggestion_zh, diagnostic)
        if getattr(exc, "code", None):
            return WorkspaceUseCaseError(exc.code, getattr(exc, "message_zh", str(exc)),
                                         getattr(exc, "suggestion_zh", "请检查状态后重试。"), diagnostic)
        mapping = {WorkspaceRootRequiredError: "workspace_root_invalid", WorkspaceInsufficientSpaceError: "workspace_space_low",
                   WorkspaceNotWritableError: "workspace_not_writable", WorkspaceConfigError: "workspace_config_invalid",
                   WorkspaceLayoutError: "workspace_layout_invalid"}
        code = next((v for k, v in mapping.items() if isinstance(exc, k)), "workspace_initialization_failed")
        return WorkspaceUseCaseError(code, str(exc), "请检查工作区状态并重试。", diagnostic)

    def initialize_and_select(self, root):
        paths = self._paths(root)
        service = self.workspace_service_factory(paths)
        try:
            service.initialize()
            diagnostic = service.diagnose()
        except WorkspaceError as exc:
            raise self._error(exc) from exc
        if not diagnostic.ok:
            raise self._error(WorkspaceError(), diagnostic)
        selection = WorkspaceSelection(SELECTION_SCHEMA_VERSION, str(paths.root))
        try:
            self.selection_port.save(selection)
        except Exception as exc:
            raise WorkspaceUseCaseError("selection_state_write_failed", "无法保存当前工作区选择。", "请重试 use 操作。", diagnostic) from exc
        return WorkspaceView(selection.selected_workspace, diagnostic)

    def select_existing(self, root):
        paths = self._paths(root)
        service = self.workspace_service_factory(paths)
        try:
            service.load_config()
            diagnostic = service.diagnose()
        except WorkspaceError as exc:
            raise self._error(exc) from exc
        if not diagnostic.ok:
            raise self._error(WorkspaceError(), diagnostic)
        selection = WorkspaceSelection(SELECTION_SCHEMA_VERSION, str(paths.root))
        try:
            self.selection_port.save(selection)
        except Exception as exc:
            raise WorkspaceUseCaseError("selection_state_write_failed", "无法保存当前工作区选择。", "请重试 use 操作。", diagnostic) from exc
        return WorkspaceView(selection.selected_workspace, diagnostic)

    def show_current(self):
        try:
            selection = self.selection_port.load()
        except Exception as exc:
            raise self._error(exc) from exc
        if selection is None:
            raise WorkspaceUseCaseError("selection_missing", "尚未选择工作区。", "请先初始化或使用一个工作区。")
        return self.diagnose(selection.selected_workspace)

    def diagnose(self, root=None):
        if root is None:
            try:
                selection = self.selection_port.load()
            except Exception as exc:
                raise self._error(exc) from exc
            if selection is None:
                raise WorkspaceUseCaseError("selection_missing", "尚未选择工作区。", "请先选择工作区。")
            root = selection.selected_workspace
        paths = self._paths(root)
        service = self.workspace_service_factory(paths)
        diagnostic = service.diagnose()
        if not diagnostic.ok:
            raise self._error(WorkspaceError(), diagnostic)
        return WorkspaceView(str(paths.root), diagnostic)

    def forget_current(self):
        try:
            return ForgetWorkspaceResult(self.selection_port.forget())
        except Exception as exc:
            raise WorkspaceUseCaseError("selection_state_forget_failed", "无法忘记当前工作区选择。", "请重试 forget 操作。") from exc
