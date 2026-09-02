from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from collections.abc import Mapping
from typing import Any

from .assets import DemoAssetRef, validate_display_name
from .errors import DomainSchemaError
from .fingerprint import content_fingerprint
from .schema import (
    MAX_COUNT,
    require_current_schema,
    require_exact_keys,
    require_identifier,
    require_int,
    require_mapping,
    require_path_identifier,
    require_artifact_relative_path,
    require_logical_path,
    require_sha256,
    require_str,
    reject_private_data,
)

CURRENT_JOB_SCHEMA_VERSION = 1


def _invalid(path: str, code: str = "domain_field_invalid", message: str = "Job 数据无效。"):
    raise DomainSchemaError(code, message, "请修正后重试。", path)


def _timestamp(value: object, path: str) -> str:
    if not isinstance(value, str) or value != value.strip():
        _invalid(path, "domain_field_invalid", "时间格式无效。")
    # Durable timestamps are intentionally canonical, not merely parseable.
    import re

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value) is None:
        _invalid(path, "domain_field_invalid", "时间必须是带 6 位微秒的 UTC 时间。")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise DomainSchemaError("domain_field_invalid", "时间无效。", "请修正后重试。", path) from exc
    return parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _name(value: object, path: str) -> str:
    try:
        return validate_display_name(value)
    except (TypeError, ValueError) as exc:
        raise DomainSchemaError("domain_field_invalid", "显示名称无效。", "请修正后重试。", path) from exc


def _enum(cls: type[Enum], value: object, path: str):
    if not isinstance(value, cls):
        _invalid(path)
    return value


def _tuple(value: object, path: str) -> tuple[Any, ...]:
    if not isinstance(value, (tuple, list)):
        _invalid(path)
    return tuple(value)


def _unique(values: tuple[str, ...], path: str) -> tuple[str, ...]:
    folded = [v.casefold() for v in values]
    if len(set(folded)) != len(folded):
        _invalid(path, "domain_field_invalid", "列表中存在重复标识符。")
    return values


class JobPhase(str, Enum):
    CREATED = "created"
    TIMELINE_READY = "timeline_ready"
    VOICE_READY = "voice_ready"
    TRANSCRIBED = "transcribed"
    CONTEXT_READY = "context_ready"
    UNDERSTANDING_TRANSLATING = "understanding_translating"
    UNDERSTOOD_TRANSLATED = "understood_translated"
    DRAFT_TIMELINE_READY = "draft_timeline_ready"
    COMPLETED_DRAFT = "completed_draft"
    REVIEW_PENDING = "review_pending"
    REVIEWED = "reviewed"
    FINAL_TIMELINE_READY = "final_timeline_ready"
    SUBTITLES_EXPORTED = "subtitles_exported"
    GREEN_SCREEN_RENDERED = "green_screen_rendered"
    COMPLETED_WITHOUT_VIDEO = "completed_without_video"
    READY_FOR_RENDER = "ready_for_render"
    RENDERING = "rendering"
    VIDEO_READY = "video_ready"
    COMPLETED_WITH_VIDEO = "completed_with_video"


class JobRunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class FinalArtifactKind(str, Enum):
    TIMELINE = "timeline"
    SUBTITLE = "subtitle"
    GREEN_SCREEN = "green_screen"
    VIDEO = "video"


class FinalArtifactTimebase(str, Enum):
    DEMO_GLOBAL = "demo_global"
    ROUND_LOCAL = "round_local"


@dataclass(frozen=True, slots=True)
class RoundProgressSummary:
    total: int
    succeeded: int
    failed: int
    review_pending: int

    def __post_init__(self) -> None:
        for value, path in ((self.total, "total"), (self.succeeded, "succeeded"), (self.failed, "failed"), (self.review_pending, "review_pending")):
            require_int(value, path, minimum=0, maximum=MAX_COUNT)
        if self.succeeded > self.total or self.failed > self.total or self.review_pending > self.total or self.succeeded + self.failed + self.review_pending > self.total:
            _invalid("round_progress", message="回合进度统计无效。")

    def to_dict(self) -> dict[str, int]:
        return {"total": self.total, "succeeded": self.succeeded, "failed": self.failed, "review_pending": self.review_pending}

    @classmethod
    def from_dict(cls, value: object) -> "RoundProgressSummary":
        d = require_mapping(value, "round_progress")
        reject_private_data(d, "round_progress")
        require_exact_keys(d, {"total", "succeeded", "failed", "review_pending"}, set(), "round_progress")
        return cls(d["total"], d["succeeded"], d["failed"], d["review_pending"])


@dataclass(frozen=True, slots=True)
class FinalArtifactEntry:
    artifact_id: str
    kind: FinalArtifactKind
    relative_path: str
    content_sha256: str
    round_id: str | None
    timebase: FinalArtifactTimebase | None

    def __post_init__(self) -> None:
        require_path_identifier(self.artifact_id, "artifact_id")
        _enum(FinalArtifactKind, self.kind, "kind")
        require_sha256(self.content_sha256, "content_sha256")
        require_artifact_relative_path(self.relative_path, self.kind)
        if self.round_id is not None:
            require_path_identifier(self.round_id, "round_id")
        if self.timebase is not None:
            _enum(FinalArtifactTimebase, self.timebase, "timebase")

    def to_dict(self) -> dict[str, object]:
        return {"artifact_id": self.artifact_id, "kind": self.kind.value, "relative_path": self.relative_path, "content_sha256": self.content_sha256, "round_id": self.round_id, "timebase": None if self.timebase is None else self.timebase.value}

    @classmethod
    def from_dict(cls, value: object) -> "FinalArtifactEntry":
        d = require_mapping(value, "final_artifact")
        reject_private_data(d, "final_artifact")
        require_exact_keys(d, {"artifact_id", "kind", "relative_path", "content_sha256", "round_id", "timebase"}, set(), "final_artifact")
        try:
            kind = FinalArtifactKind(d["kind"])
            timebase = None if d["timebase"] is None else FinalArtifactTimebase(d["timebase"])
        except (ValueError, TypeError) as exc:
            raise DomainSchemaError("domain_field_invalid", "产物类型无效。", "请修正后重试。", "final_artifact") from exc
        return cls(d["artifact_id"], kind, d["relative_path"], d["content_sha256"], d["round_id"], timebase)


@dataclass(frozen=True, slots=True)
class CreateJobRequest:
    job_id: str
    display_name: str
    source: "JobDemoSource"

    def __post_init__(self) -> None:
        require_path_identifier(self.job_id, "job_id")
        _name(self.display_name, "display_name")
        if not isinstance(self.source, JobDemoSource):
            _invalid("source")
        reject_private_data(self.to_dict(), "create_job_request")

    def to_dict(self) -> dict[str, object]:
        return {"job_id": self.job_id, "display_name": self.display_name, "source": self.source.to_dict()}


@dataclass(frozen=True, slots=True)
class JobManifest:
    job_id: str
    display_name: str
    created_at: str
    updated_at: str
    demo_asset_id: str
    demo_display_name: str
    map_name: str | None
    target_player_id: str | None
    phase: JobPhase
    run_status: JobRunStatus
    round_progress: RoundProgressSummary
    configuration_snapshot_ids: tuple[str, ...]
    active_review_id: str | None
    final_artifacts: tuple[FinalArtifactEntry, ...]

    def __post_init__(self) -> None:
        require_path_identifier(self.job_id, "job_id")
        _name(self.display_name, "display_name")
        created = _timestamp(self.created_at, "created_at")
        updated = _timestamp(self.updated_at, "updated_at")
        if updated < created:
            _invalid("updated_at", message="更新时间不能早于创建时间。")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "updated_at", updated)
        require_sha256(self.demo_asset_id, "demo_asset_id")
        _name(self.demo_display_name, "demo_display_name")
        if self.map_name is not None:
            require_identifier(self.map_name, "map_name")
        if self.target_player_id is not None:
            require_identifier(self.target_player_id, "target_player_id")
        _enum(JobPhase, self.phase, "phase")
        _enum(JobRunStatus, self.run_status, "run_status")
        if not isinstance(self.round_progress, RoundProgressSummary):
            _invalid("round_progress")
        snapshots = _tuple(self.configuration_snapshot_ids, "configuration_snapshot_ids")
        snapshots = tuple(require_path_identifier(x, "configuration_snapshot_ids[]") for x in snapshots)
        object.__setattr__(self, "configuration_snapshot_ids", _unique(snapshots, "configuration_snapshot_ids"))
        if self.active_review_id is not None:
            require_path_identifier(self.active_review_id, "active_review_id")
        artifacts = _tuple(self.final_artifacts, "final_artifacts")
        if any(not isinstance(x, FinalArtifactEntry) for x in artifacts):
            _invalid("final_artifacts")
        _unique(tuple(x.artifact_id for x in artifacts), "final_artifacts")
        _unique(tuple(x.relative_path.casefold() for x in artifacts), "final_artifacts")
        object.__setattr__(self, "final_artifacts", artifacts)
        reject_private_data(self.to_dict(), "job_manifest")

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "job_id": self.job_id, "display_name": self.display_name, "created_at": self.created_at, "updated_at": self.updated_at, "demo_asset_id": self.demo_asset_id, "demo_display_name": self.demo_display_name, "map_name": self.map_name, "target_player_id": self.target_player_id, "phase": self.phase.value, "run_status": self.run_status.value, "round_progress": self.round_progress.to_dict(), "configuration_snapshot_ids": list(self.configuration_snapshot_ids), "active_review_id": self.active_review_id, "final_artifacts": [x.to_dict() for x in self.final_artifacts]}

    def content_fingerprint(self) -> str:
        return content_fingerprint(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "JobManifest":
        d = require_mapping(value, "job_manifest")
        reject_private_data(d, "job_manifest")
        require_current_schema(d, "job_manifest")
        require_exact_keys(d, {"schema_version", "job_id", "display_name", "created_at", "updated_at", "demo_asset_id", "demo_display_name", "map_name", "target_player_id", "phase", "run_status", "round_progress", "configuration_snapshot_ids", "active_review_id", "final_artifacts"}, set(), "job_manifest")
        try:
            phase = JobPhase(d["phase"])
            status = JobRunStatus(d["run_status"])
        except (TypeError, ValueError) as exc:
            raise DomainSchemaError("domain_field_invalid", "Job 状态无效。", "请修正后重试。", "job_manifest") from exc
        return cls(d["job_id"], d["display_name"], d["created_at"], d["updated_at"], d["demo_asset_id"], d["demo_display_name"], d["map_name"], d["target_player_id"], phase, status, RoundProgressSummary.from_dict(d["round_progress"]), tuple(d["configuration_snapshot_ids"]), d["active_review_id"], tuple(FinalArtifactEntry.from_dict(x) for x in d["final_artifacts"]))


@dataclass(frozen=True, slots=True)
class JobRepositoryMarker:
    job_id: str
    repository_kind: str = "cs2pov-current-job"

    def __post_init__(self) -> None:
        require_path_identifier(self.job_id, "job_id")
        if self.repository_kind != "cs2pov-current-job":
            _invalid("repository_kind")

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "repository_kind": self.repository_kind, "job_id": self.job_id}

    @classmethod
    def from_dict(cls, value: object) -> "JobRepositoryMarker":
        d = require_mapping(value, "repository")
        reject_private_data(d, "repository")
        require_current_schema(d, "repository")
        require_exact_keys(d, {"schema_version", "repository_kind", "job_id"}, set(), "repository")
        return cls(d["job_id"], d["repository_kind"])


@dataclass(frozen=True, slots=True)
class JobDemoSource:
    asset_id: str
    asset_manifest_relative_path: str
    display_name: str

    def __post_init__(self) -> None:
        try:
            DemoAssetRef(self.asset_id, self.asset_manifest_relative_path)
        except (TypeError, ValueError) as exc:
            raise DomainSchemaError(
                "domain_field_invalid",
                "Demo 来源引用无效。",
                "请修正后重试。",
                "demo_source",
            ) from exc
        _name(self.display_name, "display_name")
        reject_private_data(self.to_dict(), "demo_source")

    def to_ref(self) -> DemoAssetRef:
        return DemoAssetRef(self.asset_id, self.asset_manifest_relative_path)

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "asset_id": self.asset_id, "asset_manifest_relative_path": self.asset_manifest_relative_path, "display_name": self.display_name}

    @classmethod
    def from_dict(cls, value: object) -> "JobDemoSource":
        d = require_mapping(value, "demo_source")
        reject_private_data(d, "demo_source")
        require_current_schema(d, "demo_source")
        require_exact_keys(d, {"schema_version", "asset_id", "asset_manifest_relative_path", "display_name"}, set(), "demo_source")
        return cls(d["asset_id"], d["asset_manifest_relative_path"], d["display_name"])


def _freeze(value: object, path: str = "payload") -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(k, str) for k in value):
            _invalid(path)
        return ("__dict__", tuple(sorted((k, _freeze(v, f"{path}.{k}")) for k, v in value.items())))
    if isinstance(value, (list, tuple)):
        return ("__list__", tuple(_freeze(v, f"{path}[]") for v in value))
    if isinstance(value, float) and not math.isfinite(value):
        _invalid(path)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    _invalid(path)


def _thaw(value: object) -> object:
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "__dict__":
        return {k: _thaw(v) for k, v in value[1]}
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "__list__":
        return [_thaw(v) for v in value[1]]
    return value


@dataclass(frozen=True, slots=True)
class JobEvent:
    event_id: str
    job_id: str
    run_id: str
    occurred_at: str
    event_type: str
    payload: object

    def __post_init__(self) -> None:
        require_path_identifier(self.event_id, "event_id")
        require_path_identifier(self.job_id, "job_id")
        require_path_identifier(self.run_id, "run_id")
        object.__setattr__(self, "occurred_at", _timestamp(self.occurred_at, "occurred_at"))
        require_identifier(self.event_type, "event_type")
        reject_private_data({"event_type": self.event_type, "payload": self.payload}, "event")
        object.__setattr__(self, "payload", _freeze(self.payload))

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "event_id": self.event_id, "job_id": self.job_id, "run_id": self.run_id, "occurred_at": self.occurred_at, "event_type": self.event_type, "payload": _thaw(self.payload)}

    @classmethod
    def from_dict(cls, value: object) -> "JobEvent":
        d = require_mapping(value, "event")
        reject_private_data(d, "event")
        require_current_schema(d, "event")
        require_exact_keys(d, {"schema_version", "event_id", "job_id", "run_id", "occurred_at", "event_type", "payload"}, set(), "event")
        return cls(d["event_id"], d["job_id"], d["run_id"], d["occurred_at"], d["event_type"], d["payload"])


@dataclass(frozen=True, slots=True)
class JobWriteClaim:
    job_id: str
    run_id: str
    process_id: int
    acquired_at: str
    heartbeat_at: str
    lease_expires_at: str

    def __post_init__(self) -> None:
        require_path_identifier(self.job_id, "job_id")
        require_path_identifier(self.run_id, "run_id")
        require_int(self.process_id, "process_id", minimum=0)
        acquired = _timestamp(self.acquired_at, "acquired_at")
        heartbeat = _timestamp(self.heartbeat_at, "heartbeat_at")
        expiry = _timestamp(self.lease_expires_at, "lease_expires_at")
        if heartbeat < acquired or expiry <= heartbeat:
            _invalid("lease_expires_at", message="Claim 租约时间无效。")
        object.__setattr__(self, "acquired_at", acquired)
        object.__setattr__(self, "heartbeat_at", heartbeat)
        object.__setattr__(self, "lease_expires_at", expiry)

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, "job_id": self.job_id, "run_id": self.run_id, "process_id": self.process_id, "acquired_at": self.acquired_at, "heartbeat_at": self.heartbeat_at, "lease_expires_at": self.lease_expires_at}

    @classmethod
    def from_dict(cls, value: object) -> "JobWriteClaim":
        d = require_mapping(value, "claim")
        reject_private_data(d, "claim")
        require_current_schema(d, "claim")
        require_exact_keys(d, {"schema_version", "job_id", "run_id", "process_id", "acquired_at", "heartbeat_at", "lease_expires_at"}, set(), "claim")
        return cls(d["job_id"], d["run_id"], d["process_id"], d["acquired_at"], d["heartbeat_at"], d["lease_expires_at"])


@dataclass(frozen=True, slots=True)
class JobIssue:
    code: str
    severity: str
    message_zh: str
    suggestion_zh: str
    logical_path: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code or self.severity not in {"warning", "error"}:
            _invalid("issue")
        require_str(self.message_zh, "message_zh")
        require_str(self.suggestion_zh, "suggestion_zh")
        reject_private_data({"code": self.code, "message_zh": self.message_zh, "suggestion_zh": self.suggestion_zh, "logical_path": self.logical_path}, "issue")
        if self.logical_path is not None:
            try:
                require_logical_path(self.logical_path)
            except ValueError as exc:
                raise DomainSchemaError("domain_field_invalid", "诊断路径无效。", "请修正后重试。", "logical_path") from exc


@dataclass(frozen=True, slots=True)
class JobCatalogEntry:
    discovery_id: str
    job_id: str | None
    display_name: str | None
    created_at: str | None
    updated_at: str | None
    demo_asset_id: str | None
    demo_display_name: str | None
    map_name: str | None
    target_player_id: str | None
    phase: JobPhase | None
    durable_run_status: JobRunStatus | None
    effective_run_status: JobRunStatus | None
    round_progress: RoundProgressSummary | None
    final_artifact_kinds: tuple[FinalArtifactKind, ...]
    healthy: bool
    issues: tuple[JobIssue, ...]

    def __post_init__(self) -> None:
        require_path_identifier(self.discovery_id, "discovery_id")
        if self.job_id is not None:
            require_path_identifier(self.job_id, "job_id")
        if self.display_name is not None:
            _name(self.display_name, "display_name")
        if self.demo_display_name is not None:
            _name(self.demo_display_name, "demo_display_name")
        if (self.created_at is None) != (self.updated_at is None):
            _invalid("created_at", message="创建和更新时间必须同时存在。")
        if self.created_at is not None:
            created = _timestamp(self.created_at, "created_at")
            updated = _timestamp(self.updated_at, "updated_at")
            if updated < created:
                _invalid("updated_at", message="更新时间不能早于创建时间。")
            object.__setattr__(self, "created_at", created)
            object.__setattr__(self, "updated_at", updated)
        if self.demo_asset_id is not None:
            require_sha256(self.demo_asset_id, "demo_asset_id")
        if self.map_name is not None:
            require_identifier(self.map_name, "map_name")
        if self.target_player_id is not None:
            require_identifier(self.target_player_id, "target_player_id")
        if self.phase is not None:
            _enum(JobPhase, self.phase, "phase")
        if self.durable_run_status is not None:
            _enum(JobRunStatus, self.durable_run_status, "durable_run_status")
        if self.effective_run_status is not None:
            _enum(JobRunStatus, self.effective_run_status, "effective_run_status")
        if self.round_progress is not None and not isinstance(self.round_progress, RoundProgressSummary):
            _invalid("round_progress")
        kinds = _tuple(self.final_artifact_kinds, "final_artifact_kinds")
        if any(not isinstance(kind, FinalArtifactKind) for kind in kinds):
            _invalid("final_artifact_kinds")
        object.__setattr__(self, "final_artifact_kinds", kinds)
        if type(self.healthy) is not bool:
            _invalid("healthy")
        issues = _tuple(self.issues, "issues")
        if any(not isinstance(issue, JobIssue) for issue in issues):
            _invalid("issues")
        if len(set(kinds)) != len(kinds):
            _invalid("final_artifact_kinds", message="产物类型不能重复。")
        if self.healthy and any(issue.severity == "error" for issue in issues):
            _invalid("issues", message="健康 Job 不能带错误诊断。")
        if not self.healthy and not any(issue.severity == "error" for issue in issues):
            _invalid("issues", message="不健康 Job 必须带错误诊断。")
        reject_private_data({"display_name": self.display_name, "demo_display_name": self.demo_display_name, "logical_path": [issue.logical_path for issue in issues]}, "catalog")
        object.__setattr__(self, "issues", issues)


@dataclass(frozen=True, slots=True)
class JobInspection:
    entry: JobCatalogEntry
    marker: JobRepositoryMarker | None
    manifest: JobManifest | None
    source: JobDemoSource | None
    events: tuple[JobEvent, ...]
    event_tail_incomplete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.entry, JobCatalogEntry):
            _invalid("entry")
        if self.marker is not None and not isinstance(self.marker, JobRepositoryMarker):
            _invalid("marker")
        if self.manifest is not None and not isinstance(self.manifest, JobManifest):
            _invalid("manifest")
        if self.source is not None and not isinstance(self.source, JobDemoSource):
            _invalid("source")
        events = _tuple(self.events, "events")
        if any(not isinstance(event, JobEvent) for event in events):
            _invalid("events")
        object.__setattr__(self, "events", events)
        if type(self.event_tail_incomplete) is not bool:
            _invalid("event_tail_incomplete")
        reject_private_data(
            {
                "marker": None if self.marker is None else self.marker.to_dict(),
                "manifest": None if self.manifest is None else self.manifest.to_dict(),
                "source": None if self.source is None else self.source.to_dict(),
                "events": [event.to_dict() for event in events],
            },
            "inspection",
        )
