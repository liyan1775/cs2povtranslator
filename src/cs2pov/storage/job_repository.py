from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import hashlib
import os
from pathlib import Path
import re
import shutil
import stat
import sys
from uuid import UUID, uuid4

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.job import (
    CreateJobRequest,
    FinalArtifactKind,
    JobDemoSource,
    JobCatalogEntry,
    JobInspection,
    JobIssue,
    JobManifest,
    JobPhase,
    JobRepositoryMarker,
    JobRunStatus,
    JobWriteClaim,
    RoundProgressSummary,
)
from cs2pov.domain.schema import require_path_identifier
from cs2pov.storage.demo_asset_repository import (
    DemoAssetRepositoryError,
    FileSystemDemoAssetRepository,
)
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_paths import JobPaths
from cs2pov.workspace.errors import WorkspacePathOutsideRootError
from cs2pov.workspace.paths import WorkspacePaths

from .atomic_documents import (
    atomic_write_bytes,
    atomic_write_json,
    read_strict_json,
    schema_aware_parser,
)
from .cross_process_lock import CrossProcessFileLock
from .job_claim import CLAIM_INITIALIZATION_GRACE_US, JobWriteSession


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class OpenedJob:
    marker: JobRepositoryMarker
    manifest: JobManifest
    source: JobDemoSource
    paths: JobPaths
    effective_run_status: JobRunStatus


_MARKER_PARSER = schema_aware_parser(
    JobRepositoryMarker.from_dict,
    expectations=("",),
    invalid_code="job_manifest_invalid",
)
_MANIFEST_PARSER = schema_aware_parser(
    JobManifest.from_dict,
    expectations=("",),
    invalid_code="job_manifest_invalid",
)
_SOURCE_PARSER = schema_aware_parser(
    JobDemoSource.from_dict,
    expectations=("",),
    invalid_code="job_shard_invalid",
)
_CLAIM_PARSER = JobWriteClaim.from_dict

_INITIAL_DIRECTORIES = (
    "source",
    "timeline",
    "voice",
    "models/snapshots",
    "models/invocations",
    "transcript",
    "understanding",
    "review/revisions",
    "tasks",
    "events",
    "final/timelines",
    "final/subtitles",
    "final/green_screen",
    "final/video",
)

_OPTIONAL_EXACT_FILES = (
    "timeline/demo.json",
    "timeline/rounds.json",
    "timeline/time_anchors.jsonl",
    "voice/activities.jsonl",
    "transcript/unassigned.jsonl",
    "final/timelines/draft.json",
    "final/timelines/reviewed.json",
)

_OPTIONAL_DYNAMIC_FILES = (
    ("models/snapshots", re.compile(r"snapshot_[a-z0-9][a-z0-9_-]{0,63}\.json\Z")),
    ("models/invocations", re.compile(r"task_[a-z0-9][a-z0-9_-]{0,63}\.jsonl\Z")),
    ("transcript", re.compile(r"round_[a-z0-9][a-z0-9_-]{0,63}\.jsonl\Z")),
    ("understanding", re.compile(r"round_[a-z0-9][a-z0-9_-]{0,63}\.json\Z")),
    ("tasks", re.compile(r"round_[a-z0-9][a-z0-9_-]{0,63}\.json\Z")),
)

_REVIEW_DIRECTORY = re.compile(r"review_[a-z0-9][a-z0-9_-]{0,63}\Z")
_REVIEW_ROUND_FILE = re.compile(r"round_[a-z0-9][a-z0-9_-]{0,63}\.json\Z")
_DIRECTORY_FSYNC_SUPPORTED = os.name != "nt"
_CLAIM_LOGICAL_PATH = "events/.writer_claim/claim.json"
_WRITE_LOCK_TIMEOUT_MS = 30_000
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _repository_error(
    code: str,
    message_zh: str,
    suggestion_zh: str,
    logical_path: str | None = None,
    cause: BaseException | None = None,
) -> JobRepositoryError:
    error = JobRepositoryError(code, message_zh, suggestion_zh, logical_path)
    if cause is not None:
        error.__cause__ = cause
    return error


def _is_link_or_reparse(result: os.stat_result) -> bool:
    attributes = getattr(result, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(result.st_mode) or bool(attributes & reparse)


def _canonical_timestamp(clock) -> str:
    try:
        value = clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("clock must return an aware datetime")
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    except (OverflowError, TypeError, ValueError) as exc:
        raise _repository_error(
            "job_write_failed",
            "Job 时间无效。",
            "请检查系统时间后重试。",
            "job.json",
            exc,
        ) from exc


def _claim_clock_now(clock) -> datetime:
    try:
        value = clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise TypeError("clock must return an aware datetime")
        return value.astimezone(timezone.utc)
    except (OverflowError, TypeError, ValueError) as exc:
        raise _repository_error(
            "job_claim_invalid",
            "写入权时钟无效。",
            "请检查系统时间后重新取得写入权。",
            _CLAIM_LOGICAL_PATH,
            exc,
        ) from exc


def _format_timestamp(value: datetime) -> str:
    try:
        return value.astimezone(timezone.utc).strftime(_TIMESTAMP_FORMAT)
    except (OverflowError, TypeError, ValueError) as exc:
        raise _repository_error(
            "job_claim_invalid",
            "写入权时间超出支持范围。",
            "请检查系统时间后重试。",
            _CLAIM_LOGICAL_PATH,
            exc,
        ) from exc


def _parse_timestamp(value: str) -> datetime:
    try:
        return datetime.strptime(value, _TIMESTAMP_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise _repository_error(
            "job_claim_invalid",
            "写入权时间格式无效。",
            "请重新取得写入权。",
            _CLAIM_LOGICAL_PATH,
            exc,
        ) from exc


def _duration_us(start: datetime, end: datetime) -> int:
    delta = end - start
    return delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds


def _fsync_metadata_directory(path: Path, logical_path: str) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise _repository_error(
            "job_write_durability_uncertain",
            "写入结果已经可见，但目录持久化状态不确定。",
            "请重新检查该 Job；不要回滚已经可见的结果。",
            logical_path,
            exc,
        ) from exc


def _lstat_optional(
    path: Path, *, logical_path: str | None = None
) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise _repository_error(
            "job_path_escape",
            "无法安全检查 Job 文件系统节点。",
            "请检查该 Job 的目录权限和文件系统状态。",
            logical_path,
            exc,
        ) from exc


def _fsync_jobs_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise _repository_error(
            "job_write_durability_uncertain",
            "Job 已发布，但目录持久化状态不确定。",
            "请重新检查该 Job；不要删除已发布目录。",
            None,
            exc,
        ) from exc


def _fsync_staging_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            current = os.lstat(path)
            if (
                _is_link_or_reparse(current)
                or not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise _repository_error(
                    "job_path_escape",
                    "Job staging 目录在持久化前发生变化。",
                    "请停止其他程序修改 jobs 目录后重试。",
                )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except JobRepositoryError:
        raise
    except OSError as exc:
        raise _repository_error(
            "job_write_failed",
            "Job staging 目录持久化失败。",
            "请检查磁盘和工作区权限后重试。",
            None,
            exc,
        ) from exc


def _fsync_staging_tree(staging: Path) -> None:
    if not _DIRECTORY_FSYNC_SUPPORTED:
        return
    directories = {staging}
    for relative in _INITIAL_DIRECTORIES:
        current = staging
        for part in relative.split("/"):
            current = current / part
            directories.add(current)
    # Each child directory persists its own entries first; each parent then
    # persists the child's directory entry, ending with the staging root.
    for directory in sorted(
        directories,
        key=lambda path: len(path.relative_to(staging).parts),
        reverse=True,
    ):
        _fsync_staging_directory(directory)


class FileSystemJobRepository:
    def __init__(
        self,
        paths: WorkspacePaths,
        demo_assets: FileSystemDemoAssetRepository,
        *,
        clock=utc_now,
        staging_id_factory=uuid4,
        run_id_factory=uuid4,
        process_id_supplier=os.getpid,
        lock_factory=CrossProcessFileLock,
    ) -> None:
        if not isinstance(paths, WorkspacePaths):
            raise TypeError("paths 必须是 WorkspacePaths。")
        if not isinstance(demo_assets, FileSystemDemoAssetRepository):
            raise TypeError("demo_assets 必须是 FileSystemDemoAssetRepository。")
        if demo_assets.paths.root != paths.root:
            raise ValueError("demo_assets 必须属于同一工作区。")
        if not all(
            callable(value)
            for value in (
                clock,
                staging_id_factory,
                run_id_factory,
                process_id_supplier,
            )
        ):
            raise TypeError("仓储依赖必须可调用。")
        if not hasattr(lock_factory, "bootstrap_for_write") or not hasattr(
            lock_factory, "open_existing"
        ):
            raise TypeError("lock_factory 不符合仓储锁接口。")
        self.paths = paths
        self.demo_assets = demo_assets
        self.clock = clock
        self.staging_id_factory = staging_id_factory
        self.run_id_factory = run_id_factory
        self.process_id_supplier = process_id_supplier
        self.lock_factory = lock_factory

    def create_job(self, request: CreateJobRequest) -> OpenedJob:
        if not isinstance(request, CreateJobRequest):
            raise TypeError("request 必须是 CreateJobRequest。")

        # Source health is deliberately established before any Job staging is
        # created. inspect_asset is read-only; resolve_asset may rebuild cache
        # and therefore is not part of Job creation.
        self._validate_source(request.source)
        final_paths = self._paths_for(request.job_id)
        timestamp = _canonical_timestamp(self.clock)
        marker = JobRepositoryMarker(request.job_id)
        manifest = JobManifest(
            request.job_id,
            request.display_name,
            timestamp,
            timestamp,
            request.source.asset_id,
            request.source.display_name,
            None,
            None,
            JobPhase.CREATED,
            JobRunStatus.PENDING,
            RoundProgressSummary(0, 0, 0, 0),
            (),
            None,
            (),
        )

        self._ensure_jobs_root_for_write(request.job_id)
        if _lstat_optional(final_paths.job_dir) is not None:
            raise self._already_exists(request.job_id)

        staging = self._new_staging_path(request.job_id)
        staging_identity: tuple[int, int] | None = None
        published = False
        try:
            try:
                os.mkdir(staging, 0o700)
            except FileExistsError as exc:
                raise _repository_error(
                    "job_write_failed",
                    "无法创建唯一 Job staging 目录。",
                    "请重试创建 Job。",
                    None,
                    exc,
                ) from exc
            staging_stat = os.lstat(staging)
            if _is_link_or_reparse(staging_stat) or not stat.S_ISDIR(staging_stat.st_mode):
                raise _repository_error(
                    "job_path_escape",
                    "Job staging 目录不安全。",
                    "请检查工作区 jobs 目录。",
                )
            staging_identity = (staging_stat.st_dev, staging_stat.st_ino)

            self._prepare_staging(staging, marker, manifest, request.source)
            lock_path = self.paths.jobs_dir / ".repository.lock"
            with self.lock_factory.bootstrap_for_write(lock_path, timeout_ms=30_000):
                self._validate_jobs_root()
                if _lstat_optional(final_paths.job_dir) is not None:
                    raise self._already_exists(request.job_id)
                try:
                    os.rename(staging, final_paths.job_dir)
                except OSError as exc:
                    if exc.errno in {
                        errno.EEXIST,
                        errno.ENOTEMPTY,
                        getattr(errno, "EACCES", 13),
                    } and _lstat_optional(final_paths.job_dir) is not None:
                        raise self._already_exists(request.job_id, exc) from exc
                    raise _repository_error(
                        "job_write_failed",
                        "Job 最终发布失败。",
                        "请检查工作区权限和磁盘空间后重试。",
                        None,
                        exc,
                    ) from exc
                published = True

            _fsync_jobs_directory(self.paths.jobs_dir)
            return self.load_job(request.job_id)
        finally:
            if not published and staging_identity is not None:
                self._cleanup_owned_staging(staging, staging_identity, sys.exc_info()[1])

    def load_job(self, job_id: str) -> OpenedJob:
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        # Classify identity/source failures before consulting the v1 write
        # lock, preserving the repository boundary for markerless legacy data.
        self._read_job_core(paths, job_id)
        self._assert_safe_regular(
            paths.write_lock,
            logical_path="events/.write.lock",
            missing_code="job_shard_missing",
            invalid_code="job_shard_invalid",
        )
        try:
            lock_context = self.lock_factory.open_existing(
                paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
            )
            with lock_context as locked_file:
                self._assert_read_lock_locked(paths, locked_file)
                opened = self._load_job_durable(
                    job_id, write_lock_already_held=True
                )
                effective, _ = self._project_claim_state_locked(
                    paths, opened.manifest.run_status
                )
                if effective is None:
                    raise AssertionError("manifest status projection cannot be None")
                return OpenedJob(
                    opened.marker,
                    opened.manifest,
                    opened.source,
                    opened.paths,
                    effective,
                )
        except JobRepositoryError as exc:
            if exc.code != "job_write_failed":
                raise
            raise _repository_error(
                "job_shard_invalid",
                "无法安全读取 Job 写锁。",
                "请检查该 Job；读取操作不会自动修复它。",
                "events/.write.lock",
                exc,
            ) from exc

    def _load_job_durable(
        self, job_id: str, *, write_lock_already_held: bool = False
    ) -> OpenedJob:
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)

        marker, manifest, source = self._read_job_core(paths, job_id)
        issues = self._collect_integrity_issues(
            paths,
            manifest,
            source,
            write_lock_already_held=write_lock_already_held,
        )
        if issues:
            raise self._error_from_issue(issues[0])
        return OpenedJob(marker, manifest, source, paths, manifest.run_status)

    def _read_job_core(
        self, paths: JobPaths, job_id: str
    ) -> tuple[JobRepositoryMarker, JobManifest, JobDemoSource]:

        marker = self._read_identity_document(
            paths.repository_marker,
            logical_path="repository.json",
            parser=_MARKER_PARSER,
        )
        manifest = self._read_identity_document(
            paths.manifest,
            logical_path="job.json",
            parser=_MANIFEST_PARSER,
        )
        self._assert_safe_regular(
            paths.demo_source,
            logical_path="source/demo_ref.json",
            missing_code="job_shard_missing",
            invalid_code="job_shard_invalid",
        )
        source = read_strict_json(
            paths.demo_source,
            logical_path="source/demo_ref.json",
            parser=_SOURCE_PARSER,
        )

        if marker.job_id != job_id or manifest.job_id != job_id:
            raise _repository_error(
                "job_manifest_invalid",
                "Job 目录、标记和清单身份不一致。",
                "请在管理界面检查该 Job。",
                "job.json",
            )
        if (
            manifest.demo_asset_id != source.asset_id
            or manifest.demo_display_name != source.display_name
        ):
            raise _repository_error(
                "job_shard_invalid",
                "Job 清单与 Demo 来源身份不一致。",
                "请检查 Demo 来源引用。",
                "source/demo_ref.json",
            )
        return marker, manifest, source

    def acquire_write(self, job_id: str, *, lease_us: int) -> JobWriteSession:
        if type(lease_us) is not int or lease_us <= 0:
            raise _repository_error(
                "job_claim_invalid",
                "写入权租约时长无效。",
                "请使用正整数微秒作为租约时长。",
                _CLAIM_LOGICAL_PATH,
            )
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        run_id = self._new_run_id()
        try:
            process_id = self.process_id_supplier()
        except (OSError, TypeError, ValueError) as exc:
            raise _repository_error(
                "job_claim_invalid",
                "无法取得有效的进程标识。",
                "请重启程序后重试。",
                _CLAIM_LOGICAL_PATH,
                exc,
            ) from exc
        if type(process_id) is not int or process_id < 0:
            raise _repository_error(
                "job_claim_invalid",
                "进程标识无效。",
                "请重启程序后重试。",
                _CLAIM_LOGICAL_PATH,
            )
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            # The complete validation happens after waiting for the OS lock,
            # so it cannot race a cooperating writer's publication.
            self._load_job_durable(job_id, write_lock_already_held=True)
            now = _claim_clock_now(self.clock)
            try:
                expires = now + timedelta(microseconds=lease_us)
            except OverflowError as exc:
                raise _repository_error(
                    "job_claim_invalid",
                    "写入权租约超出支持范围。",
                    "请缩短租约后重试。",
                    _CLAIM_LOGICAL_PATH,
                    exc,
                ) from exc
            claim = JobWriteClaim(
                job_id,
                run_id,
                process_id,
                _format_timestamp(now),
                _format_timestamp(now),
                _format_timestamp(expires),
            )
            try:
                active = self._read_active_claim_locked(paths)
            except JobRepositoryError as exc:
                if exc.code != "job_claim_invalid":
                    raise
                if not self._claim_initialization_grace_elapsed(paths, now):
                    raise
                self._archive_active_claim_locked(paths)
            else:
                if active is not None:
                    heartbeat = _parse_timestamp(active.heartbeat_at)
                    expiry = _parse_timestamp(active.lease_expires_at)
                    if now < heartbeat:
                        raise _repository_error(
                            "job_claim_invalid",
                            "系统时间早于当前写入权心跳。",
                            "请校准系统时间后重试；不要强制接管。",
                            _CLAIM_LOGICAL_PATH,
                        )
                    if now < expiry:
                        raise _repository_error(
                            "job_write_busy",
                            "这个 Job 正由另一个运行会话写入。",
                            "请等待当前操作完成，或在租约过期后重试。",
                            _CLAIM_LOGICAL_PATH,
                        )
                    self._archive_active_claim_locked(paths)
            self._publish_claim_locked(paths, claim)
        return JobWriteSession(self, job_id, claim)

    def replace_manifest(
        self,
        job_id: str,
        expected_fingerprint: str,
        new_manifest: JobManifest,
        claim: JobWriteClaim,
    ) -> OpenedJob:
        if not isinstance(expected_fingerprint, str):
            raise TypeError("expected_fingerprint must be a string")
        if not isinstance(new_manifest, JobManifest):
            raise TypeError("new_manifest must be a JobManifest")
        if not isinstance(claim, JobWriteClaim):
            raise TypeError("claim must be a JobWriteClaim")
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            return self._replace_manifest_locked(
                locked_file,
                job_id,
                expected_fingerprint,
                new_manifest,
                claim,
            )

    def _replace_manifest_locked(
        self,
        locked_file,
        job_id: str,
        expected_fingerprint: str,
        new_manifest: JobManifest,
        claim: JobWriteClaim,
    ) -> OpenedJob:
        paths = self._paths_for(job_id)
        self._assert_write_lock_locked(paths, locked_file)
        self._verify_claim_locked(paths, claim)
        opened = self._load_job_durable(job_id, write_lock_already_held=True)
        current = opened.manifest
        if current.content_fingerprint() != expected_fingerprint:
            raise _repository_error(
                "job_manifest_conflict",
                "Job 清单已经被其他操作更新。",
                "请重新打开 Job，并基于最新状态重试。",
                "job.json",
            )
        immutable_current = (
            current.job_id,
            current.created_at,
            current.demo_asset_id,
            current.demo_display_name,
        )
        immutable_new = (
            new_manifest.job_id,
            new_manifest.created_at,
            new_manifest.demo_asset_id,
            new_manifest.demo_display_name,
        )
        if immutable_new != immutable_current or new_manifest.job_id != job_id:
            raise _repository_error(
                "job_manifest_conflict",
                "Job 或 Demo 的持久身份不能被修改。",
                "请保留原始身份，只更新可变字段。",
                "job.json",
            )
        if new_manifest.updated_at <= current.updated_at:
            raise _repository_error(
                "job_manifest_conflict",
                "Job 更新时间必须严格向前推进。",
                "请使用晚于当前清单的 UTC 时间。",
                "job.json",
            )
        self._validate_manifest_references(paths, new_manifest, opened.source)
        atomic_write_json(
            paths.manifest,
            new_manifest,
            logical_path="job.json",
            serializer=lambda value: value.to_dict(),
            parser=_MANIFEST_PARSER,
        )
        persisted = self._read_identity_document(
            paths.manifest,
            logical_path="job.json",
            parser=_MANIFEST_PARSER,
        )
        if persisted != new_manifest:
            raise _repository_error(
                "job_write_failed",
                "Job 清单写入后的回读结果不一致。",
                "请停止其他程序修改该 Job 后重试。",
                "job.json",
            )
        return OpenedJob(
            opened.marker,
            persisted,
            opened.source,
            paths,
            persisted.run_status,
        )

    def _heartbeat_write(
        self, job_id: str, claim: JobWriteClaim
    ) -> JobWriteClaim:
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            active, now = self._verify_claim_locked(paths, claim)
            lease_us = _duration_us(
                _parse_timestamp(active.heartbeat_at),
                _parse_timestamp(active.lease_expires_at),
            )
            if lease_us <= 0:
                raise _repository_error(
                    "job_claim_invalid",
                    "当前写入权的租约时长无效。",
                    "请重新取得写入权。",
                    _CLAIM_LOGICAL_PATH,
                )
            try:
                expires = now + timedelta(microseconds=lease_us)
            except OverflowError as exc:
                raise _repository_error(
                    "job_claim_invalid",
                    "写入权租约超出支持范围。",
                    "请重新取得较短的写入权。",
                    _CLAIM_LOGICAL_PATH,
                    exc,
                ) from exc
            refreshed = JobWriteClaim(
                active.job_id,
                active.run_id,
                active.process_id,
                active.acquired_at,
                _format_timestamp(now),
                _format_timestamp(expires),
            )
            atomic_write_json(
                paths.writer_claim,
                refreshed,
                logical_path=_CLAIM_LOGICAL_PATH,
                serializer=lambda value: value.to_dict(),
                parser=_CLAIM_PARSER,
            )
            return refreshed

    def _release_write(self, job_id: str, claim: JobWriteClaim) -> None:
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            released = self._move_active_claim_locked(paths, "released")
            self._remove_released_claim_locked(paths, released)

    def _remove_released_claim_locked(
        self, paths: JobPaths, released: Path
    ) -> None:
        try:
            state = os.lstat(released)
            children = tuple(os.scandir(released))
            safe_directory = (
                released.parent == paths.events_dir
                and released.name.startswith(".writer_claim.released-")
                and not _is_link_or_reparse(state)
                and stat.S_ISDIR(state.st_mode)
            )
            if not safe_directory or [child.name for child in children] != ["claim.json"]:
                raise ValueError("released claim directory has unexpected contents")
            claim_state = children[0].stat(follow_symlinks=False)
            if _is_link_or_reparse(claim_state) or not stat.S_ISREG(claim_state.st_mode):
                raise ValueError("released claim document is not a regular file")
            os.unlink(released / "claim.json")
            os.rmdir(released)
            _fsync_metadata_directory(paths.events_dir, _CLAIM_LOGICAL_PATH)
        except JobRepositoryError:
            raise
        except (OSError, ValueError) as exc:
            raise _repository_error(
                "job_write_failed",
                "写入权已经停止激活，但诊断目录清理失败。",
                "请检查 events 中的隐藏目录。",
                _CLAIM_LOGICAL_PATH,
                exc,
            ) from exc

    def _new_run_id(self) -> str:
        try:
            value = self.run_id_factory()
        except (OSError, TypeError, ValueError) as exc:
            raise _repository_error(
                "job_claim_invalid",
                "无法生成写入会话标识。",
                "请重启程序后重试。",
                _CLAIM_LOGICAL_PATH,
                exc,
            ) from exc
        if not isinstance(value, UUID):
            raise _repository_error(
                "job_claim_invalid",
                "写入会话标识生成器返回了无效值。",
                "请修复运行配置后重试。",
                _CLAIM_LOGICAL_PATH,
            )
        return f"run-{value.hex}"

    def _new_claim_aux_path(self, paths: JobPaths, purpose: str) -> Path:
        for _ in range(16):
            try:
                value = self.staging_id_factory()
            except (OSError, TypeError, ValueError) as exc:
                raise _repository_error(
                    "job_write_failed",
                    "无法生成写入权临时标识。",
                    "请重试。",
                    _CLAIM_LOGICAL_PATH,
                    exc,
                ) from exc
            if not isinstance(value, UUID):
                raise _repository_error(
                    "job_write_failed",
                    "写入权临时标识无效。",
                    "请修复 staging ID 配置。",
                    _CLAIM_LOGICAL_PATH,
                )
            candidate = paths.events_dir / f".writer_claim.{purpose}-{value.hex}"
            if _lstat_optional(candidate, logical_path=_CLAIM_LOGICAL_PATH) is None:
                return candidate
        raise _repository_error(
            "job_write_failed",
            "无法分配唯一的写入权临时目录。",
            "请清理冲突的隐藏目录后重试。",
            _CLAIM_LOGICAL_PATH,
        )

    def _assert_write_lock_locked(self, paths: JobPaths, locked_file) -> None:
        try:
            handle = locked_file.file
            if handle is None:
                raise ValueError("lock context has no open file")
            opened = os.fstat(handle.fileno())
            current = os.lstat(paths.write_lock)
            position = handle.tell()
            handle.seek(0)
            payload = handle.read(1)
            handle.seek(position)
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            raise _repository_error(
                "job_write_interrupted",
                "Job 写锁在临界区内失效。",
                "请重新取得写入权后重试。",
                "events/.write.lock",
                exc,
            ) from exc
        if (
            _is_link_or_reparse(current)
            or not stat.S_ISREG(opened.st_mode)
            or opened.st_size != 1
            or payload != b"0"
            or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise _repository_error(
                "job_write_interrupted",
                "Job 写锁身份在临界区内发生变化。",
                "请停止其他程序修改该 Job 后重试。",
                "events/.write.lock",
            )

    def _assert_read_lock_locked(self, paths: JobPaths, locked_file) -> None:
        try:
            self._assert_write_lock_locked(paths, locked_file)
        except JobRepositoryError as exc:
            raise _repository_error(
                "job_shard_invalid",
                "Job 写锁文件无效。",
                "请检查该 Job；读取操作不会自动修复它。",
                "events/.write.lock",
                exc,
            ) from exc

    def _read_active_claim_locked(self, paths: JobPaths) -> JobWriteClaim | None:
        state = _lstat_optional(paths.writer_claim_dir, logical_path=_CLAIM_LOGICAL_PATH)
        if state is None:
            return None
        if _is_link_or_reparse(state) or not stat.S_ISDIR(state.st_mode):
            raise _repository_error(
                "job_path_escape",
                "写入权目录不是安全的普通目录。",
                "请移除链接或恢复该 Job。",
                _CLAIM_LOGICAL_PATH,
            )
        try:
            self._assert_safe_regular(
                paths.writer_claim,
                logical_path=_CLAIM_LOGICAL_PATH,
                missing_code="job_claim_invalid",
                invalid_code="job_claim_invalid",
            )
            claim = read_strict_json(
                paths.writer_claim,
                logical_path=_CLAIM_LOGICAL_PATH,
                parser=_CLAIM_PARSER,
            )
        except JobRepositoryError as exc:
            if exc.code in {"job_schema_unsupported", "job_path_escape", "job_claim_invalid"}:
                raise
            raise _repository_error(
                "job_claim_invalid",
                "写入权文档无效或不完整。",
                "请等待初始化宽限期后重试接管。",
                _CLAIM_LOGICAL_PATH,
                exc,
            ) from exc
        if claim.job_id != paths.job_id:
            raise _repository_error(
                "job_claim_invalid",
                "写入权文档引用了另一个 Job。",
                "请等待初始化宽限期后重试接管。",
                _CLAIM_LOGICAL_PATH,
            )
        return claim

    def _verify_claim_locked(
        self, paths: JobPaths, claim: JobWriteClaim
    ) -> tuple[JobWriteClaim, datetime]:
        if (
            not isinstance(claim, JobWriteClaim)
            or claim.job_id != paths.job_id
        ):
            raise _repository_error(
                "job_write_interrupted",
                "提供的写入权不属于这个 Job。",
                "请重新取得写入权后再继续。",
                _CLAIM_LOGICAL_PATH,
            )
        active = self._read_active_claim_locked(paths)
        if active is None or active.run_id != claim.run_id:
            raise _repository_error(
                "job_write_interrupted",
                "写入权已释放或已由新的运行会话接管。",
                "请停止旧任务，并从最新 Job 状态重新继续。",
                _CLAIM_LOGICAL_PATH,
            )
        now = _claim_clock_now(self.clock)
        heartbeat = _parse_timestamp(active.heartbeat_at)
        if now < heartbeat:
            raise _repository_error(
                "job_claim_invalid",
                "系统时间早于当前写入权心跳。",
                "请校准系统时间后重试。",
                _CLAIM_LOGICAL_PATH,
            )
        if now >= _parse_timestamp(active.lease_expires_at):
            raise _repository_error(
                "job_write_interrupted",
                "写入权租约已经过期。",
                "请重新取得写入权后再继续。",
                _CLAIM_LOGICAL_PATH,
            )
        return active, now

    def _claim_initialization_grace_elapsed(
        self, paths: JobPaths, now: datetime
    ) -> bool:
        try:
            state = os.lstat(paths.writer_claim_dir)
        except OSError as exc:
            raise _repository_error(
                "job_claim_invalid",
                "无法检查不完整写入权目录的年龄。",
                "请检查该 Job 后重试。",
                _CLAIM_LOGICAL_PATH,
                exc,
            ) from exc
        if _is_link_or_reparse(state) or not stat.S_ISDIR(state.st_mode):
            raise _repository_error(
                "job_path_escape",
                "写入权目录不是安全的普通目录。",
                "请移除链接或恢复该 Job。",
                _CLAIM_LOGICAL_PATH,
            )
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        now_us = _duration_us(epoch, now)
        modified_us = state.st_mtime_ns // 1_000
        age_us = now_us - modified_us
        if age_us < 0:
            raise _repository_error(
                "job_claim_invalid",
                "系统时间早于写入权目录时间。",
                "请校准系统时间；不要强制接管。",
                _CLAIM_LOGICAL_PATH,
            )
        return age_us >= CLAIM_INITIALIZATION_GRACE_US

    def _move_active_claim_locked(self, paths: JobPaths, purpose: str) -> Path:
        state = _lstat_optional(paths.writer_claim_dir, logical_path=_CLAIM_LOGICAL_PATH)
        if state is None or _is_link_or_reparse(state) or not stat.S_ISDIR(state.st_mode):
            raise _repository_error(
                "job_write_interrupted",
                "活动写入权目录在操作期间发生变化。",
                "请重新检查 Job 后重试。",
                _CLAIM_LOGICAL_PATH,
            )
        destination = self._new_claim_aux_path(paths, purpose)
        try:
            os.rename(paths.writer_claim_dir, destination)
        except OSError as exc:
            raise _repository_error(
                "job_write_failed",
                "无法移动旧写入权目录。",
                "请检查 events 目录后重试。",
                _CLAIM_LOGICAL_PATH,
                exc,
            ) from exc
        _fsync_metadata_directory(paths.events_dir, _CLAIM_LOGICAL_PATH)
        return destination

    def _archive_active_claim_locked(self, paths: JobPaths) -> Path:
        return self._move_active_claim_locked(paths, "stale")

    def _publish_claim_locked(self, paths: JobPaths, claim: JobWriteClaim) -> None:
        staging = self._new_claim_aux_path(paths, "staging")
        identity: tuple[int, int] | None = None
        published = False
        try:
            os.mkdir(staging, 0o700)
            created = os.lstat(staging)
            if _is_link_or_reparse(created) or not stat.S_ISDIR(created.st_mode):
                raise _repository_error(
                    "job_path_escape",
                    "写入权 staging 目录不安全。",
                    "请检查 events 目录后重试。",
                    _CLAIM_LOGICAL_PATH,
                )
            identity = (created.st_dev, created.st_ino)
            staged_claim = staging / "claim.json"
            atomic_write_json(
                staged_claim,
                claim,
                logical_path=_CLAIM_LOGICAL_PATH,
                serializer=lambda value: value.to_dict(),
                parser=_CLAIM_PARSER,
            )
            if read_strict_json(
                staged_claim,
                logical_path=_CLAIM_LOGICAL_PATH,
                parser=_CLAIM_PARSER,
            ) != claim:
                raise _repository_error(
                    "job_write_failed",
                    "写入权 staging 回读不一致。",
                    "请重试取得写入权。",
                    _CLAIM_LOGICAL_PATH,
                )
            if _DIRECTORY_FSYNC_SUPPORTED:
                _fsync_staging_directory(staging)
            if _lstat_optional(
                paths.writer_claim_dir, logical_path=_CLAIM_LOGICAL_PATH
            ) is not None:
                raise _repository_error(
                    "job_write_busy",
                    "活动写入权在发布期间出现。",
                    "请稍后重试。",
                    _CLAIM_LOGICAL_PATH,
                )
            try:
                os.rename(staging, paths.writer_claim_dir)
            except FileExistsError as exc:
                raise _repository_error(
                    "job_write_busy",
                    "活动写入权在发布期间出现。",
                    "请稍后重试。",
                    _CLAIM_LOGICAL_PATH,
                    exc,
                ) from exc
            published = True
            _fsync_metadata_directory(paths.events_dir, _CLAIM_LOGICAL_PATH)
        except JobRepositoryError:
            raise
        except OSError as exc:
            raise _repository_error(
                "job_write_failed",
                "无法发布写入权。",
                "请检查磁盘和工作区权限后重试。",
                _CLAIM_LOGICAL_PATH,
                exc,
            ) from exc
        finally:
            if not published and identity is not None:
                self._cleanup_claim_staging(staging, identity, sys.exc_info()[1])

    def _cleanup_claim_staging(
        self,
        staging: Path,
        identity: tuple[int, int],
        primary: BaseException | None,
    ) -> None:
        try:
            current = os.lstat(staging)
        except FileNotFoundError:
            return
        except OSError as exc:
            if primary is not None:
                primary.add_note(f"claim staging cleanup check failed: {type(exc).__name__}")
                return
            raise _repository_error(
                "job_write_failed",
                "无法检查写入权 staging。",
                "请检查 events 中的隐藏目录。",
                _CLAIM_LOGICAL_PATH,
                exc,
            ) from exc
        safe = (
            staging.parent.name == "events"
            and staging.name.startswith(".writer_claim.staging-")
            and not _is_link_or_reparse(current)
            and stat.S_ISDIR(current.st_mode)
            and (current.st_dev, current.st_ino) == identity
        )
        if not safe:
            if primary is not None:
                primary.add_note("claim staging cleanup skipped because ownership changed")
                return
            raise _repository_error(
                "job_write_failed",
                "写入权 staging 所有权已变化，未执行清理。",
                "请检查 events 中的隐藏目录。",
                _CLAIM_LOGICAL_PATH,
            )
        try:
            shutil.rmtree(staging)
        except OSError as exc:
            if primary is not None:
                primary.add_note(f"claim staging cleanup failed: {type(exc).__name__}")
                return
            raise _repository_error(
                "job_write_failed",
                "无法清理写入权 staging。",
                "请检查 events 中的隐藏目录。",
                _CLAIM_LOGICAL_PATH,
                exc,
            ) from exc

    def _validate_manifest_references(
        self,
        paths: JobPaths,
        manifest: JobManifest,
        source: JobDemoSource,
    ) -> None:
        issues = list(
            self._collect_integrity_issues(
                paths,
                manifest,
                source,
                write_lock_already_held=True,
            )
        )
        for snapshot_id in manifest.configuration_snapshot_ids:
            try:
                self._assert_safe_regular(
                    paths.snapshot(snapshot_id),
                    logical_path=f"models/snapshots/snapshot_{snapshot_id}.json",
                    missing_code="job_shard_missing",
                    invalid_code="job_shard_invalid",
                )
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
        if manifest.active_review_id is not None:
            review_id = manifest.active_review_id
            revision_dir = paths.review_revision(review_id)
            logical_dir = f"review/revisions/review_{review_id}"
            try:
                state = os.lstat(revision_dir)
                if _is_link_or_reparse(state) or not stat.S_ISDIR(state.st_mode):
                    raise _repository_error(
                        "job_shard_invalid",
                        "活动复核版本目录无效。",
                        "请先完整发布复核版本，再更新 Job 清单。",
                        logical_dir,
                    )
                self._assert_safe_regular(
                    paths.review_revision_manifest(review_id),
                    logical_path=f"{logical_dir}/revision.json",
                    missing_code="job_shard_missing",
                    invalid_code="job_shard_invalid",
                )
            except FileNotFoundError as exc:
                self._append_issue(
                    issues,
                    _repository_error(
                        "job_shard_missing",
                        "活动复核版本不存在。",
                        "请先完整发布复核版本，再更新 Job 清单。",
                        logical_dir,
                        exc,
                    ).to_issue(),
                )
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
            except OSError as exc:
                self._append_issue(
                    issues,
                    _repository_error(
                        "job_shard_invalid",
                        "无法检查活动复核版本。",
                        "请检查该 Job。",
                        logical_dir,
                        exc,
                    ).to_issue(),
                )
        if issues:
            raise self._error_from_issue(issues[0])

    def _project_claim_state(
        self,
        paths: JobPaths,
        durable_status: JobRunStatus | None,
    ) -> tuple[JobRunStatus | None, JobIssue | None]:
        self._assert_safe_regular(
            paths.write_lock,
            logical_path="events/.write.lock",
            missing_code="job_shard_missing",
            invalid_code="job_shard_invalid",
        )
        try:
            lock_context = self.lock_factory.open_existing(
                paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
            )
            with lock_context as locked_file:
                self._assert_read_lock_locked(paths, locked_file)
                return self._project_claim_state_locked(paths, durable_status)
        except JobRepositoryError as exc:
            if exc.code != "job_write_failed":
                raise
            raise _repository_error(
                "job_shard_invalid",
                "无法安全读取 Job 写锁。",
                "请检查该 Job；读取操作不会自动修复它。",
                "events/.write.lock",
                exc,
            ) from exc

    def _project_claim_state_locked(
        self,
        paths: JobPaths,
        durable_status: JobRunStatus | None,
    ) -> tuple[JobRunStatus | None, JobIssue | None]:
        active = self._read_active_claim_locked(paths)
        if active is None:
            if durable_status is JobRunStatus.RUNNING:
                return (
                    JobRunStatus.INTERRUPTED,
                    self._interrupted_projection_issue(),
                )
            return durable_status, None
        now = _claim_clock_now(self.clock)
        heartbeat = _parse_timestamp(active.heartbeat_at)
        if now < heartbeat:
            raise _repository_error(
                "job_claim_invalid",
                "系统时间早于当前写入权心跳。",
                "请校准系统时间后重新检查 Job。",
                _CLAIM_LOGICAL_PATH,
            )
        if (
            durable_status is JobRunStatus.RUNNING
            and now >= _parse_timestamp(active.lease_expires_at)
        ):
            return (
                JobRunStatus.INTERRUPTED,
                self._interrupted_projection_issue(),
            )
        return durable_status, None

    def _interrupted_projection_issue(self) -> JobIssue:
        return JobIssue(
            "job_write_interrupted",
            "warning",
            "上次运行没有可用的写入权，当前按已中断显示。",
            "如需继续，请明确执行继续或重试；查看操作不会改写磁盘。",
            _CLAIM_LOGICAL_PATH,
        )

    def list_jobs(self) -> tuple[JobCatalogEntry, ...]:
        root_state = _lstat_optional(self.paths.jobs_dir)
        if root_state is None:
            return ()
        if _is_link_or_reparse(root_state) or not stat.S_ISDIR(root_state.st_mode):
            raise _repository_error(
                "job_path_escape",
                "当前工作区的 jobs 路径不是安全目录。",
                "请移除链接或重新选择工作区。",
            )

        entries: list[JobCatalogEntry] = []
        try:
            children = tuple(os.scandir(self.paths.jobs_dir))
        except OSError as exc:
            raise _repository_error(
                "job_path_escape",
                "无法安全读取当前工作区的 Job 列表。",
                "请检查工作区目录权限。",
                None,
                exc,
            ) from exc
        for child in children:
            discovery_id = child.name
            if discovery_id.startswith("."):
                continue
            try:
                require_path_identifier(discovery_id, "discovery_id")
            except DomainSchemaError:
                continue
            try:
                child_state = child.stat(follow_symlinks=False)
            except OSError as exc:
                entries.append(
                    self._entry_from_parts(
                        discovery_id,
                        None,
                        (
                            _repository_error(
                                "job_path_escape",
                                "无法安全检查候选 Job 目录。",
                                "请检查该 Job 的目录权限和文件系统状态。",
                                None,
                                exc,
                            ).to_issue(),
                        ),
                    )
                )
                continue
            if _is_link_or_reparse(child_state):
                entries.append(
                    self._entry_from_parts(
                        discovery_id,
                        None,
                        (
                            JobIssue(
                                "job_path_escape",
                                "error",
                                "Job 目录是链接或重解析点，未读取其内容。",
                                "请移除链接，并从可信工作区恢复 Job。",
                                None,
                            ),
                        ),
                    )
                )
                continue
            if not stat.S_ISDIR(child_state.st_mode):
                continue

            marker_path = Path(child.path) / "repository.json"
            try:
                os.lstat(marker_path)
            except FileNotFoundError:
                # Markerless directories, including v0.x manifest.json-only
                # outputs, are outside this current-version repository.
                continue
            except OSError as exc:
                entries.append(
                    self._entry_from_parts(
                        discovery_id,
                        None,
                        (
                            _repository_error(
                                "job_manifest_invalid",
                                "无法检查当前 Job 的仓储标记。",
                                "请检查该 Job 的 repository.json 和目录权限。",
                                "repository.json",
                                exc,
                            ).to_issue(),
                        ),
                    )
                )
                continue
            try:
                entries.append(self.inspect_job(discovery_id).entry)
            except JobRepositoryError as exc:
                # A sibling may disappear or become unreadable after discovery;
                # catalog isolation still returns the other Jobs.
                entries.append(
                    self._entry_from_parts(discovery_id, None, (exc.to_issue(),))
                )
            except OSError as exc:
                entries.append(
                    self._entry_from_parts(
                        discovery_id,
                        None,
                        (
                            _repository_error(
                                "job_path_escape",
                                "检查 Job 时发生文件系统错误。",
                                "请检查该 Job 的目录权限和文件系统状态。",
                                None,
                                exc,
                            ).to_issue(),
                        ),
                    )
                )

        valid_time = [entry for entry in entries if entry.updated_at is not None]
        invalid_time = [entry for entry in entries if entry.updated_at is None]
        # Canonical timestamps are fixed-width UTC strings, so lexical order is
        # exact down to the microsecond and avoids lossy float timestamps.
        valid_time.sort(key=lambda entry: entry.job_id or entry.discovery_id)
        valid_time.sort(key=lambda entry: entry.updated_at or "", reverse=True)
        invalid_time.sort(key=lambda entry: entry.discovery_id)
        return tuple((*valid_time, *invalid_time))

    def inspect_job(self, job_id: str) -> JobInspection:
        try:
            require_path_identifier(job_id, "job_id")
        except DomainSchemaError as exc:
            raise _repository_error(
                "job_path_escape",
                "Job ID 不能安全用作目录名。",
                "请从 Job 列表重新选择。",
                None,
                exc,
            ) from exc

        try:
            paths = self._paths_for(job_id)
            self._validate_existing_job_dir(paths)
        except JobRepositoryError as exc:
            if exc.code != "job_path_escape":
                raise
            entry = self._entry_from_parts(job_id, None, (exc.to_issue(),))
            return JobInspection(entry, None, None, None, (), False)

        issues: list[JobIssue] = []
        marker = self._inspect_document(
            paths.repository_marker,
            logical_path="repository.json",
            parser=_MARKER_PARSER,
            missing_code="job_manifest_invalid",
            invalid_code="job_manifest_invalid",
            issues=issues,
        )
        manifest = self._inspect_document(
            paths.manifest,
            logical_path="job.json",
            parser=_MANIFEST_PARSER,
            missing_code="job_manifest_invalid",
            invalid_code="job_manifest_invalid",
            issues=issues,
        )
        source = self._inspect_document(
            paths.demo_source,
            logical_path="source/demo_ref.json",
            parser=_SOURCE_PARSER,
            missing_code="job_shard_missing",
            invalid_code="job_shard_invalid",
            issues=issues,
        )

        if marker is not None and marker.job_id != job_id:
            self._append_issue(
                issues,
                JobIssue(
                    "job_manifest_invalid",
                    "error",
                    "仓储标记与目录中的 Job ID 不一致。",
                    "请检查 repository.json；不要重命名 Job 目录。",
                    "repository.json",
                ),
            )
        if manifest is not None and manifest.job_id != job_id:
            self._append_issue(
                issues,
                JobIssue(
                    "job_manifest_invalid",
                    "error",
                    "Job 清单身份与目录名不一致。",
                    "请检查 job.json；不要重命名 Job 目录。",
                    "job.json",
                ),
            )
        if (
            marker is not None
            and manifest is not None
            and marker.job_id != manifest.job_id
        ):
            self._append_issue(
                issues,
                JobIssue(
                    "job_manifest_invalid",
                    "error",
                    "仓储标记与 Job 清单身份不一致。",
                    "请检查 repository.json 和 job.json。",
                    "job.json",
                ),
            )
        if manifest is not None and source is not None and (
            manifest.demo_asset_id != source.asset_id
            or manifest.demo_display_name != source.display_name
        ):
            self._append_issue(
                issues,
                JobIssue(
                    "job_shard_invalid",
                    "error",
                    "Job 清单与 Demo 来源身份不一致。",
                    "请检查 source/demo_ref.json。",
                    "source/demo_ref.json",
                ),
            )

        if manifest is not None:
            for issue in self._collect_integrity_issues(
                paths,
                manifest,
                source,
                write_lock_already_held=True,
            ):
                self._append_issue(issues, issue)
        else:
            for issue in self._inspect_static_layout(
                paths, write_lock_already_held=True
            ):
                self._append_issue(issues, issue)

        effective_run_status = None if manifest is None else manifest.run_status
        core_is_healthy = (
            marker is not None
            and manifest is not None
            and source is not None
            and not any(issue.severity == "error" for issue in issues)
        )
        if core_is_healthy:
            try:
                coherent = self.load_job(job_id)
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
            else:
                marker = coherent.marker
                manifest = coherent.manifest
                source = coherent.source
                effective_run_status = coherent.effective_run_status
                if (
                    manifest.run_status is JobRunStatus.RUNNING
                    and effective_run_status is JobRunStatus.INTERRUPTED
                ):
                    self._append_issue(issues, self._interrupted_projection_issue())
        else:
            try:
                effective_run_status, projection_issue = self._project_claim_state(
                    paths,
                    effective_run_status,
                )
                if projection_issue is not None:
                    self._append_issue(issues, projection_issue)
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
        entry = self._entry_from_parts(
            job_id,
            manifest,
            tuple(issues),
            marker=marker,
            effective_run_status=effective_run_status,
        )
        return JobInspection(entry, marker, manifest, source, (), False)

    def _paths_for(self, job_id: str) -> JobPaths:
        try:
            return JobPaths(self.paths, job_id)
        except (DomainSchemaError, WorkspacePathOutsideRootError, OSError, ValueError) as exc:
            raise _repository_error(
                "job_path_escape",
                "Job 路径无效或包含链接。",
                "请检查工作区 jobs 目录和 Job ID。",
                None,
                exc,
            ) from exc

    def _entry_from_parts(
        self,
        discovery_id: str,
        manifest: JobManifest | None,
        issues: tuple[JobIssue, ...],
        *,
        marker: JobRepositoryMarker | None = None,
        effective_run_status: JobRunStatus | None = None,
    ) -> JobCatalogEntry:
        kinds: list[FinalArtifactKind] = []
        if manifest is not None:
            for artifact in manifest.final_artifacts:
                if artifact.kind not in kinds:
                    kinds.append(artifact.kind)
        job_id = manifest.job_id if manifest is not None else (
            marker.job_id if marker is not None else None
        )
        return JobCatalogEntry(
            discovery_id,
            job_id,
            None if manifest is None else manifest.display_name,
            None if manifest is None else manifest.created_at,
            None if manifest is None else manifest.updated_at,
            None if manifest is None else manifest.demo_asset_id,
            None if manifest is None else manifest.demo_display_name,
            None if manifest is None else manifest.map_name,
            None if manifest is None else manifest.target_player_id,
            None if manifest is None else manifest.phase,
            None if manifest is None else manifest.run_status,
            (
                None
                if manifest is None
                else effective_run_status or manifest.run_status
            ),
            None if manifest is None else manifest.round_progress,
            tuple(kinds),
            not any(issue.severity == "error" for issue in issues),
            issues,
        )

    def _inspect_document(
        self,
        path: Path,
        *,
        logical_path: str,
        parser,
        missing_code: str,
        invalid_code: str,
        issues: list[JobIssue],
    ):
        try:
            self._assert_safe_regular(
                path,
                logical_path=logical_path,
                missing_code=missing_code,
                invalid_code=invalid_code,
            )
            return read_strict_json(path, logical_path=logical_path, parser=parser)
        except JobRepositoryError as exc:
            if invalid_code == "job_manifest_invalid" and exc.code in {
                "job_shard_missing",
                "job_shard_invalid",
            }:
                exc = _repository_error(
                    "job_manifest_invalid",
                    "Job 身份或清单文档无效。",
                    "请检查该 Job 的身份文档。",
                    logical_path,
                    exc,
                )
            self._append_issue(issues, exc.to_issue())
            return None

    def _append_issue(self, issues: list[JobIssue], issue: JobIssue) -> None:
        key = (issue.code, issue.severity, issue.logical_path, issue.message_zh)
        if all(
            (item.code, item.severity, item.logical_path, item.message_zh) != key
            for item in issues
        ):
            issues.append(issue)

    def _error_from_issue(self, issue: JobIssue) -> JobRepositoryError:
        return JobRepositoryError(
            issue.code,
            issue.message_zh,
            issue.suggestion_zh,
            issue.logical_path,
            severity=issue.severity,
        )

    def _collect_integrity_issues(
        self,
        paths: JobPaths,
        manifest: JobManifest,
        source: JobDemoSource | None,
        *,
        write_lock_already_held: bool = False,
    ) -> tuple[JobIssue, ...]:
        issues = list(
            self._inspect_static_layout(
                paths, write_lock_already_held=write_lock_already_held
            )
        )
        if source is not None:
            try:
                inspection = self.demo_assets.inspect_asset(source.asset_id)
            except (DemoAssetRepositoryError, OSError, TypeError, ValueError):
                inspection = None
            if (
                inspection is None
                or not inspection.source_ok
                or inspection.asset.asset_id != source.asset_id
                or inspection.asset.display_name != source.display_name
                or inspection.asset.to_ref().asset_manifest_relative_path
                != source.asset_manifest_relative_path
            ):
                self._append_issue(
                    issues,
                    JobIssue(
                        "job_source_unavailable",
                        "error",
                        "Job 引用的 Demo 持久源不可用。",
                        "请在素材管理中检查或重新导入该 Demo；已有最终产物仍可查看。",
                        "source/demo_ref.json",
                    ),
                )
        for artifact in manifest.final_artifacts:
            try:
                path = paths.artifact_path(artifact.kind, artifact.relative_path)
                digest = self._hash_safe_regular(path, artifact.relative_path)
                if digest != artifact.content_sha256:
                    raise _repository_error(
                        "job_shard_invalid",
                        "最终产物内容与清单哈希不一致。",
                        "请重新生成或恢复该产物。",
                        artifact.relative_path,
                    )
            except (
                WorkspacePathOutsideRootError,
                DomainSchemaError,
                OSError,
                ValueError,
            ) as exc:
                error = _repository_error(
                    "job_path_escape",
                    "最终产物路径超出 Job 或包含不安全节点。",
                    "请检查 job.json 中的最终产物路径。",
                    artifact.relative_path,
                    exc,
                )
                self._append_issue(issues, error.to_issue())
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
        return tuple(issues)

    def _inspect_static_layout(
        self, paths: JobPaths, *, write_lock_already_held: bool = False
    ) -> tuple[JobIssue, ...]:
        issues: list[JobIssue] = []
        for relative in _INITIAL_DIRECTORIES:
            directory = paths.job_dir.joinpath(*relative.split("/"))
            try:
                state = os.lstat(directory)
                if _is_link_or_reparse(state):
                    raise _repository_error(
                        "job_path_escape",
                        "Job 布局目录包含链接或重解析点。",
                        "请恢复该目录后重试。",
                        relative,
                    )
                if not stat.S_ISDIR(state.st_mode):
                    raise _repository_error(
                        "job_shard_invalid",
                        "Job 布局路径不是目录。",
                        "请恢复该目录后重试。",
                        relative,
                    )
            except FileNotFoundError as exc:
                self._append_issue(
                    issues,
                    _repository_error(
                        "job_shard_missing",
                        "Job 必需目录缺失。",
                        "请检查或恢复该 Job。",
                        relative,
                        exc,
                    ).to_issue(),
                )
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
            except OSError as exc:
                self._append_issue(
                    issues,
                    _repository_error(
                        "job_shard_invalid",
                        "无法检查 Job 布局目录。",
                        "请检查该 Job。",
                        relative,
                        exc,
                    ).to_issue(),
                )

        for issue in self._inspect_optional_files(paths):
            self._append_issue(issues, issue)

        required_files = [(paths.event_journal, "events/job_events.jsonl")]
        if not write_lock_already_held:
            required_files.insert(0, (paths.write_lock, "events/.write.lock"))
        for path, logical_path in required_files:
            try:
                payload = self._read_safe_regular(path, logical_path)
                if logical_path == "events/.write.lock" and payload != b"0":
                    raise _repository_error(
                        "job_shard_invalid",
                        "Job 写锁文件必须是稳定的单字节文件。",
                        "请检查该 Job，读取操作不会自动修复它。",
                        logical_path,
                    )
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
        return tuple(issues)

    def _inspect_optional_files(self, paths: JobPaths) -> tuple[JobIssue, ...]:
        issues: list[JobIssue] = []
        for relative in _OPTIONAL_EXACT_FILES:
            path = paths.job_dir.joinpath(*relative.split("/"))
            try:
                state = _lstat_optional(path, logical_path=relative)
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
                continue
            if state is None:
                continue
            try:
                self._assert_safe_regular(
                    path,
                    logical_path=relative,
                    missing_code="job_shard_missing",
                    invalid_code="job_shard_invalid",
                )
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())

        for relative_dir, pattern in _OPTIONAL_DYNAMIC_FILES:
            directory = paths.job_dir.joinpath(*relative_dir.split("/"))
            try:
                children = tuple(os.scandir(directory))
            except (FileNotFoundError, NotADirectoryError):
                continue
            except OSError as exc:
                self._append_issue(
                    issues,
                    _repository_error(
                        "job_shard_invalid",
                        "无法检查 Job 阶段文件。",
                        "请检查该 Job。",
                        relative_dir,
                        exc,
                    ).to_issue(),
                )
                continue
            for child in children:
                if pattern.fullmatch(child.name) is None:
                    continue
                logical_path = f"{relative_dir}/{child.name}"
                try:
                    self._assert_safe_regular(
                        Path(child.path),
                        logical_path=logical_path,
                        missing_code="job_shard_missing",
                        invalid_code="job_shard_invalid",
                    )
                except JobRepositoryError as exc:
                    self._append_issue(issues, exc.to_issue())

        revisions = paths.review_revisions_dir
        try:
            revision_children = tuple(os.scandir(revisions))
        except (FileNotFoundError, NotADirectoryError):
            revision_children = ()
        except OSError as exc:
            self._append_issue(
                issues,
                _repository_error(
                    "job_shard_invalid",
                    "无法检查复核历史目录。",
                    "请检查该 Job。",
                    "review/revisions",
                    exc,
                ).to_issue(),
            )
            revision_children = ()
        for child in revision_children:
            if _REVIEW_DIRECTORY.fullmatch(child.name) is None:
                continue
            logical_directory = f"review/revisions/{child.name}"
            try:
                child_state = child.stat(follow_symlinks=False)
                if _is_link_or_reparse(child_state):
                    raise _repository_error(
                        "job_path_escape",
                        "复核历史目录不能是链接或重解析点。",
                        "请恢复普通目录后重试。",
                        logical_directory,
                    )
                if not stat.S_ISDIR(child_state.st_mode):
                    raise _repository_error(
                        "job_shard_invalid",
                        "复核历史路径不是目录。",
                        "请恢复普通目录后重试。",
                        logical_directory,
                    )
                revision_files = tuple(os.scandir(child.path))
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
                continue
            except OSError as exc:
                self._append_issue(
                    issues,
                    _repository_error(
                        "job_shard_invalid",
                        "无法检查复核历史目录。",
                        "请检查该 Job。",
                        logical_directory,
                        exc,
                    ).to_issue(),
                )
                continue
            for revision_file in revision_files:
                if revision_file.name != "revision.json" and _REVIEW_ROUND_FILE.fullmatch(
                    revision_file.name
                ) is None:
                    continue
                logical_path = f"{logical_directory}/{revision_file.name}"
                try:
                    self._assert_safe_regular(
                        Path(revision_file.path),
                        logical_path=logical_path,
                        missing_code="job_shard_missing",
                        invalid_code="job_shard_invalid",
                    )
                except JobRepositoryError as exc:
                    self._append_issue(issues, exc.to_issue())
        return tuple(issues)

    def _hash_safe_regular(self, path: Path, logical_path: str) -> str:
        digest = hashlib.sha256()
        self._consume_safe_regular(path, logical_path, digest.update)
        return digest.hexdigest()

    def _read_safe_regular(self, path: Path, logical_path: str) -> bytes:
        chunks: list[bytes] = []
        self._consume_safe_regular(path, logical_path, chunks.append)
        return b"".join(chunks)

    def _consume_safe_regular(self, path: Path, logical_path: str, consume) -> None:
        self._assert_safe_regular(
            path,
            logical_path=logical_path,
            missing_code="job_shard_missing",
            invalid_code="job_shard_invalid",
        )
        flags = os.O_RDONLY
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
            try:
                opened = os.fstat(descriptor)
                current = os.lstat(path)
                if (
                    _is_link_or_reparse(current)
                    or not stat.S_ISREG(opened.st_mode)
                    or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
                ):
                    raise _repository_error(
                        "job_path_escape",
                        "Job 文件在读取期间发生变化。",
                        "请停止其他程序修改该 Job 后重试。",
                        logical_path,
                    )
                while True:
                    chunk = os.read(descriptor, 1024 * 1024)
                    if not chunk:
                        break
                    consume(chunk)
            finally:
                os.close(descriptor)
        except JobRepositoryError:
            raise
        except OSError as exc:
            raise _repository_error(
                "job_shard_invalid",
                "无法读取 Job 文件。",
                "请检查文件权限和完整性。",
                logical_path,
                exc,
            ) from exc

    def _assert_safe_regular(
        self,
        path: Path,
        *,
        logical_path: str,
        missing_code: str,
        invalid_code: str,
    ) -> None:
        try:
            result = os.lstat(path)
        except FileNotFoundError as exc:
            raise _repository_error(
                missing_code,
                "Job 必需文件不存在。",
                "请检查或恢复该 Job。",
                logical_path,
                exc,
            ) from exc
        except OSError as exc:
            raise _repository_error(
                invalid_code,
                "无法检查 Job 文件。",
                "请检查该 Job。",
                logical_path,
                exc,
            ) from exc
        if _is_link_or_reparse(result):
            raise _repository_error(
                "job_path_escape",
                "Job 文件不能是链接或重解析点。",
                "请恢复普通文件后重试。",
                logical_path,
            )
        if not stat.S_ISREG(result.st_mode):
            raise _repository_error(
                invalid_code,
                "Job 文件不是普通文件。",
                "请恢复普通文件后重试。",
                logical_path,
            )

    def _validate_source(self, source: JobDemoSource) -> None:
        try:
            inspection = self.demo_assets.inspect_asset(source.asset_id)
        except (DemoAssetRepositoryError, OSError, TypeError, ValueError) as exc:
            raise _repository_error(
                "job_source_unavailable",
                "Job 的 Demo 持久源不可用。",
                "请在素材管理中检查或重新导入 Demo。",
                "source/demo_ref.json",
                exc,
            ) from exc
        if (
            not inspection.source_ok
            or inspection.asset.asset_id != source.asset_id
            or inspection.asset.display_name != source.display_name
            or inspection.asset.to_ref().asset_manifest_relative_path
            != source.asset_manifest_relative_path
        ):
            raise _repository_error(
                "job_source_unavailable",
                "Job 的 Demo 持久源不可用或身份不一致。",
                "请在素材管理中检查该 Demo。",
                "source/demo_ref.json",
            )

    def _validate_jobs_root(self) -> None:
        try:
            result = os.lstat(self.paths.jobs_dir)
        except OSError as exc:
            raise _repository_error(
                "job_path_escape",
                "无法访问当前工作区的 jobs 目录。",
                "请重新选择或修复工作区。",
                None,
                exc,
            ) from exc
        if _is_link_or_reparse(result) or not stat.S_ISDIR(result.st_mode):
            raise _repository_error(
                "job_path_escape",
                "当前工作区的 jobs 路径不是安全目录。",
                "请移除链接或修复工作区。",
            )

    def _ensure_jobs_root_for_write(self, job_id: str) -> None:
        # Constructing JobPaths checks every already-existing component before
        # this write path creates the final jobs directory.
        self._paths_for(job_id)
        current = _lstat_optional(self.paths.jobs_dir)
        if current is None:
            try:
                self.paths.jobs_dir.mkdir(parents=True, exist_ok=False)
            except FileExistsError:
                pass
            except OSError as exc:
                raise _repository_error(
                    "job_write_failed",
                    "无法创建工作区 jobs 目录。",
                    "请检查工作区权限和磁盘空间。",
                    None,
                    exc,
                ) from exc
        self._validate_jobs_root()
        # Reconstruct after mkdir to catch a race that substituted a link.
        self._paths_for(job_id)

    def _new_staging_path(self, job_id: str) -> Path:
        try:
            value = self.staging_id_factory()
        except Exception as exc:
            raise _repository_error(
                "job_write_failed",
                "无法生成 Job staging 标识。",
                "请重试创建 Job。",
                None,
                exc,
            ) from exc
        if not isinstance(value, UUID):
            raise _repository_error(
                "job_write_failed",
                "Job staging 标识无效。",
                "请修复 staging ID 配置。",
            )
        return self.paths.jobs_dir / f".{job_id}.{value.hex}.staging"

    def _prepare_staging(
        self,
        staging: Path,
        marker: JobRepositoryMarker,
        manifest: JobManifest,
        source: JobDemoSource,
    ) -> None:
        try:
            for relative in _INITIAL_DIRECTORIES:
                staging.joinpath(*relative.split("/")).mkdir(parents=True, exist_ok=False)

            documents = (
                (staging / "repository.json", marker, "repository.json", _MARKER_PARSER),
                (
                    staging / "source/demo_ref.json",
                    source,
                    "source/demo_ref.json",
                    _SOURCE_PARSER,
                ),
                (staging / "job.json", manifest, "job.json", _MANIFEST_PARSER),
            )
            for path, value, logical_path, parser in documents:
                atomic_write_json(
                    path,
                    value,
                    logical_path=logical_path,
                    serializer=lambda item: item.to_dict(),
                    parser=parser,
                )
            atomic_write_bytes(
                staging / "events/.write.lock",
                b"0",
                logical_path="events/.write.lock",
            )
            atomic_write_bytes(
                staging / "events/job_events.jsonl",
                b"",
                logical_path="events/job_events.jsonl",
            )

            # A staged directory is eligible for publication only after the
            # exact production read path has accepted every initial document.
            for path, expected, logical_path, parser in documents:
                if read_strict_json(path, logical_path=logical_path, parser=parser) != expected:
                    raise _repository_error(
                        "job_write_failed",
                        "Job staging 文档回读不一致。",
                        "请重试创建 Job。",
                        logical_path,
                    )
            if (staging / "events/.write.lock").read_bytes() != b"0":
                raise _repository_error(
                    "job_write_failed",
                    "Job 写锁文件初始化失败。",
                    "请重试创建 Job。",
                    "events/.write.lock",
                )
            if (staging / "events/job_events.jsonl").read_bytes() != b"":
                raise _repository_error(
                    "job_write_failed",
                    "Job 事件日志初始化失败。",
                    "请重试创建 Job。",
                    "events/job_events.jsonl",
                )
            _fsync_staging_tree(staging)
        except JobRepositoryError:
            raise
        except OSError as exc:
            raise _repository_error(
                "job_write_failed",
                "无法准备 Job staging 目录。",
                "请检查工作区权限和磁盘空间后重试。",
                None,
                exc,
            ) from exc

    def _validate_existing_job_dir(self, paths: JobPaths) -> None:
        try:
            result = os.lstat(paths.job_dir)
        except FileNotFoundError as exc:
            raise _repository_error(
                "job_not_found",
                "找不到这个 Job。",
                "请从当前工作区的 Job 列表重新选择。",
                None,
                exc,
            ) from exc
        except OSError as exc:
            raise _repository_error(
                "job_path_escape",
                "无法安全打开 Job 目录。",
                "请检查工作区目录。",
                None,
                exc,
            ) from exc
        if _is_link_or_reparse(result) or not stat.S_ISDIR(result.st_mode):
            raise _repository_error(
                "job_path_escape",
                "Job 路径不是安全目录。",
                "请移除链接或修复该 Job。",
            )

    def _read_identity_document(self, path: Path, *, logical_path: str, parser):
        try:
            self._assert_safe_regular(
                path,
                logical_path=logical_path,
                missing_code="job_manifest_invalid",
                invalid_code="job_manifest_invalid",
            )
            return read_strict_json(path, logical_path=logical_path, parser=parser)
        except JobRepositoryError as exc:
            if exc.code == "job_schema_unsupported":
                raise
            if exc.code in {"job_shard_missing", "job_shard_invalid"}:
                mapped = _repository_error(
                    "job_manifest_invalid",
                    "Job 身份或清单文档无效。",
                    "请在管理界面检查该 Job。",
                    logical_path,
                    exc,
                )
                if isinstance(exc.__cause__, DomainSchemaError):
                    mapped.__cause__ = exc.__cause__
                raise mapped
            raise

    def _already_exists(
        self, job_id: str, cause: BaseException | None = None
    ) -> JobRepositoryError:
        return _repository_error(
            "job_already_exists",
            "同名 Job 已存在，未覆盖任何内容。",
            "请改用新的 Job ID，或从列表打开已有 Job。",
            None,
            cause,
        )

    def _cleanup_owned_staging(
        self,
        staging: Path,
        identity: tuple[int, int],
        primary: BaseException | None,
    ) -> None:
        try:
            current = os.lstat(staging)
        except FileNotFoundError:
            return
        except OSError as cleanup_error:
            if primary is not None:
                primary.add_note(f"staging cleanup check failed: {type(cleanup_error).__name__}")
                return
            raise _repository_error(
                "job_write_failed",
                "无法检查 Job staging 目录。",
                "请检查 jobs 目录中的隐藏 staging。",
                None,
                cleanup_error,
            ) from cleanup_error
        if (
            staging.parent != self.paths.jobs_dir
            or not staging.name.startswith(".")
            or not staging.name.endswith(".staging")
            or _is_link_or_reparse(current)
            or not stat.S_ISDIR(current.st_mode)
            or (current.st_dev, current.st_ino) != identity
        ):
            if primary is not None:
                primary.add_note("staging cleanup skipped because ownership changed")
                return
            raise _repository_error(
                "job_write_failed",
                "Job staging 所有权已变化，未执行清理。",
                "请检查 jobs 目录中的隐藏 staging。",
            )
        try:
            shutil.rmtree(staging)
        except OSError as cleanup_error:
            if primary is not None:
                primary.add_note(f"staging cleanup failed: {type(cleanup_error).__name__}")
                return
            raise _repository_error(
                "job_write_failed",
                "无法清理 Job staging 目录。",
                "请检查 jobs 目录中的隐藏 staging。",
                None,
                cleanup_error,
            ) from cleanup_error
