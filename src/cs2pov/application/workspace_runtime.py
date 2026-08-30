from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from cs2pov.application.workspace import WorkspaceSelectionPort, WorkspaceSelectionPortError
from cs2pov.workspace.errors import WorkspaceConfigError, WorkspaceError
from cs2pov.workspace.models import WorkspaceDiagnostic
from cs2pov.workspace.paths import WorkspacePaths
from cs2pov.workspace.service import WorkspaceService

WORKSPACE_PATH_POLICY_VERSION = 1


class WorkspaceRuntimeError(WorkspaceError):
    def __init__(self, code: str, message_zh: str, suggestion_zh: str, diagnostic: WorkspaceDiagnostic | None = None):
        self.code, self.message_zh, self.suggestion_zh, self.diagnostic = code, message_zh, suggestion_zh, diagnostic
        super().__init__(message_zh)


@dataclass(frozen=True, slots=True)
class WorkspaceRuntime:
    root: Path
    workspace_id: str
    workspace_schema_version: int
    workspace_layout_version: int
    path_policy_version: int = WORKSPACE_PATH_POLICY_VERSION

    @property
    def paths(self) -> WorkspacePaths:
        return WorkspacePaths(self.root)

    def environment_overrides(self) -> dict[str, str]:
        return self.paths.environment_overrides()

    def subprocess_environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        import os
        result = dict(os.environ if base is None else base)
        result.update(self.environment_overrides())
        return result


class WorkspaceRuntimeResolver:
    def __init__(self, selection_port: WorkspaceSelectionPort, *, workspace_service_factory: Callable = WorkspaceService):
        self.selection_port = selection_port
        self.workspace_service_factory = workspace_service_factory

    def _selection(self):
        try:
            selection = self.selection_port.load()
        except WorkspaceSelectionPortError as exc:
            raise WorkspaceRuntimeError(exc.code, exc.message_zh, exc.suggestion_zh) from exc
        if selection is None:
            raise WorkspaceRuntimeError("workspace_selection_required", "尚未选择工作区。", "请先初始化或选择一个工作区。")
        return selection

    def _resolve(self, require_write: bool) -> WorkspaceRuntime:
        selection = self._selection()
        paths = WorkspacePaths(selection.selected_workspace)
        service = self.workspace_service_factory(paths)
        diagnostic = service.diagnose()
        if require_write and not diagnostic.ok:
            issue = diagnostic.issues[0] if diagnostic.issues else None
            raise WorkspaceRuntimeError("workspace_unhealthy", issue.message_zh if issue else "工作区不健康。", issue.suggestion_zh if issue else "请修复工作区后重试。", diagnostic)
        if not diagnostic.initialized:
            issue = diagnostic.issues[0] if diagnostic.issues else None
            raise WorkspaceRuntimeError("workspace_unhealthy", issue.message_zh if issue else "工作区配置无效。", issue.suggestion_zh if issue else "请初始化工作区后重试。", diagnostic)
        try:
            config = service.load_config()
        except WorkspaceConfigError as exc:
            raise WorkspaceRuntimeError("workspace_unhealthy", str(exc), "请修复工作区配置后重试。", diagnostic) from exc
        return WorkspaceRuntime(paths.root, config.workspace_id, config.schema_version, config.layout_version)

    def resolve_selected(self) -> WorkspaceRuntime:
        return self._resolve(False)

    def resolve_for_write(self) -> WorkspaceRuntime:
        return self._resolve(True)
