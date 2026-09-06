from __future__ import annotations

import math
import re
from datetime import datetime
from collections.abc import Mapping
from typing import Final
from .errors import DomainSchemaError

CURRENT_DOMAIN_SCHEMA_VERSION: Final[int] = 1
MAX_DEMO_TIME_US = 2_592_000_000_000
MAX_SOURCE_POSITION = 9_223_372_036_854_775_807
MAX_COUNT = 2_147_483_647
SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
PATH_IDENTIFIER_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
WINDOWS_INVALID_FILENAME_CHARS = frozenset('<>:"/\\|?*')
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_SECRET_KEYS = frozenset(
    {
        "api_key",
        "api-key",
        "x-api-key",
        "authorization",
        "proxy-authorization",
        "access_token",
        "refresh_token",
        "client_secret",
        "secret",
        "password",
    }
)
FORBIDDEN_DURABLE_KEYS = FORBIDDEN_SECRET_KEYS | frozenset(
    {"path", "file_path", "directory_path", "steamid", "steam_id"}
)
WINDOWS_RESERVED_STEMS = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)


def _err(code, path, msg="字段无效。"):
    raise DomainSchemaError(code, msg, "请修正后重试。", path)


def require_mapping(value, path):
    if not isinstance(value, Mapping):
        _err("domain_field_invalid", path)
    return value


def require_canonical_utc_timestamp(value: object, path: str) -> str:
    """Validate an exact UTC timestamp and preserve its canonical bytes."""
    if not isinstance(value, str) or value != value.strip():
        _err("domain_field_invalid", path, "时间格式无效。")
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z", value) is None:
        _err("domain_field_invalid", path, "时间必须是带 6 位微秒的 UTC 时间。")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as exc:
        raise DomainSchemaError("domain_field_invalid", "时间无效。", "请修正后重试。", path) from exc
    # strftime does not zero-pad years below 1000 on all platforms.
    return value


def require_exact_keys(data, required, optional, path):
    missing = required - set(data)
    unknown = set(data) - (required | optional)
    if missing or unknown:
        _err("domain_schema_invalid", path, "数据结构无效。")


def require_current_schema(data, path):
    if (
        not isinstance(data, Mapping)
        or type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
    ):
        _err("domain_schema_unsupported", path, "不支持的领域版本。")
    return 1


def require_int(value, path, *, minimum=None, maximum=None):
    if (
        type(value) is not int
        or (minimum is not None and value < minimum)
        or (maximum is not None and value > maximum)
    ):
        _err("domain_field_invalid", path)
    return value


def require_optional_int(value, path, *, minimum=None, maximum=None):
    return (
        None
        if value is None
        else require_int(value, path, minimum=minimum, maximum=maximum)
    )


def require_str(value, path, *, allow_empty=False):
    if not isinstance(value, str) or (not allow_empty and not value):
        _err("domain_field_invalid", path)
    return value


def require_optional_str(value, path, *, allow_empty=False):
    return None if value is None else require_str(value, path, allow_empty=allow_empty)


def require_identifier(value, path):
    if (
        not isinstance(value, str)
        or not SAFE_IDENTIFIER_RE.fullmatch(value)
        or value in (".", "..")
        or value.split(".")[0].upper() in WINDOWS_RESERVED_STEMS
    ):
        _err("domain_identifier_invalid", path, "标识符无效。")
    return value


def require_path_identifier(value, path):
    """Validate an identifier which will become a filesystem path segment.

    This deliberately stays stricter than ``require_identifier`` so legacy
    domain values keep their historical acceptance rules.
    """
    if (
        not isinstance(value, str)
        or PATH_IDENTIFIER_RE.fullmatch(value) is None
        or value.rstrip(" .") != value
        or value in {".", ".."}
        or value.split(".")[0].upper() in WINDOWS_RESERVED_STEMS
    ):
        _err("domain_identifier_invalid", path, "路径标识符无效。")
    return value


def require_artifact_segment(value, path):
    """Validate one persisted artifact filename segment (extension allowed)."""
    if not isinstance(value, str) or not value or value in {".", ".."}:
        _err("domain_identifier_invalid", path, "产物路径段无效。")
    if value.rstrip(" .") != value or any(ord(c) < 32 or c in WINDOWS_INVALID_FILENAME_CHARS for c in value):
        _err("domain_identifier_invalid", path, "产物路径段含有 Windows 非法字符。")
    stem = value.split(".", 1)[0]
    if stem.upper() in WINDOWS_RESERVED_STEMS:
        _err("domain_identifier_invalid", path, "产物路径段不能使用 Windows 设备名。")
    return value


def require_artifact_relative_path(value, kind, path="relative_path"):
    """Validate and return an artifact path beneath its kind-specific final tree."""
    if not isinstance(value, str) or "\\" in value:
        _err("domain_identifier_invalid", path, "产物路径无效。")
    kind_value = getattr(kind, "value", kind)
    roots = {
        "timeline": ("final", "timelines"),
        "subtitle": ("final", "subtitles"),
        "green_screen": ("final", "green_screen"),
        "video": ("final", "video"),
    }
    root = roots.get(kind_value)
    parts = value.split("/")
    if root is None or len(parts) < 3 or tuple(parts[:2]) != root or any(not part or part in {".", ".."} for part in parts):
        _err("domain_identifier_invalid", path, "产物路径不在对应目录中。")
    for part in parts[2:]:
        require_artifact_segment(part, path)
    return value


def require_logical_path(value, path="logical_path"):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value or "://" in value:
        raise ValueError("logical_path must be a non-empty relative POSIX path")
    if value.startswith("/") or value.startswith("~"):
        raise ValueError("logical_path must be relative")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("logical_path must be normalized")
    return value


def require_sha256(value, path):
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _err("domain_field_invalid", path)
    return value


def require_probability(value, path):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        _err("domain_field_invalid", path)
    return float(value)


def require_string_list(value, path, *, allow_empty=True):
    if not isinstance(value, (list, tuple)) or (not allow_empty and not value):
        _err("domain_field_invalid", path)
    return tuple(require_str(x, f"{path}[]") for x in value)


def reject_secret_keys(value, path):
    if isinstance(value, Mapping):
        for k, v in value.items():
            if str(k).lower() in FORBIDDEN_SECRET_KEYS:
                _err("domain_secret_forbidden", f"{path}.{k}", "禁止保存秘密信息。")
            reject_secret_keys(v, f"{path}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            reject_secret_keys(v, f"{path}[{i}]")


def reject_private_data(value, path):
    reject_secret_keys(value, path)

    def scan(v, p):
        if isinstance(v, Mapping):
            for k, x in v.items():
                if (
                    str(k).lower() in FORBIDDEN_DURABLE_KEYS
                    and str(k).lower() not in FORBIDDEN_SECRET_KEYS
                ):
                    _err(
                        "domain_private_data_forbidden",
                        f"{p}.{k}",
                        "禁止保存私有数据。",
                    )
                scan(x, f"{p}.{k}")
        elif isinstance(v, (list, tuple)):
            for i, x in enumerate(v):
                scan(x, f"{p}[{i}]")
        elif isinstance(v, str) and (
            re.match(r"^[A-Za-z]:[\\/]", v)
            or v.startswith(("\\\\", "/", "~/", "~\\"))
            or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://", v)
        ):
            _err("domain_private_data_forbidden", p, "禁止保存私有数据。")

    scan(value, path)
