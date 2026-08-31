from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any


DEMO_ASSET_SCHEMA_VERSION = 1
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_IMPORTED_AT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_ASSET_KEYS = frozenset(
    {
        "schema_version",
        "asset_id",
        "logical_sha256",
        "logical_size_bytes",
        "source_sha256",
        "source_size_bytes",
        "source_format",
        "source_relative_path",
        "display_name",
        "imported_at",
    }
)
_CACHE_STATUSES = frozenset({"not_applicable", "missing", "valid", "corrupt"})
_PERSISTENT_SOURCE_ISSUES = frozenset({
    "demo_asset_integrity_failed",
    "demo_asset_manifest_invalid",
    "demo_asset_path_escape",
})


def _validate_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{field} 必须是 64 位小写 SHA-256。")
    return value


def _validate_size(value: object, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} 必须是非负整数。")
    return value


def _validate_imported_at(value: object) -> str:
    if not isinstance(value, str) or _IMPORTED_AT_RE.fullmatch(value) is None:
        raise ValueError("imported_at 必须是带 6 位微秒的 UTC 时间。")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise ValueError("imported_at 必须是有效的 UTC 时间。") from exc
    return value


def _validate_display_name(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or not value.strip() or len(value) > 255:
        raise ValueError("display_name 必须是 1 到 255 个字符。")
    if "/" in value or "\\" in value or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("display_name 不能包含路径分隔符或控制字符。")
    return value


def _validate_relative_path(value: object, asset_id: str, source_format: str) -> str:
    if not isinstance(value, str) or "\\" in value:
        raise ValueError("source_relative_path 必须是安全的正斜线路径。")
    parts = value.split("/")
    expected_name = "source." + source_format
    if parts != ["library", "demos", asset_id, expected_name]:
        raise ValueError("source_relative_path 必须指向当前资产的持久源。")
    return value


def _validate_asset_manifest_path(value: object, asset_id: str) -> str:
    if value != f"library/demos/{asset_id}/asset.json":
        raise ValueError("asset_manifest_relative_path 必须指向当前资产 manifest。")
    return value


@dataclass(frozen=True, slots=True)
class DemoAsset:
    schema_version: int
    asset_id: str
    logical_sha256: str
    logical_size_bytes: int
    source_sha256: str
    source_size_bytes: int
    source_format: str
    source_relative_path: str
    display_name: str
    imported_at: str

    def __post_init__(self) -> None:
        if type(self.schema_version) is not int or self.schema_version != DEMO_ASSET_SCHEMA_VERSION:
            raise ValueError("schema_version 必须为 1。")
        asset_id = _validate_hash(self.asset_id, "asset_id")
        logical_sha256 = _validate_hash(self.logical_sha256, "logical_sha256")
        source_sha256 = _validate_hash(self.source_sha256, "source_sha256")
        if asset_id != logical_sha256:
            raise ValueError("asset_id 必须等于 logical_sha256。")
        _validate_size(self.logical_size_bytes, "logical_size_bytes")
        _validate_size(self.source_size_bytes, "source_size_bytes")
        if self.source_format not in {"dem", "dem.zst"}:
            raise ValueError("source_format 必须为 dem 或 dem.zst。")
        _validate_relative_path(self.source_relative_path, asset_id, self.source_format)
        _validate_display_name(self.display_name)
        _validate_imported_at(self.imported_at)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "asset_id": self.asset_id,
            "logical_sha256": self.logical_sha256,
            "logical_size_bytes": self.logical_size_bytes,
            "source_sha256": self.source_sha256,
            "source_size_bytes": self.source_size_bytes,
            "source_format": self.source_format,
            "source_relative_path": self.source_relative_path,
            "display_name": self.display_name,
            "imported_at": self.imported_at,
        }

    @classmethod
    def from_dict(cls, value: object) -> "DemoAsset":
        if not isinstance(value, dict) or frozenset(value) != _ASSET_KEYS:
            raise ValueError("DemoAsset manifest 字段不符合固定 schema。")
        return cls(**value)

    def to_ref(self) -> "DemoAssetRef":
        return DemoAssetRef(self.asset_id, f"library/demos/{self.asset_id}/asset.json")


@dataclass(frozen=True, slots=True)
class DemoAssetRef:
    asset_id: str
    asset_manifest_relative_path: str

    def __post_init__(self) -> None:
        asset_id = _validate_hash(self.asset_id, "asset_id")
        _validate_asset_manifest_path(self.asset_manifest_relative_path, asset_id)

    def to_dict(self) -> dict[str, str]:
        return {
            "asset_id": self.asset_id,
            "asset_manifest_relative_path": self.asset_manifest_relative_path,
        }


@dataclass(frozen=True, slots=True)
class DemoImportResult:
    asset: DemoAsset
    disposition: str
    persistent_bytes_added: int

    def __post_init__(self) -> None:
        if not isinstance(self.asset, DemoAsset):
            raise ValueError("asset 必须是 DemoAsset。")
        if self.disposition not in {"imported", "reused"}:
            raise ValueError("disposition 必须为 imported 或 reused。")
        _validate_size(self.persistent_bytes_added, "persistent_bytes_added")
        if self.disposition == "reused" and self.persistent_bytes_added != 0:
            raise ValueError("reused 结果的 persistent_bytes_added 必须为 0。")

    def to_dict(self) -> dict[str, object]:
        return {
            "asset": self.asset.to_dict(),
            "disposition": self.disposition,
            "persistent_bytes_added": self.persistent_bytes_added,
        }


@dataclass(frozen=True, slots=True)
class DemoAssetSummary:
    asset_id: str
    display_name: str | None
    source_format: str | None
    source_size_bytes: int | None
    logical_size_bytes: int | None
    imported_at: str | None
    healthy: bool
    issue_code: str | None

    def __post_init__(self) -> None:
        _validate_hash(self.asset_id, "asset_id")
        if self.display_name is not None:
            _validate_display_name(self.display_name)
        if self.source_format is not None and self.source_format not in {"dem", "dem.zst"}:
            raise ValueError("source_format 必须为 dem 或 dem.zst。")
        if self.source_size_bytes is not None:
            _validate_size(self.source_size_bytes, "source_size_bytes")
        if self.logical_size_bytes is not None:
            _validate_size(self.logical_size_bytes, "logical_size_bytes")
        if self.imported_at is not None:
            _validate_imported_at(self.imported_at)
        if type(self.healthy) is not bool:
            raise ValueError("healthy 必须是布尔值。")
        if self.issue_code is not None and (not isinstance(self.issue_code, str) or not self.issue_code):
            raise ValueError("issue_code 必须是非空字符串。")
        if self.healthy and self.issue_code is not None:
            raise ValueError("healthy 资产不能带 issue_code。")
        if not self.healthy and not self.issue_code:
            raise ValueError("不健康资产必须带 issue_code。")

    def to_dict(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "display_name": self.display_name,
            "source_format": self.source_format,
            "source_size_bytes": self.source_size_bytes,
            "logical_size_bytes": self.logical_size_bytes,
            "imported_at": self.imported_at,
            "healthy": self.healthy,
            "issue_code": self.issue_code,
        }


@dataclass(frozen=True, slots=True)
class DemoAssetInspection:
    asset: DemoAsset
    source_ok: bool
    cache_status: str
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.asset, DemoAsset):
            raise ValueError("asset 必须是 DemoAsset。")
        if type(self.source_ok) is not bool:
            raise ValueError("source_ok 必须是布尔值。")
        if self.cache_status not in _CACHE_STATUSES:
            raise ValueError("cache_status 不符合固定集合。")
        if self.asset.source_format == "dem" and self.cache_status != "not_applicable":
            raise ValueError("未压缩 Demo 的 cache_status 必须为 not_applicable。")
        if self.asset.source_format == "dem.zst" and self.cache_status == "not_applicable":
            raise ValueError("压缩 Demo 必须报告解压缓存状态。")
        if not isinstance(self.issues, tuple) or not all(isinstance(issue, str) and issue for issue in self.issues):
            raise ValueError("issues 必须是非空字符串元组。")
        has_persistent_issue = any(issue in _PERSISTENT_SOURCE_ISSUES for issue in self.issues)
        if self.source_ok and has_persistent_issue:
            raise ValueError("source_ok 为真时不能带持久源错误。")
        if not self.source_ok and not has_persistent_issue:
            raise ValueError("source_ok 为假时必须带持久源错误。")

    @property
    def ok(self) -> bool:
        return self.source_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset": self.asset.to_dict(),
            "source_ok": self.source_ok,
            "cache_status": self.cache_status,
            "issues": list(self.issues),
            "ok": self.ok,
        }
