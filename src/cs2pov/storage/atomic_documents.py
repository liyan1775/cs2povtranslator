from __future__ import annotations

import enum
import errno
import json
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable, Iterable, Mapping

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.schema import reject_private_data

from .job_errors import JobRepositoryError


class SchemaClassification(enum.Enum):
    CURRENT = "current"
    UNSUPPORTED = "unsupported"
    MALFORMED = "malformed"


@dataclass(frozen=True, slots=True)
class SchemaExpectation:
    pointer: str


@dataclass(frozen=True, slots=True)
class JsonlReadResult:
    records: tuple[object, ...]
    incomplete_tail: bool = False


def _repo_error(code: str, message: str, logical_path: str, cause: BaseException | None = None):
    error = JobRepositoryError(code, message, "请检查文档后重试。", logical_path)
    if cause is not None:
        error.__cause__ = cause
    return error


def _map_exception(exc: BaseException, logical_path: str):
    if isinstance(exc, JobRepositoryError):
        return exc
    if isinstance(exc, DomainSchemaError):
        code = "job_schema_unsupported" if exc.code == "domain_schema_unsupported" else "job_shard_invalid"
        return _repo_error(code, "Job 文档校验失败。", logical_path, exc)
    return _repo_error("job_shard_invalid", "Job 文档格式无效。", logical_path, exc)


_EXPECTED_PARSE_ERRORS = (DomainSchemaError, ValueError, TypeError, OSError, UnicodeError, OverflowError)


def _reject_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")


def _reject_duplicate(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _loads(data: bytes, logical_path: str):
    if data.startswith(b"\xef\xbb\xbf"):
        raise _repo_error("job_shard_invalid", "JSON 不得包含 BOM。", logical_path)
    try:
        text = data.decode("utf-8")
        return json.loads(text, object_pairs_hook=_reject_duplicate, parse_constant=_reject_constant)
    except JobRepositoryError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise _repo_error("job_shard_invalid", "JSON 文档格式无效。", logical_path, exc) from exc


def _validate_regular(path: Path, logical_path: str, *, missing_code: str = "job_shard_missing") -> None:
    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        raise _repo_error(missing_code, "Job 文档不存在。", logical_path, exc) from exc
    except OSError as exc:
        raise _repo_error("job_shard_invalid", "无法检查 Job 文档。", logical_path, exc) from exc
    if _is_link_or_reparse(st) or not stat.S_ISREG(st.st_mode):
        raise _repo_error("job_shard_invalid", "Job 文档必须是普通文件。", logical_path)


def _is_link_or_reparse(st) -> bool:
    attrs = getattr(st, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(st.st_mode) or bool(attrs & reparse)


def _validate_parent(path: Path, logical_path: str) -> None:
    parent = path.parent
    current = parent
    while True:
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            current = current.parent
            if current == parent:
                break
            continue
        if _is_link_or_reparse(st) or not stat.S_ISDIR(st.st_mode):
            raise _repo_error("job_path_escape", "Job 文档目录包含链接或不是目录。", logical_path)
        if current == current.parent:
            break
        current = current.parent


def _read_verified_bytes(path: Path, logical_path: str) -> bytes:
    _validate_parent(path, logical_path)
    _validate_regular(path, logical_path)
    flags = os.O_RDONLY
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise _repo_error("job_shard_invalid", "无法打开 Job 文档。", logical_path, exc) from exc
    try:
        opened = os.fstat(fd)
        current = os.lstat(path)
        if _is_link_or_reparse(current) or not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise _repo_error("job_shard_invalid", "Job 文档在读取期间发生变化。", logical_path)
        chunks = []
        while True:
            try:
                chunk = os.read(fd, 1024 * 1024)
            except OSError as exc:
                if exc.errno == errno.EINTR:
                    continue
                raise
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    except JobRepositoryError:
        raise
    except OSError as exc:
        raise _repo_error("job_shard_invalid", "无法读取 Job 文档。", logical_path, exc) from exc
    finally:
        os.close(fd)


def _write_all(fd: int, payload: bytes) -> None:
    offset = 0
    while offset < len(payload):
        try:
            written = os.write(fd, payload[offset:])
        except OSError as exc:
            if exc.errno == errno.EINTR:
                continue
            raise
        if written <= 0:
            raise OSError(errno.EIO, "zero-progress write")
        offset += written


def _serialize(value, serializer, logical_path: str) -> bytes:
    try:
        payload = serializer(value)
        reject_private_data(payload, logical_path)
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return (text + "\n").encode("utf-8")
    except JobRepositoryError:
        raise
    except (DomainSchemaError, TypeError, ValueError, OverflowError, UnicodeError) as exc:
        raise _map_exception(exc, logical_path) from exc


def read_strict_json(path: Path, *, logical_path: str, parser: Callable[[object], object]):
    try:
        raw = _read_verified_bytes(path, logical_path)
        value = _loads(raw, logical_path)
        if not isinstance(value, Mapping):
            raise _repo_error("job_shard_invalid", "JSON 顶层必须是对象。", logical_path)
        return parser(value)
    except _EXPECTED_PARSE_ERRORS as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise _map_exception(exc, logical_path) from exc


def atomic_write_json(path: Path, value, *, logical_path: str, serializer: Callable[[object], object], parser: Callable[[object], object]):
    # Serializer and parser run before touching the destination filesystem.
    payload = _serialize(value, serializer, logical_path)
    parsed = _loads(payload, logical_path)
    if not isinstance(parsed, Mapping):
        raise _repo_error("job_shard_invalid", "JSON 顶层必须是对象。", logical_path)
    try:
        parser(parsed)
    except _EXPECTED_PARSE_ERRORS as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise _map_exception(exc, logical_path) from exc
    _validate_parent(path, logical_path)
    try:
        if path.exists() or path.is_symlink():
            _validate_regular(path, logical_path, missing_code="job_shard_invalid")
    except JobRepositoryError:
        raise
    staging = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    replaced = False
    try:
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(staging, path)
        replaced = True
        if os.name != "nt":
            _fsync_directory(path.parent, logical_path)
    except JobRepositoryError:
        raise
    except OSError as exc:
        if replaced:
            raise _repo_error("job_write_durability_uncertain", "文档已可见但目录持久化状态不确定。", logical_path, exc) from exc
        raise _repo_error("job_write_failed", "Job 文档写入失败。", logical_path, exc) from exc
    finally:
        try:
            staging.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return None


def _fsync_directory(path: Path, logical_path: str) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError as exc:
        raise _repo_error("job_write_durability_uncertain", "文档已可见但目录持久化状态不确定。", logical_path, exc) from exc
    finally:
        os.close(fd)


def read_strict_jsonl(path: Path, *, logical_path: str, parser: Callable[[object], object], allow_incomplete_tail: bool = False) -> JsonlReadResult:
    try:
        raw = _read_verified_bytes(path, logical_path)
        if raw.startswith(b"\xef\xbb\xbf"):
            raise _repo_error("job_shard_invalid", "JSONL 不得包含 BOM。", logical_path)
        records: list[object] = []
        lines = raw.splitlines(keepends=True)
        incomplete = bool(raw) and not raw.endswith(b"\n")
        if incomplete and not allow_incomplete_tail:
            raise _repo_error("job_shard_invalid", "JSONL 末行不完整。", logical_path)
        for index, line in enumerate(lines, 1):
            terminal = line.endswith(b"\n")
            if incomplete and index == len(lines) and not terminal:
                break
            content = line[:-1] if terminal else line
            if content.endswith(b"\r"):
                content = content[:-1]
            if not content:
                raise _repo_error("job_shard_invalid", f"JSONL 第 {index} 条记录为空。", f"{logical_path}#{index}")
            value = _loads(content, f"{logical_path}#{index}")
            if not isinstance(value, Mapping):
                raise _repo_error("job_shard_invalid", "JSONL 记录必须是对象。", f"{logical_path}#{index}")
            try:
                value = parser(value)
            except _EXPECTED_PARSE_ERRORS as exc:
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise
                raise _map_exception(exc, f"{logical_path}#{index}") from exc
            records.append(value)
        return JsonlReadResult(tuple(records), incomplete)
    except _EXPECTED_PARSE_ERRORS as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        if isinstance(exc, JobRepositoryError):
            raise
        raise _map_exception(exc, logical_path) from exc


def atomic_write_jsonl(path: Path, values: Iterable[object], *, logical_path: str, serializer: Callable[[object], object], parser: Callable[[object], object]):
    payloads: list[bytes] = []
    for value in values:
        payload = _serialize(value, serializer, logical_path)
        parsed = _loads(payload, logical_path)
        if not isinstance(parsed, Mapping):
            raise _repo_error("job_shard_invalid", "JSONL 记录必须是对象。", logical_path)
        try:
            parser(parsed)
        except _EXPECTED_PARSE_ERRORS as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            raise _map_exception(exc, logical_path) from exc
        payloads.append(payload)
    # Keep the collection a single replace-style document.
    return atomic_write_bytes(path, b"".join(payloads), logical_path=logical_path)


def atomic_write_bytes(path: Path, payload: bytes, *, logical_path: str):
    _validate_parent(path, logical_path)
    try:
        if path.exists() or path.is_symlink():
            _validate_regular(path, logical_path, missing_code="job_shard_invalid")
    except JobRepositoryError:
        raise
    staging = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    replaced = False
    try:
        fd = os.open(staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(staging, path)
        replaced = True
        if os.name != "nt":
            _fsync_directory(path.parent, logical_path)
    except JobRepositoryError:
        raise
    except OSError as exc:
        code = "job_write_durability_uncertain" if replaced else "job_write_failed"
        raise _repo_error(code, "文档写入失败。", logical_path, exc) from exc
    finally:
        try:
            staging.unlink()
        except (FileNotFoundError, OSError):
            pass


def append_jsonl_record(path: Path, value, *, logical_path: str, serializer: Callable[[object], object], parser: Callable[[object], object]):
    payload = _serialize(value, serializer, logical_path)
    parsed = _loads(payload, logical_path)
    if not isinstance(parsed, Mapping):
        raise _repo_error("job_shard_invalid", "JSONL 记录必须是对象。", logical_path)
    try:
        parser(parsed)
    except _EXPECTED_PARSE_ERRORS as exc:
        raise _map_exception(exc, logical_path) from exc
    _validate_parent(path, logical_path)
    try:
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(path, flags, 0o600)
        try:
            opened = os.fstat(fd)
            current = os.lstat(path)
            if _is_link_or_reparse(current) or not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise _repo_error("job_shard_invalid", "JSONL 文件在打开期间发生变化。", logical_path)
            if opened.st_size:
                os.lseek(fd, -1, os.SEEK_END)
                tail = os.read(fd, 1)
                if tail != b"\n":
                    raise _repo_error("job_shard_invalid", "JSONL 末行不完整，不能追加。", logical_path)
            _write_all(fd, payload)
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise _repo_error("job_write_failed", "JSONL 追加失败。", logical_path, exc) from exc


def classify_schema_versions(raw_value: object, expectations: tuple[SchemaExpectation | str, ...]) -> SchemaClassification:
    found_malformed = False
    found_unsupported = False

    def values_at(pointer: str):
        if pointer in {"", "/"}:
            return True, [raw_value]
        current = [raw_value]
        for segment in pointer.strip("/").split("/"):
            nxt = []
            for value in current:
                if segment == "*":
                    if isinstance(value, list):
                        nxt.extend(value)
                    elif isinstance(value, Mapping):
                        nxt.extend(value.values())
                    else:
                        return False, []
                elif isinstance(value, Mapping) and segment in value:
                    nxt.append(value[segment])
                else:
                    return False, []
            current = nxt
        return True, current

    for expectation in expectations:
        pointer = expectation.pointer if isinstance(expectation, SchemaExpectation) else expectation
        if not isinstance(pointer, str):
            found_malformed = True
            continue
        found, selected = values_at(pointer)
        if not found:
            found_malformed = True
            continue
        for value in selected:
            if not isinstance(value, Mapping) or "schema_version" not in value or type(value.get("schema_version")) is not int:
                found_malformed = True
            elif value["schema_version"] != 1:
                found_unsupported = True
    if found_unsupported:
        return SchemaClassification.UNSUPPORTED
    if found_malformed:
        return SchemaClassification.MALFORMED
    return SchemaClassification.CURRENT
