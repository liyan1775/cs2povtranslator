from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from .errors import WorkspaceConfigError

WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_LAYOUT_VERSION = 1
_CONFIG_KEYS = {"schema_version", "layout_version", "workspace_id", "created_at"}


def _validate_config_values(schema_version, layout_version, workspace_id, created_at):
    if (type(schema_version) is not int or type(layout_version) is not int
            or schema_version != WORKSPACE_SCHEMA_VERSION or layout_version != WORKSPACE_LAYOUT_VERSION):
        raise WorkspaceConfigError("工作区配置版本不受支持，请使用匹配版本重新初始化工作区。")
    if not isinstance(workspace_id, str):
        raise WorkspaceConfigError("工作区 ID 无效，请重新初始化工作区。")
    try:
        parsed_id = UUID(workspace_id)
    except (ValueError, AttributeError) as exc:
        raise WorkspaceConfigError("工作区 ID 无效，请重新初始化工作区。") from exc
    if str(parsed_id) != workspace_id:
        raise WorkspaceConfigError("工作区 ID 必须是规范 UUID，请重新初始化工作区。")
    if not isinstance(created_at, str):
        raise WorkspaceConfigError("创建时间无效，请重新初始化工作区。")
    try:
        parsed_time = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkspaceConfigError("创建时间必须是 UTC ISO-8601，请重新初始化工作区。") from exc
    if (not created_at.endswith("Z") or parsed_time.tzinfo is None
            or parsed_time.utcoffset() != timezone.utc.utcoffset(parsed_time)
            or parsed_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != created_at):
        raise WorkspaceConfigError("创建时间格式不规范，请重新初始化工作区。")


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    schema_version: int
    layout_version: int
    workspace_id: str
    created_at: str

    def __post_init__(self):
        _validate_config_values(self.schema_version, self.layout_version, self.workspace_id, self.created_at)

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "layout_version": self.layout_version,
                "workspace_id": self.workspace_id, "created_at": self.created_at}

    @classmethod
    def from_dict(cls, value: object) -> "WorkspaceConfig":
        if not isinstance(value, dict) or set(value) != _CONFIG_KEYS:
            raise WorkspaceConfigError("工作区配置字段不正确，请删除无效字段后重新初始化。")
        return cls(value["schema_version"], value["layout_version"], value["workspace_id"], value["created_at"])


@dataclass(frozen=True, slots=True)
class WorkspaceIssue:
    code: str
    severity: str
    message_zh: str
    suggestion_zh: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message_zh": self.message_zh, "suggestion_zh": self.suggestion_zh}


@dataclass(frozen=True, slots=True)
class WorkspaceDiagnostic:
    ok: bool
    initialized: bool
    writable: bool | None
    free_bytes: int | None
    required_free_bytes: int
    issues: tuple[WorkspaceIssue, ...]

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "initialized": self.initialized, "writable": self.writable,
                "free_bytes": self.free_bytes, "required_free_bytes": self.required_free_bytes,
                "issues": [issue.to_dict() for issue in self.issues]}
