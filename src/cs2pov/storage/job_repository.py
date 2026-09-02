from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import ctypes
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
    JobEvent,
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
from cs2pov.domain.invocation import (
    ModelConfigurationSnapshot,
    ModelInvocationRecord,
)
from cs2pov.domain.review import (
    DraftCommsTimeline,
    ReviewRevisionManifest,
    ReviewedCommsTimeline,
    RoundReviewDocument,
    compose_reviewed_timeline,
)
from cs2pov.domain.schema import require_path_identifier
from cs2pov.domain.timeline import DemoTimeline
from cs2pov.domain.transcript import TranscriptCue
from cs2pov.domain.understanding import RoundUnderstandingDocument
from cs2pov.domain.validation import (
    validate_draft_timeline_graph,
    validate_reviewed_timeline_graph,
    validate_transcript_against_timeline,
    validate_understanding_document_graph,
    validate_voice_activity_against_timeline,
)
from cs2pov.domain.voice import VoiceActivityCue
from cs2pov.storage.demo_asset_repository import (
    DemoAssetRepositoryError,
    FileSystemDemoAssetRepository,
)
from cs2pov.storage.job_errors import JobRepositoryError
from cs2pov.storage.job_paths import JobPaths
from cs2pov.workspace.errors import WorkspacePathOutsideRootError
from cs2pov.workspace.paths import WorkspacePaths

from .atomic_documents import (
    append_jsonl_record,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_jsonl,
    read_strict_json,
    read_strict_jsonl,
    schema_aware_parser,
)
from .cross_process_lock import CrossProcessFileLock
from .job_claim import CLAIM_INITIALIZATION_GRACE_US, JobWriteSession
from .job_events import (
    EVENT_LOGICAL_PATH,
    JOB_EVENT_PARSER,
    EventJournalRead,
    read_event_journal,
)
from .job_shards import (
    DEMO_DESCRIPTOR_PARSER,
    DRAFT_TIMELINE_PARSER,
    MODEL_CONFIGURATION_PARSER,
    MODEL_INVOCATION_PARSER,
    ROUND_COLLECTION_PARSER,
    ROUND_REVIEW_PARSER,
    ROUND_UNDERSTANDING_PARSER,
    REVIEWED_TIMELINE_PARSER,
    REVIEW_REVISION_PARSER,
    TIME_ANCHOR_PARSER,
    TRANSCRIPT_CUE_PARSER,
    VOICE_ACTIVITY_PARSER,
    canonical_task_invocations,
    canonical_transcripts,
    canonical_voice_activities,
    require_canonical_task_invocations,
    require_canonical_transcripts,
    require_canonical_voice_activities,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class OpenedJob:
    marker: JobRepositoryMarker
    manifest: JobManifest
    source: JobDemoSource
    paths: JobPaths
    effective_run_status: JobRunStatus


@dataclass(frozen=True, slots=True)
class LanguageGraph:
    timeline: DemoTimeline
    activities: tuple[VoiceActivityCue, ...]
    configurations: tuple[ModelConfigurationSnapshot, ...]
    invocations: tuple[ModelInvocationRecord, ...]
    transcripts: tuple[TranscriptCue, ...]
    understanding_documents: tuple[RoundUnderstandingDocument, ...]


@dataclass(frozen=True, slots=True)
class ReviewRevisionBundle:
    revision: ReviewRevisionManifest
    round_documents: tuple[RoundReviewDocument, ...]


@dataclass(frozen=True, slots=True)
class CompleteDomainGraph:
    language: LanguageGraph
    draft: DraftCommsTimeline
    active_review: ReviewRevisionBundle
    reviewed: ReviewedCommsTimeline


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


def _fsync_metadata_directory(
    path: Path,
    logical_path: str,
    *,
    expected_identity: tuple[int, int] | None = None,
) -> None:
    if os.name == "nt":
        return
    try:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            current = os.lstat(path)
            identity = (opened.st_dev, opened.st_ino)
            if (
                _is_link_or_reparse(current)
                or not stat.S_ISDIR(opened.st_mode)
                or identity != (current.st_dev, current.st_ino)
                or (expected_identity is not None and identity != expected_identity)
            ):
                raise _repository_error(
                    "job_path_escape",
                    "Job 目录在持久化期间发生变化。",
                    "请停止其他程序修改该 Job 后重试。",
                    logical_path,
                )
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except JobRepositoryError:
        raise
    except OSError as exc:
        raise _repository_error(
            "job_write_durability_uncertain",
            "写入结果已经可见，但目录持久化状态不确定。",
            "请重新检查该 Job；不要回滚已经可见的结果。",
            logical_path,
            exc,
        ) from exc


def _rename_directory_no_replace(
    source: Path,
    target: Path,
    *,
    expected_source_identity: tuple[int, int],
    logical_path: str,
) -> tuple[int, int]:
    if source.parent != target.parent:
        raise _repository_error(
            "job_write_failed",
            "复核版本 staging 与目标不在同一目录。",
            "请检查 Job 仓储实现。",
            logical_path,
        )
    parent = source.parent
    try:
        parent_before = os.lstat(parent)
    except OSError as exc:
        raise _repository_error(
            "job_path_escape",
            "无法安全打开复核版本父目录。",
            "请检查 review/revisions 目录。",
            logical_path,
            exc,
        ) from exc
    if _is_link_or_reparse(parent_before) or not stat.S_ISDIR(parent_before.st_mode):
        raise _repository_error(
            "job_path_escape",
            "复核版本父目录不是安全目录。",
            "请检查 review/revisions 目录。",
            logical_path,
        )
    parent_identity = (parent_before.st_dev, parent_before.st_ino)

    if os.name == "nt":
        try:
            source_state = os.lstat(source)
            if (
                _is_link_or_reparse(source_state)
                or not stat.S_ISDIR(source_state.st_mode)
                or (source_state.st_dev, source_state.st_ino)
                != expected_source_identity
            ):
                raise _repository_error(
                    "job_path_escape",
                    "复核版本 staging 目录在发布前发生变化。",
                    "请停止其他程序修改该 Job 后重试。",
                    logical_path,
                )
            os.rename(source, target)
        except JobRepositoryError:
            raise
        except OSError as exc:
            try:
                collision = os.lstat(target)
            except OSError:
                collision = None
            if collision is not None:
                raise _repository_error(
                    "job_shard_invalid",
                    "同一复核版本 ID 已存在，未覆盖原目录。",
                    "请改用新的复核版本 ID，或加载已有版本。",
                    logical_path,
                    exc,
                ) from exc
            raise _repository_error(
                "job_write_failed",
                "无法发布复核版本目录。",
                "请检查磁盘空间和目录权限。",
                logical_path,
                exc,
            ) from exc
        parent_after = os.lstat(parent)
        target_state = os.lstat(target)
        if (
            _is_link_or_reparse(parent_after)
            or (parent_after.st_dev, parent_after.st_ino) != parent_identity
            or _is_link_or_reparse(target_state)
            or not stat.S_ISDIR(target_state.st_mode)
            or (target_state.st_dev, target_state.st_ino)
            != expected_source_identity
        ):
            raise _repository_error(
                "job_path_escape",
                "复核版本目录在发布期间发生变化。",
                "请停止其他程序修改该 Job 后检查复核历史。",
                logical_path,
            )
        return parent_identity

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_descriptor = os.open(parent, flags)
        try:
            opened_parent = os.fstat(parent_descriptor)
            current_parent = os.lstat(parent)
            if (
                _is_link_or_reparse(current_parent)
                or not stat.S_ISDIR(opened_parent.st_mode)
                or (opened_parent.st_dev, opened_parent.st_ino) != parent_identity
                or (current_parent.st_dev, current_parent.st_ino) != parent_identity
            ):
                raise _repository_error(
                    "job_path_escape",
                    "复核版本父目录在发布前发生变化。",
                    "请停止其他程序修改该 Job 后重试。",
                    logical_path,
                )
            source_state = os.stat(
                source.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISDIR(source_state.st_mode)
                or (source_state.st_dev, source_state.st_ino)
                != expected_source_identity
            ):
                raise _repository_error(
                    "job_path_escape",
                    "复核版本 staging 目录在发布前发生变化。",
                    "请停止其他程序修改该 Job 后重试。",
                    logical_path,
                )

            library = ctypes.CDLL(None, use_errno=True)
            rename_no_replace = None
            rename_flags = 0
            if sys.platform.startswith("linux"):
                rename_no_replace = getattr(library, "renameat2", None)
                rename_flags = 1  # RENAME_NOREPLACE
            elif sys.platform == "darwin":
                rename_no_replace = getattr(library, "renameatx_np", None)
                rename_flags = 0x00000004  # RENAME_EXCL
            if rename_no_replace is None:
                raise _repository_error(
                    "job_write_failed",
                    "当前 POSIX 平台不支持原子不可覆盖目录发布。",
                    "请在支持 renameat2/renameatx_np 的平台运行。",
                    logical_path,
                )
            rename_no_replace.argtypes = (
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            )
            rename_no_replace.restype = ctypes.c_int
            result = rename_no_replace(
                parent_descriptor,
                os.fsencode(source.name),
                parent_descriptor,
                os.fsencode(target.name),
                rename_flags,
            )
            if result != 0:
                error_number = ctypes.get_errno()
                error = OSError(error_number, os.strerror(error_number))
                if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise _repository_error(
                        "job_shard_invalid",
                        "同一复核版本 ID 已存在，未覆盖原目录。",
                        "请改用新的复核版本 ID，或加载已有版本。",
                        logical_path,
                        error,
                    ) from error
                raise error
            target_state = os.stat(
                target.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            current_parent = os.lstat(parent)
            if (
                not stat.S_ISDIR(target_state.st_mode)
                or (target_state.st_dev, target_state.st_ino)
                != expected_source_identity
                or _is_link_or_reparse(current_parent)
                or (current_parent.st_dev, current_parent.st_ino) != parent_identity
            ):
                raise _repository_error(
                    "job_path_escape",
                    "复核版本目录在发布期间发生变化。",
                    "请停止其他程序修改该 Job 后检查复核历史。",
                    logical_path,
                )
        finally:
            os.close(parent_descriptor)
    except JobRepositoryError:
        raise
    except OSError as exc:
        raise _repository_error(
            "job_write_failed",
            "无法发布复核版本目录。",
            "请检查平台能力、磁盘空间和目录权限。",
            logical_path,
            exc,
        ) from exc
    return parent_identity


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
        if manifest.active_review_id is not None:
            self._read_review_revision_locked(
                paths,
                manifest,
                manifest.active_review_id,
            )
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

    def save_voice_activities(
        self,
        job_id: str,
        activities: tuple[VoiceActivityCue, ...],
        claim: JobWriteClaim,
    ) -> None:
        try:
            canonical = canonical_voice_activities(activities)
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "语音活动集合无效。", "voice/activities.jsonl", exc
            ) from exc
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            atomic_write_jsonl(
                paths.voice_activities,
                canonical,
                logical_path="voice/activities.jsonl",
                serializer=lambda value: value.to_dict(),
                parser=VOICE_ACTIVITY_PARSER,
            )

    def load_voice_activities(
        self, job_id: str
    ) -> tuple[VoiceActivityCue, ...]:
        opened = self.load_job(job_id)
        state = _lstat_optional(
            opened.paths.voice_activities,
            logical_path="voice/activities.jsonl",
        )
        if state is None:
            return ()
        result = read_strict_jsonl(
            opened.paths.voice_activities,
            logical_path="voice/activities.jsonl",
            parser=VOICE_ACTIVITY_PARSER,
        )
        try:
            return require_canonical_voice_activities(result.records)
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "语音活动文件关系无效。", "voice/activities.jsonl", exc
            ) from exc

    def register_model_configuration(
        self,
        job_id: str,
        snapshot: ModelConfigurationSnapshot,
        expected_manifest_fingerprint: str,
        claim: JobWriteClaim,
    ) -> OpenedJob:
        if type(snapshot) is not ModelConfigurationSnapshot:
            raise self._invalid_shard_input(
                "模型配置快照无效。", "models/snapshots"
            )
        snapshot_id = self._persisted_path_id(snapshot.snapshot_id, "snapshot_id")
        if not isinstance(expected_manifest_fingerprint, str):
            raise TypeError("expected_manifest_fingerprint must be a string")
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            current = opened.manifest
            if current.content_fingerprint() != expected_manifest_fingerprint:
                raise self._manifest_conflict()
            configurations = self._configuration_index(
                paths,
                current,
                allowed_unindexed_id=snapshot_id,
            )
            existing = configurations.get(snapshot_id)
            if existing is not None and existing != snapshot:
                raise self._invalid_shard_input(
                    "同一配置 ID 已存在不同内容。",
                    f"models/snapshots/snapshot_{snapshot_id}.json",
                )
            if snapshot_id in current.configuration_snapshot_ids:
                if existing is None:
                    raise self._invalid_shard_input(
                        "Job 清单引用的模型配置不存在。",
                        f"models/snapshots/snapshot_{snapshot_id}.json",
                    )
                return opened
            timestamp = _canonical_timestamp(self.clock)
            if timestamp <= current.updated_at:
                raise self._manifest_conflict(
                    "Job 更新时间没有向前推进，尚未写入配置快照。"
                )
            target = paths.snapshot(snapshot_id)
            if existing is None:
                atomic_write_json(
                    target,
                    snapshot,
                    logical_path=f"models/snapshots/snapshot_{snapshot_id}.json",
                    serializer=lambda value: value.to_dict(),
                    parser=MODEL_CONFIGURATION_PARSER,
                )
            new_manifest = replace(
                current,
                updated_at=timestamp,
                configuration_snapshot_ids=(
                    *current.configuration_snapshot_ids,
                    snapshot_id,
                ),
            )
            return self._replace_manifest_locked(
                locked_file,
                job_id,
                expected_manifest_fingerprint,
                new_manifest,
                claim,
            )

    def load_model_configuration(
        self, job_id: str, snapshot_id: str
    ) -> ModelConfigurationSnapshot:
        persisted_id = self._persisted_path_id(snapshot_id, "snapshot_id")
        opened = self.load_job(job_id)
        if persisted_id not in opened.manifest.configuration_snapshot_ids:
            raise self._invalid_shard_input(
                "模型配置快照尚未登记到 Job 清单。", "models/snapshots"
            )
        value = self._read_model_configuration(opened.paths, persisted_id)
        if value.snapshot_id != persisted_id:
            raise self._invalid_shard_input(
                "配置文件名与内容身份不一致。",
                f"models/snapshots/snapshot_{persisted_id}.json",
            )
        return value

    def load_model_configurations(
        self, job_id: str
    ) -> tuple[ModelConfigurationSnapshot, ...]:
        opened = self.load_job(job_id)
        values = self._configuration_index(opened.paths, opened.manifest)
        return tuple(
            values[snapshot_id]
            for snapshot_id in opened.manifest.configuration_snapshot_ids
        )

    def save_task_invocations(
        self,
        job_id: str,
        task_id: str,
        records: tuple[ModelInvocationRecord, ...],
        claim: JobWriteClaim,
    ) -> None:
        persisted_id = self._persisted_path_id(task_id, "task_id")
        try:
            canonical = canonical_task_invocations(persisted_id, records)
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "模型调用集合与任务文件不一致。",
                f"models/invocations/task_{persisted_id}.jsonl",
                exc,
            ) from exc
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            configurations = self._configuration_index(paths, opened.manifest)
            if any(
                record.configuration_snapshot_id not in configurations
                for record in canonical
            ):
                raise self._invalid_shard_input(
                    "模型调用引用了未注册的配置快照。",
                    f"models/invocations/task_{persisted_id}.jsonl",
                )
            target = paths.task_invocations(persisted_id)
            if _lstat_optional(
                target,
                logical_path=f"models/invocations/task_{persisted_id}.jsonl",
            ) is not None:
                existing = self._read_task_invocations(paths, persisted_id)
                if existing != canonical:
                    raise self._invalid_shard_input(
                        "同一任务调用文件已存在不同内容。",
                        f"models/invocations/task_{persisted_id}.jsonl",
                    )
                return
            atomic_write_jsonl(
                target,
                canonical,
                logical_path=f"models/invocations/task_{persisted_id}.jsonl",
                serializer=lambda value: value.to_dict(),
                parser=MODEL_INVOCATION_PARSER,
            )

    def load_task_invocations(
        self, job_id: str, task_id: str
    ) -> tuple[ModelInvocationRecord, ...]:
        persisted_id = self._persisted_path_id(task_id, "task_id")
        opened = self.load_job(job_id)
        values = self._read_task_invocations(opened.paths, persisted_id)
        configurations = self._configuration_index(opened.paths, opened.manifest)
        if any(
            value.configuration_snapshot_id not in configurations for value in values
        ):
            raise self._invalid_shard_input(
                "模型调用引用了未注册的配置快照。",
                f"models/invocations/task_{persisted_id}.jsonl",
            )
        return values

    def load_all_invocations(
        self, job_id: str
    ) -> tuple[ModelInvocationRecord, ...]:
        opened = self.load_job(job_id)
        task_ids = self._invocation_task_ids(opened.paths)
        values = tuple(
            value
            for task_id in task_ids
            for value in self._read_task_invocations(opened.paths, task_id)
        )
        if len({value.invocation_id for value in values}) != len(values):
            raise self._invalid_shard_input(
                "不同任务文件中的模型调用 ID 重复。", "models/invocations"
            )
        configurations = self._configuration_index(opened.paths, opened.manifest)
        if any(
            value.configuration_snapshot_id not in configurations for value in values
        ):
            raise self._invalid_shard_input(
                "模型调用引用了未注册的配置快照。", "models/invocations"
            )
        return values

    def save_demo_timeline(
        self,
        job_id: str,
        timeline: DemoTimeline,
        claim: JobWriteClaim,
    ) -> None:
        if type(timeline) is not DemoTimeline:
            raise self._invalid_shard_input("Demo 时间线无效。", "timeline")
        self._validate_timeline_path_ids(timeline)
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            if timeline.descriptor.demo_asset_id != opened.manifest.demo_asset_id:
                raise self._invalid_shard_input(
                    "Demo 时间线引用了不同的素材。", "timeline/demo.json"
                )
            atomic_write_json(
                paths.demo_timeline,
                timeline.descriptor,
                logical_path="timeline/demo.json",
                serializer=lambda value: value.to_dict(),
                parser=DEMO_DESCRIPTOR_PARSER,
            )
            atomic_write_json(
                paths.timeline_rounds,
                timeline.rounds,
                logical_path="timeline/rounds.json",
                serializer=lambda value: value.to_dict(),
                parser=ROUND_COLLECTION_PARSER,
            )
            atomic_write_jsonl(
                paths.time_anchors,
                timeline.anchors,
                logical_path="timeline/time_anchors.jsonl",
                serializer=lambda value: value.to_dict(),
                parser=TIME_ANCHOR_PARSER,
            )

    def load_demo_timeline(self, job_id: str) -> DemoTimeline:
        opened = self.load_job(job_id)
        return self._read_demo_timeline(
            opened.paths,
            expected_asset_id=opened.manifest.demo_asset_id,
        )

    def save_transcript_round(
        self,
        job_id: str,
        round_id: str,
        cues: tuple[TranscriptCue, ...],
        claim: JobWriteClaim,
    ) -> None:
        persisted_id = self._persisted_path_id(round_id, "round_id")
        logical_path = f"transcript/round_{persisted_id}.jsonl"
        try:
            canonical = canonical_transcripts(
                cues,
                round_id=persisted_id,
                logical_path=logical_path,
            )
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "回合转录文件关系无效。", logical_path, exc
            ) from exc
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            timeline = self._read_demo_timeline(
                paths,
                expected_asset_id=opened.manifest.demo_asset_id,
            )
            if persisted_id not in {
                value.round_id for value in timeline.rounds.rounds
            }:
                raise self._invalid_shard_input(
                    "回合转录引用了未知回合。", logical_path
                )
            atomic_write_jsonl(
                paths.round_transcript(persisted_id),
                canonical,
                logical_path=logical_path,
                serializer=lambda value: value.to_dict(),
                parser=TRANSCRIPT_CUE_PARSER,
            )

    def load_transcript_round(
        self, job_id: str, round_id: str
    ) -> tuple[TranscriptCue, ...]:
        persisted_id = self._persisted_path_id(round_id, "round_id")
        opened = self.load_job(job_id)
        return self._read_transcript_file(opened.paths, persisted_id)

    def save_unassigned_transcript(
        self,
        job_id: str,
        cues: tuple[TranscriptCue, ...],
        claim: JobWriteClaim,
    ) -> None:
        logical_path = "transcript/unassigned.jsonl"
        try:
            canonical = canonical_transcripts(
                cues,
                round_id=None,
                logical_path=logical_path,
            )
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "未分配转录文件关系无效。", logical_path, exc
            ) from exc
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            atomic_write_jsonl(
                paths.unassigned_transcript(),
                canonical,
                logical_path=logical_path,
                serializer=lambda value: value.to_dict(),
                parser=TRANSCRIPT_CUE_PARSER,
            )

    def load_unassigned_transcript(
        self, job_id: str
    ) -> tuple[TranscriptCue, ...]:
        opened = self.load_job(job_id)
        return self._read_unassigned_transcript(opened.paths, required=True)

    def save_round_understanding(
        self,
        job_id: str,
        document: RoundUnderstandingDocument,
        claim: JobWriteClaim,
    ) -> None:
        if type(document) is not RoundUnderstandingDocument:
            raise self._invalid_shard_input(
                "理解翻译文档无效。", "understanding"
            )
        round_id = self._persisted_path_id(document.round_id, "round_id")
        logical_path = f"understanding/round_{round_id}.json"
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            atomic_write_json(
                paths.round_understanding(round_id),
                document,
                logical_path=logical_path,
                serializer=lambda value: value.to_dict(),
                parser=ROUND_UNDERSTANDING_PARSER,
            )

    def load_round_understanding(
        self, job_id: str, round_id: str
    ) -> RoundUnderstandingDocument:
        persisted_id = self._persisted_path_id(round_id, "round_id")
        opened = self.load_job(job_id)
        return self._read_round_understanding(opened.paths, persisted_id)

    def load_language_graph(self, job_id: str) -> LanguageGraph:
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_read_lock_locked(paths, locked_file)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            return self._read_language_graph_locked(opened.paths, opened.manifest)

    def register_review_revision(
        self,
        job_id: str,
        revision: ReviewRevisionManifest,
        round_documents: tuple[RoundReviewDocument, ...],
        expected_manifest_fingerprint: str,
        activate: bool,
        claim: JobWriteClaim,
    ) -> ReviewRevisionBundle:
        if type(revision) is not ReviewRevisionManifest:
            raise self._invalid_shard_input(
                "复核版本清单无效。", "review/revisions"
            )
        if not isinstance(round_documents, (tuple, list)) or any(
            type(value) is not RoundReviewDocument for value in round_documents
        ):
            raise self._invalid_shard_input(
                "复核回合文档集合无效。", "review/revisions"
            )
        if not isinstance(expected_manifest_fingerprint, str):
            raise TypeError("expected_manifest_fingerprint must be a string")
        if type(activate) is not bool:
            raise TypeError("activate must be a bool")
        review_id = self._persisted_path_id(revision.review_id, "review_id")
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            current = opened.manifest
            if current.content_fingerprint() != expected_manifest_fingerprint:
                raise self._manifest_conflict()
            language = self._read_language_graph_locked(paths, current)
            draft = self._read_validated_draft_locked(paths, current, language)
            bundle = self._validate_review_bundle(
                language.timeline,
                draft,
                revision,
                tuple(round_documents),
                logical_path=f"review/revisions/review_{review_id}",
            )
            target = paths.review_revision(review_id)
            target_state = _lstat_optional(
                target,
                logical_path=f"review/revisions/review_{review_id}",
            )
            if target_state is None:
                self._publish_review_revision(paths, bundle)
                persisted = self._read_review_revision_directory(
                    target,
                    logical_directory=f"review/revisions/review_{review_id}",
                    expected_review_id=review_id,
                    timeline=language.timeline,
                    draft=draft,
                )
                if persisted != bundle:
                    raise self._invalid_shard_input(
                        "复核版本发布后的回读内容不一致。",
                        f"review/revisions/review_{review_id}",
                    )
            else:
                if _is_link_or_reparse(target_state) or not stat.S_ISDIR(
                    target_state.st_mode
                ):
                    raise self._invalid_shard_input(
                        "复核版本路径不是安全目录。",
                        f"review/revisions/review_{review_id}",
                    )
                persisted = self._read_review_revision_directory(
                    target,
                    logical_directory=f"review/revisions/review_{review_id}",
                    expected_review_id=review_id,
                    timeline=language.timeline,
                    draft=draft,
                )
                if persisted != bundle:
                    raise self._invalid_shard_input(
                        "同一复核版本 ID 已存在不同内容。",
                        f"review/revisions/review_{review_id}",
                    )
            if not activate or current.active_review_id == review_id:
                return bundle
            timestamp = _canonical_timestamp(self.clock)
            if timestamp <= current.updated_at:
                raise self._manifest_conflict(
                    "Job 更新时间没有向前推进，复核版本尚未激活。"
                )
            new_manifest = replace(
                current,
                updated_at=timestamp,
                active_review_id=review_id,
            )
            self._replace_manifest_locked(
                locked_file,
                job_id,
                expected_manifest_fingerprint,
                new_manifest,
                claim,
            )
            return bundle

    def load_review_revision(
        self, job_id: str, review_id: str
    ) -> ReviewRevisionBundle:
        persisted_id = self._persisted_path_id(review_id, "review_id")
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_read_lock_locked(paths, locked_file)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            return self._read_review_revision_locked(
                paths,
                opened.manifest,
                persisted_id,
            )

    def save_draft_timeline(
        self,
        job_id: str,
        timeline: DraftCommsTimeline,
        claim: JobWriteClaim,
    ) -> None:
        if type(timeline) is not DraftCommsTimeline:
            raise self._invalid_shard_input(
                "Draft 通讯时间线无效。", "final/timelines/draft.json"
            )
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            language = self._read_language_graph_locked(paths, opened.manifest)
            self._validate_draft(timeline, language)
            atomic_write_json(
                paths.final_timelines_dir / "draft.json",
                timeline,
                logical_path="final/timelines/draft.json",
                serializer=lambda value: value.to_dict(),
                parser=DRAFT_TIMELINE_PARSER,
            )

    def load_draft_timeline(self, job_id: str) -> DraftCommsTimeline:
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_read_lock_locked(paths, locked_file)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            language = self._read_language_graph_locked(paths, opened.manifest)
            return self._read_validated_draft_locked(
                paths, opened.manifest, language
            )

    def save_reviewed_timeline(
        self,
        job_id: str,
        timeline: ReviewedCommsTimeline,
        claim: JobWriteClaim,
    ) -> None:
        if type(timeline) is not ReviewedCommsTimeline:
            raise self._invalid_shard_input(
                "Reviewed 通讯时间线无效。", "final/timelines/reviewed.json"
            )
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            self._verify_claim_locked(paths, claim)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            language = self._read_language_graph_locked(paths, opened.manifest)
            draft = self._read_validated_draft_locked(
                paths, opened.manifest, language
            )
            active = self._read_active_review_locked(paths, opened.manifest)
            self._validate_reviewed(timeline, language, draft, active)
            atomic_write_json(
                paths.final_timelines_dir / "reviewed.json",
                timeline,
                logical_path="final/timelines/reviewed.json",
                serializer=lambda value: value.to_dict(),
                parser=REVIEWED_TIMELINE_PARSER,
            )

    def load_reviewed_timeline(self, job_id: str) -> ReviewedCommsTimeline:
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_read_lock_locked(paths, locked_file)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            language = self._read_language_graph_locked(paths, opened.manifest)
            draft = self._read_validated_draft_locked(
                paths, opened.manifest, language
            )
            active = self._read_active_review_locked(paths, opened.manifest)
            return self._read_validated_reviewed_locked(
                paths,
                language,
                draft,
                active,
            )

    def load_complete_domain_graph(self, job_id: str) -> CompleteDomainGraph:
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_read_lock_locked(paths, locked_file)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            language = self._read_language_graph_locked(paths, opened.manifest)
            draft = self._read_validated_draft_locked(
                paths, opened.manifest, language
            )
            active = self._read_active_review_locked(paths, opened.manifest)
            reviewed = self._read_validated_reviewed_locked(
                paths,
                language,
                draft,
                active,
            )
            return CompleteDomainGraph(language, draft, active, reviewed)

    def append_event(
        self,
        job_id: str,
        event: JobEvent,
        claim: JobWriteClaim,
    ) -> None:
        if type(event) is not JobEvent:
            raise self._invalid_shard_input(
                "Job 事件无效。", EVENT_LOGICAL_PATH
            )
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_write_lock_locked(paths, locked_file)
            active, _ = self._verify_claim_locked(paths, claim)
            if event.job_id != job_id or event.run_id != active.run_id:
                raise self._invalid_shard_input(
                    "Job 事件与当前 Job 或写入会话身份不一致。",
                    EVENT_LOGICAL_PATH,
                )
            current = read_event_journal(
                paths.event_journal,
                expected_job_id=job_id,
            )
            if current.incomplete_tail:
                raise self._invalid_shard_input(
                    "事件日志存在不完整末行，不能继续追加。",
                    EVENT_LOGICAL_PATH,
                )
            if event.event_id in {value.event_id for value in current.events}:
                raise self._invalid_shard_input(
                    "事件 ID 已存在，未重复追加。",
                    EVENT_LOGICAL_PATH,
                )
            append_jsonl_record(
                paths.event_journal,
                event,
                logical_path=EVENT_LOGICAL_PATH,
                serializer=lambda value: value.to_dict(),
                parser=JOB_EVENT_PARSER,
            )

    def read_events(self, job_id: str) -> EventJournalRead:
        paths = self._paths_for(job_id)
        self._validate_existing_job_dir(paths)
        with self.lock_factory.open_existing(
            paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
        ) as locked_file:
            self._assert_read_lock_locked(paths, locked_file)
            opened = self._load_job_durable(job_id, write_lock_already_held=True)
            return read_event_journal(
                paths.event_journal,
                expected_job_id=opened.manifest.job_id,
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
                self._read_review_revision_locked(paths, manifest, review_id)
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
        event_read = EventJournalRead((), False, ())
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
            if not any(issue.code == "job_path_escape" for issue in issues):
                try:
                    with self.lock_factory.open_existing(
                        paths.write_lock, timeout_ms=_WRITE_LOCK_TIMEOUT_MS
                    ) as locked_file:
                        self._assert_read_lock_locked(paths, locked_file)
                        for issue in self._inspect_language_shards(paths, manifest):
                            self._append_issue(issues, issue)
                        for issue in self._inspect_review_shards(paths, manifest):
                            self._append_issue(issues, issue)
                        try:
                            event_read = read_event_journal(
                                paths.event_journal,
                                expected_job_id=manifest.job_id,
                            )
                        except JobRepositoryError as exc:
                            self._append_issue(issues, exc.to_issue())
                        else:
                            for issue in event_read.issues:
                                self._append_issue(issues, issue)
                except JobRepositoryError as exc:
                    self._append_issue(issues, exc.to_issue())
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
        elif not any(issue.code == "job_path_escape" for issue in issues):
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
        return JobInspection(
            entry,
            marker,
            manifest,
            source,
            event_read.events,
            event_read.incomplete_tail,
        )

    def _invalid_shard_input(
        self,
        message_zh: str,
        logical_path: str,
        cause: BaseException | None = None,
    ) -> JobRepositoryError:
        return _repository_error(
            "job_shard_invalid",
            message_zh,
            "请检查数据身份和引用关系后重试。",
            logical_path,
            cause,
        )

    def _inspect_language_shards(
        self,
        paths: JobPaths,
        manifest: JobManifest,
    ) -> tuple[JobIssue, ...]:
        issues: list[JobIssue] = []

        def capture(operation) -> bool:
            try:
                operation()
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
                return False
            return True

        timeline_states = tuple(
            _lstat_optional(path, logical_path=logical_path)
            for path, logical_path in (
                (paths.demo_timeline, "timeline/demo.json"),
                (paths.timeline_rounds, "timeline/rounds.json"),
                (paths.time_anchors, "timeline/time_anchors.jsonl"),
            )
        )
        timeline_present = any(state is not None for state in timeline_states)
        timeline_complete = all(state is not None for state in timeline_states)
        timeline_ok = True
        if timeline_present:
            timeline_ok = capture(
                lambda: self._read_demo_timeline(
                    paths,
                    expected_asset_id=manifest.demo_asset_id,
                )
            )

        if _lstat_optional(
            paths.voice_activities,
            logical_path="voice/activities.jsonl",
        ) is not None:
            capture(lambda: self._read_voice_activities(paths, required=True))

        capture(lambda: self._configuration_index(paths, manifest))

        def inspect_invocations() -> None:
            for task_id in self._invocation_task_ids(paths):
                self._read_task_invocations(paths, task_id)

        capture(inspect_invocations)

        def inspect_transcripts() -> None:
            for round_id in self._dynamic_path_ids(
                paths.transcript_dir,
                prefix="round_",
                suffix=".jsonl",
                field="round_id",
                logical_directory="transcript",
            ):
                self._read_transcript_file(paths, round_id)
            if _lstat_optional(
                paths.unassigned_transcript(),
                logical_path="transcript/unassigned.jsonl",
            ) is not None:
                self._read_unassigned_transcript(paths, required=True)

        capture(inspect_transcripts)

        def inspect_understanding() -> None:
            for round_id in self._dynamic_path_ids(
                paths.understanding_dir,
                prefix="round_",
                suffix=".json",
                field="round_id",
                logical_directory="understanding",
            ):
                self._read_round_understanding(paths, round_id)

        capture(inspect_understanding)

        if timeline_complete and timeline_ok and not issues:
            capture(lambda: self._read_language_graph_locked(paths, manifest))
        return tuple(issues)

    def _inspect_review_shards(
        self,
        paths: JobPaths,
        manifest: JobManifest,
    ) -> tuple[JobIssue, ...]:
        issues: list[JobIssue] = []

        def capture(operation) -> bool:
            try:
                operation()
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
                return False
            return True

        try:
            children = tuple(os.scandir(paths.review_revisions_dir))
        except OSError as exc:
            return (
                self._invalid_shard_input(
                    "无法读取复核历史目录。", "review/revisions", exc
                ).to_issue(),
            )
        for child in children:
            logical_path = f"review/revisions/{child.name}"
            if child.name.startswith(".review_") and child.name.endswith(
                ".staging"
            ):
                self._append_issue(
                    issues,
                    self._invalid_shard_input(
                        "存在未完成发布的复核版本 staging。", logical_path
                    ).to_issue(),
                )
                continue
            match = _REVIEW_DIRECTORY.fullmatch(child.name)
            if match is None:
                if child.name.startswith("review_"):
                    self._append_issue(
                        issues,
                        _repository_error(
                            "job_path_escape",
                            "复核版本目录名不是安全的小写标识。",
                            "请检查复核历史目录。",
                            logical_path,
                        ).to_issue(),
                    )
                continue
            review_id = child.name[len("review_") :]
            capture(
                lambda review_id=review_id: self._read_review_revision_locked(
                    paths,
                    manifest,
                    review_id,
                )
            )

        draft_state = _lstat_optional(
            paths.final_timelines_dir / "draft.json",
            logical_path="final/timelines/draft.json",
        )
        if draft_state is not None:
            def inspect_draft() -> None:
                language = self._read_language_graph_locked(paths, manifest)
                self._read_validated_draft_locked(paths, manifest, language)

            capture(inspect_draft)

        reviewed_state = _lstat_optional(
            paths.final_timelines_dir / "reviewed.json",
            logical_path="final/timelines/reviewed.json",
        )
        if reviewed_state is not None:
            def inspect_reviewed() -> None:
                language = self._read_language_graph_locked(paths, manifest)
                draft = self._read_validated_draft_locked(
                    paths, manifest, language
                )
                active = self._read_active_review_locked(paths, manifest)
                self._read_validated_reviewed_locked(
                    paths, language, draft, active
                )

            capture(inspect_reviewed)
        return tuple(issues)

    def _manifest_conflict(
        self, message_zh: str = "Job 清单已经被其他操作更新。"
    ) -> JobRepositoryError:
        return _repository_error(
            "job_manifest_conflict",
            message_zh,
            "请重新打开 Job，并基于最新状态重试。",
            "job.json",
        )

    def _persisted_path_id(self, value: str, field: str) -> str:
        try:
            return require_path_identifier(value, field)
        except DomainSchemaError as exc:
            raise _repository_error(
                "job_path_escape",
                "持久化标识不能安全用作文件名。",
                "请使用小写字母、数字、连字符或下划线。",
                None,
                exc,
            ) from exc

    def _read_model_configuration(
        self, paths: JobPaths, snapshot_id: str
    ) -> ModelConfigurationSnapshot:
        logical_path = f"models/snapshots/snapshot_{snapshot_id}.json"
        target = paths.snapshot(snapshot_id)
        self._assert_safe_regular(
            target,
            logical_path=logical_path,
            missing_code="job_shard_missing",
            invalid_code="job_shard_invalid",
        )
        value = read_strict_json(
            target,
            logical_path=logical_path,
            parser=MODEL_CONFIGURATION_PARSER,
        )
        if value.snapshot_id != snapshot_id:
            raise self._invalid_shard_input(
                "配置文件名与内容身份不一致。", logical_path
            )
        return value

    def _configuration_index(
        self,
        paths: JobPaths,
        manifest: JobManifest,
        *,
        allowed_unindexed_id: str | None = None,
    ) -> dict[str, ModelConfigurationSnapshot]:
        try:
            children = tuple(os.scandir(paths.snapshots_dir))
        except OSError as exc:
            raise self._invalid_shard_input(
                "无法读取模型配置目录。", "models/snapshots", exc
            ) from exc
        disk_ids: list[str] = []
        for child in children:
            if child.name.startswith("."):
                continue
            if not child.name.startswith("snapshot_") or not child.name.endswith(
                ".json"
            ):
                continue
            raw_id = child.name[len("snapshot_") : -len(".json")]
            snapshot_id = self._persisted_path_id(raw_id, "snapshot_id")
            logical_path = f"models/snapshots/{child.name}"
            self._assert_safe_regular(
                Path(child.path),
                logical_path=logical_path,
                missing_code="job_shard_missing",
                invalid_code="job_shard_invalid",
            )
            disk_ids.append(snapshot_id)
        if len({value.casefold() for value in disk_ids}) != len(disk_ids):
            raise self._invalid_shard_input(
                "模型配置文件名发生大小写折叠冲突。", "models/snapshots"
            )
        manifest_ids = manifest.configuration_snapshot_ids
        expected_ids = set(manifest_ids)
        if allowed_unindexed_id is not None:
            expected_ids.add(allowed_unindexed_id)
        unexpected = set(disk_ids) - expected_ids
        if unexpected:
            raise self._invalid_shard_input(
                "存在未被 Job 清单登记的模型配置快照。", "models/snapshots"
            )
        missing = set(manifest_ids) - set(disk_ids)
        if missing:
            missing_id = sorted(missing)[0]
            raise _repository_error(
                "job_shard_missing",
                "Job 清单引用的模型配置快照不存在。",
                "请恢复该快照或回到一致的 Job 清单。",
                f"models/snapshots/snapshot_{missing_id}.json",
            )
        return {
            snapshot_id: self._read_model_configuration(paths, snapshot_id)
            for snapshot_id in sorted(disk_ids)
        }

    def _read_task_invocations(
        self, paths: JobPaths, task_id: str
    ) -> tuple[ModelInvocationRecord, ...]:
        logical_path = f"models/invocations/task_{task_id}.jsonl"
        result = read_strict_jsonl(
            paths.task_invocations(task_id),
            logical_path=logical_path,
            parser=MODEL_INVOCATION_PARSER,
        )
        try:
            return require_canonical_task_invocations(task_id, result.records)
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "模型调用文件关系无效。", logical_path, exc
            ) from exc

    def _invocation_task_ids(self, paths: JobPaths) -> tuple[str, ...]:
        try:
            children = tuple(os.scandir(paths.invocations_dir))
        except OSError as exc:
            raise self._invalid_shard_input(
                "无法读取模型调用目录。", "models/invocations", exc
            ) from exc
        task_ids: list[str] = []
        for child in children:
            if child.name.startswith("."):
                continue
            if not child.name.startswith("task_") or not child.name.endswith(
                ".jsonl"
            ):
                continue
            raw_id = child.name[len("task_") : -len(".jsonl")]
            task_id = self._persisted_path_id(raw_id, "task_id")
            self._assert_safe_regular(
                Path(child.path),
                logical_path=f"models/invocations/{child.name}",
                missing_code="job_shard_missing",
                invalid_code="job_shard_invalid",
            )
            task_ids.append(task_id)
        if len({value.casefold() for value in task_ids}) != len(task_ids):
            raise self._invalid_shard_input(
                "模型调用文件名发生大小写折叠冲突。", "models/invocations"
            )
        return tuple(sorted(task_ids))

    def _validate_timeline_path_ids(self, timeline: DemoTimeline) -> None:
        round_ids = [
            self._persisted_path_id(value.round_id, "round_id")
            for value in timeline.rounds.rounds
        ]
        if len({value.casefold() for value in round_ids}) != len(round_ids):
            raise self._invalid_shard_input(
                "回合 ID 发生大小写折叠冲突。", "timeline/rounds.json"
            )

    def _read_demo_timeline(
        self,
        paths: JobPaths,
        *,
        expected_asset_id: str,
    ) -> DemoTimeline:
        descriptor = read_strict_json(
            paths.demo_timeline,
            logical_path="timeline/demo.json",
            parser=DEMO_DESCRIPTOR_PARSER,
        )
        rounds = read_strict_json(
            paths.timeline_rounds,
            logical_path="timeline/rounds.json",
            parser=ROUND_COLLECTION_PARSER,
        )
        anchors = read_strict_jsonl(
            paths.time_anchors,
            logical_path="timeline/time_anchors.jsonl",
            parser=TIME_ANCHOR_PARSER,
        ).records
        try:
            timeline = DemoTimeline(descriptor, rounds, anchors)
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "Demo 时间线分片无法组成有效时间线。", "timeline", exc
            ) from exc
        self._validate_timeline_path_ids(timeline)
        if timeline.descriptor.demo_asset_id != expected_asset_id:
            raise self._invalid_shard_input(
                "Demo 时间线与 Job 素材身份不一致。", "timeline/demo.json"
            )
        return timeline

    def _read_voice_activities(
        self,
        paths: JobPaths,
        *,
        required: bool,
    ) -> tuple[VoiceActivityCue, ...]:
        state = _lstat_optional(
            paths.voice_activities,
            logical_path="voice/activities.jsonl",
        )
        if state is None:
            if required:
                self._assert_safe_regular(
                    paths.voice_activities,
                    logical_path="voice/activities.jsonl",
                    missing_code="job_shard_missing",
                    invalid_code="job_shard_invalid",
                )
            return ()
        result = read_strict_jsonl(
            paths.voice_activities,
            logical_path="voice/activities.jsonl",
            parser=VOICE_ACTIVITY_PARSER,
        )
        try:
            return require_canonical_voice_activities(result.records)
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "语音活动文件关系无效。", "voice/activities.jsonl", exc
            ) from exc

    def _read_transcript_file(
        self,
        paths: JobPaths,
        round_id: str,
    ) -> tuple[TranscriptCue, ...]:
        logical_path = f"transcript/round_{round_id}.jsonl"
        result = read_strict_jsonl(
            paths.round_transcript(round_id),
            logical_path=logical_path,
            parser=TRANSCRIPT_CUE_PARSER,
        )
        try:
            return require_canonical_transcripts(
                result.records,
                round_id=round_id,
                logical_path=logical_path,
            )
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "回合转录文件关系无效。", logical_path, exc
            ) from exc

    def _read_unassigned_transcript(
        self,
        paths: JobPaths,
        *,
        required: bool,
    ) -> tuple[TranscriptCue, ...]:
        logical_path = "transcript/unassigned.jsonl"
        state = _lstat_optional(paths.unassigned_transcript(), logical_path=logical_path)
        if state is None:
            if required:
                self._assert_safe_regular(
                    paths.unassigned_transcript(),
                    logical_path=logical_path,
                    missing_code="job_shard_missing",
                    invalid_code="job_shard_invalid",
                )
            return ()
        result = read_strict_jsonl(
            paths.unassigned_transcript(),
            logical_path=logical_path,
            parser=TRANSCRIPT_CUE_PARSER,
        )
        try:
            return require_canonical_transcripts(
                result.records,
                round_id=None,
                logical_path=logical_path,
            )
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "未分配转录文件关系无效。", logical_path, exc
            ) from exc

    def _read_round_understanding(
        self,
        paths: JobPaths,
        round_id: str,
    ) -> RoundUnderstandingDocument:
        logical_path = f"understanding/round_{round_id}.json"
        value = read_strict_json(
            paths.round_understanding(round_id),
            logical_path=logical_path,
            parser=ROUND_UNDERSTANDING_PARSER,
        )
        if value.round_id != round_id:
            raise self._invalid_shard_input(
                "理解翻译文档与文件身份不一致。", logical_path
            )
        return value

    def _dynamic_path_ids(
        self,
        directory: Path,
        *,
        prefix: str,
        suffix: str,
        field: str,
        logical_directory: str,
    ) -> tuple[str, ...]:
        try:
            children = tuple(os.scandir(directory))
        except OSError as exc:
            raise self._invalid_shard_input(
                "无法读取 Job 分片目录。", logical_directory, exc
            ) from exc
        values: list[str] = []
        for child in children:
            if child.name.startswith("."):
                continue
            if not child.name.startswith(prefix) or not child.name.endswith(suffix):
                continue
            raw_id = child.name[len(prefix) : -len(suffix)]
            persisted_id = self._persisted_path_id(raw_id, field)
            self._assert_safe_regular(
                Path(child.path),
                logical_path=f"{logical_directory}/{child.name}",
                missing_code="job_shard_missing",
                invalid_code="job_shard_invalid",
            )
            values.append(persisted_id)
        if len({value.casefold() for value in values}) != len(values):
            raise self._invalid_shard_input(
                "分片文件名发生大小写折叠冲突。", logical_directory
            )
        return tuple(sorted(values))

    def _read_all_invocations_locked(
        self,
        paths: JobPaths,
        configurations: tuple[ModelConfigurationSnapshot, ...],
    ) -> tuple[ModelInvocationRecord, ...]:
        task_ids = self._invocation_task_ids(paths)
        values = tuple(
            record
            for task_id in task_ids
            for record in self._read_task_invocations(paths, task_id)
        )
        if len({value.invocation_id for value in values}) != len(values):
            raise self._invalid_shard_input(
                "不同任务文件中的模型调用 ID 重复。", "models/invocations"
            )
        configuration_ids = {value.snapshot_id for value in configurations}
        if any(
            value.configuration_snapshot_id not in configuration_ids
            for value in values
        ):
            raise self._invalid_shard_input(
                "模型调用引用了未注册的配置快照。", "models/invocations"
            )
        return values

    def _read_language_graph_locked(
        self,
        paths: JobPaths,
        manifest: JobManifest,
    ) -> LanguageGraph:
        timeline = self._read_demo_timeline(
            paths,
            expected_asset_id=manifest.demo_asset_id,
        )
        activities = self._read_voice_activities(paths, required=False)
        configuration_index = self._configuration_index(paths, manifest)
        configurations = tuple(
            configuration_index[snapshot_id]
            for snapshot_id in manifest.configuration_snapshot_ids
        )
        invocations = self._read_all_invocations_locked(paths, configurations)

        transcript_ids = self._dynamic_path_ids(
            paths.transcript_dir,
            prefix="round_",
            suffix=".jsonl",
            field="round_id",
            logical_directory="transcript",
        )
        authoritative_round_ids = tuple(
            value.round_id for value in timeline.rounds.rounds
        )
        unknown_transcript_ids = set(transcript_ids) - set(authoritative_round_ids)
        if unknown_transcript_ids:
            raise self._invalid_shard_input(
                "转录文件引用了未知回合。", "transcript"
            )
        transcripts = tuple(
            cue
            for round_id in authoritative_round_ids
            if round_id in transcript_ids
            for cue in self._read_transcript_file(paths, round_id)
        ) + self._read_unassigned_transcript(paths, required=False)
        if len({value.cue_id for value in transcripts}) != len(transcripts):
            raise self._invalid_shard_input(
                "不同转录文件中的提示 ID 重复。", "transcript"
            )

        understanding_ids = self._dynamic_path_ids(
            paths.understanding_dir,
            prefix="round_",
            suffix=".json",
            field="round_id",
            logical_directory="understanding",
        )
        unknown_understanding_ids = set(understanding_ids) - set(
            authoritative_round_ids
        )
        if unknown_understanding_ids:
            raise self._invalid_shard_input(
                "理解翻译文档引用了未知回合。", "understanding"
            )
        documents = tuple(
            self._read_round_understanding(paths, round_id)
            for round_id in authoritative_round_ids
            if round_id in understanding_ids
        )

        try:
            for activity in activities:
                validate_voice_activity_against_timeline(activity, timeline)
            for transcript in transcripts:
                validate_transcript_against_timeline(
                    transcript,
                    timeline,
                    activities,
                    configurations,
                    invocations,
                )
            for document in documents:
                validate_understanding_document_graph(
                    document,
                    transcripts,
                    configurations,
                    invocations,
                )
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "语言数据图引用关系无效。", "language_graph", exc
            ) from exc
        return LanguageGraph(
            timeline,
            activities,
            configurations,
            invocations,
            transcripts,
            documents,
        )

    def _validate_draft(
        self,
        draft: DraftCommsTimeline,
        language: LanguageGraph,
    ) -> None:
        try:
            validate_draft_timeline_graph(
                draft,
                language.timeline,
                language.transcripts,
                language.understanding_documents,
                language.configurations,
                language.invocations,
            )
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "Draft 通讯时间线与语言数据图不一致。",
                "final/timelines/draft.json",
                exc,
            ) from exc

    def _read_draft_timeline(
        self,
        paths: JobPaths,
        *,
        expected_asset_id: str,
    ) -> DraftCommsTimeline:
        logical_path = "final/timelines/draft.json"
        value = read_strict_json(
            paths.final_timelines_dir / "draft.json",
            logical_path=logical_path,
            parser=DRAFT_TIMELINE_PARSER,
        )
        if value.demo_asset_id != expected_asset_id:
            raise self._invalid_shard_input(
                "Draft 通讯时间线与 Job 素材身份不一致。", logical_path
            )
        return value

    def _read_validated_draft_locked(
        self,
        paths: JobPaths,
        manifest: JobManifest,
        language: LanguageGraph,
    ) -> DraftCommsTimeline:
        draft = self._read_draft_timeline(
            paths,
            expected_asset_id=manifest.demo_asset_id,
        )
        self._validate_draft(draft, language)
        return draft

    def _validate_review_bundle(
        self,
        timeline: DemoTimeline,
        draft: DraftCommsTimeline,
        revision: ReviewRevisionManifest,
        documents: tuple[RoundReviewDocument, ...],
        *,
        logical_path: str,
    ) -> ReviewRevisionBundle:
        document_ids = tuple(document.round_id for document in documents)
        if len({value.casefold() for value in document_ids}) != len(document_ids):
            raise self._invalid_shard_input(
                "复核版本中的回合文档 ID 重复。", logical_path
            )
        authoritative_ids = tuple(
            value.round_id for value in timeline.rounds.rounds
        )
        selected = set(document_ids)
        expected_order = tuple(
            round_id for round_id in authoritative_ids if round_id in selected
        )
        if (
            set(document_ids) - set(authoritative_ids)
            or revision.round_ids != expected_order
            or set(revision.round_ids) != set(document_ids)
        ):
            raise self._invalid_shard_input(
                "复核版本回合顺序与 Demo 时间线不一致。", logical_path
            )
        if revision.source_draft_fingerprint != draft.content_fingerprint():
            raise self._invalid_shard_input(
                "复核版本引用了不同的 Draft 时间线。", logical_path
            )
        by_round = {document.round_id: document for document in documents}
        ordered = tuple(by_round[round_id] for round_id in revision.round_ids)
        decision_ids: list[str] = []
        try:
            for document in ordered:
                if (
                    document.review_id != revision.review_id
                    or document.source_draft_fingerprint
                    != revision.source_draft_fingerprint
                ):
                    raise self._invalid_shard_input(
                        "复核回合文档与版本清单身份不一致。",
                        f"{logical_path}/round_{document.round_id}.json",
                    )
                round_cues = tuple(
                    cue for cue in draft.cues if cue.round_id == document.round_id
                )
                selected_draft = DraftCommsTimeline(
                    draft.demo_asset_id,
                    draft.timebase,
                    draft.input_fingerprint,
                    round_cues,
                )
                compose_reviewed_timeline(selected_draft, document.decisions)
                decision_ids.extend(
                    decision.decision_id for decision in document.decisions
                )
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "复核决策与 Draft 回合内容不一致。", logical_path, exc
            ) from exc
        if len({value.casefold() for value in decision_ids}) != len(decision_ids):
            raise self._invalid_shard_input(
                "复核版本中的决策 ID 重复。", logical_path
            )
        return ReviewRevisionBundle(revision, ordered)

    def _read_review_revision_directory(
        self,
        directory: Path,
        *,
        logical_directory: str,
        expected_review_id: str,
        timeline: DemoTimeline,
        draft: DraftCommsTimeline,
    ) -> ReviewRevisionBundle:
        try:
            state = os.lstat(directory)
        except FileNotFoundError as exc:
            raise _repository_error(
                "job_shard_missing",
                "复核版本目录不存在。",
                "请恢复该复核版本。",
                logical_directory,
                exc,
            ) from exc
        except OSError as exc:
            raise self._invalid_shard_input(
                "无法检查复核版本目录。", logical_directory, exc
            ) from exc
        if _is_link_or_reparse(state) or not stat.S_ISDIR(state.st_mode):
            raise self._invalid_shard_input(
                "复核版本路径不是安全目录。", logical_directory
            )
        revision_path = directory / "revision.json"
        revision = read_strict_json(
            revision_path,
            logical_path=f"{logical_directory}/revision.json",
            parser=REVIEW_REVISION_PARSER,
        )
        if revision.review_id != expected_review_id:
            raise self._invalid_shard_input(
                "复核版本目录与清单身份不一致。",
                f"{logical_directory}/revision.json",
            )
        try:
            children = tuple(os.scandir(directory))
        except OSError as exc:
            raise self._invalid_shard_input(
                "无法读取复核版本目录。", logical_directory, exc
            ) from exc
        round_ids: list[str] = []
        for child in children:
            if child.name == "revision.json":
                continue
            if not child.name.startswith("round_") or not child.name.endswith(
                ".json"
            ):
                raise self._invalid_shard_input(
                    "复核版本目录包含未声明文件。",
                    f"{logical_directory}/{child.name}",
                )
            raw_id = child.name[len("round_") : -len(".json")]
            round_id = self._persisted_path_id(raw_id, "round_id")
            self._assert_safe_regular(
                Path(child.path),
                logical_path=f"{logical_directory}/{child.name}",
                missing_code="job_shard_missing",
                invalid_code="job_shard_invalid",
            )
            round_ids.append(round_id)
        if len({value.casefold() for value in round_ids}) != len(round_ids):
            raise self._invalid_shard_input(
                "复核回合文件名发生大小写折叠冲突。", logical_directory
            )
        missing = set(revision.round_ids) - set(round_ids)
        if missing:
            missing_id = next(
                value for value in revision.round_ids if value in missing
            )
            raise _repository_error(
                "job_shard_missing",
                "复核版本声明的回合文档不存在。",
                "请恢复该回合文档。",
                f"{logical_directory}/round_{missing_id}.json",
            )
        if set(round_ids) - set(revision.round_ids):
            raise self._invalid_shard_input(
                "复核版本目录包含未声明的回合文档。", logical_directory
            )
        documents = tuple(
            read_strict_json(
                directory / f"round_{round_id}.json",
                logical_path=f"{logical_directory}/round_{round_id}.json",
                parser=ROUND_REVIEW_PARSER,
            )
            for round_id in revision.round_ids
        )
        return self._validate_review_bundle(
            timeline,
            draft,
            revision,
            documents,
            logical_path=logical_directory,
        )

    def _read_review_revision_locked(
        self,
        paths: JobPaths,
        manifest: JobManifest,
        review_id: str,
    ) -> ReviewRevisionBundle:
        language = self._read_language_graph_locked(paths, manifest)
        draft = self._read_validated_draft_locked(paths, manifest, language)
        return self._read_review_revision_directory(
            paths.review_revision(review_id),
            logical_directory=f"review/revisions/review_{review_id}",
            expected_review_id=review_id,
            timeline=language.timeline,
            draft=draft,
        )

    def _new_review_staging_path(
        self,
        paths: JobPaths,
        review_id: str,
    ) -> Path:
        try:
            value = self.staging_id_factory()
        except Exception as exc:
            raise _repository_error(
                "job_write_failed",
                "无法生成复核版本 staging 标识。",
                "请重试发布复核版本。",
                "review/revisions",
                exc,
            ) from exc
        if not isinstance(value, UUID):
            raise _repository_error(
                "job_write_failed",
                "复核版本 staging 标识无效。",
                "请修复 staging ID 配置。",
                "review/revisions",
            )
        return (
            paths.review_revisions_dir
            / f".review_{review_id}.{value.hex}.staging"
        )

    def _publish_review_revision(
        self,
        paths: JobPaths,
        bundle: ReviewRevisionBundle,
    ) -> None:
        review_id = bundle.revision.review_id
        target = paths.review_revision(review_id)
        logical_directory = f"review/revisions/review_{review_id}"
        staging = self._new_review_staging_path(paths, review_id)
        staging_identity: tuple[int, int] | None = None
        try:
            try:
                os.mkdir(staging, 0o700)
            except OSError as exc:
                raise _repository_error(
                    "job_write_failed",
                    "无法创建复核版本 staging 目录。",
                    "请检查磁盘空间和目录权限。",
                    logical_directory,
                    exc,
                ) from exc
            staging_state = os.lstat(staging)
            if _is_link_or_reparse(staging_state) or not stat.S_ISDIR(
                staging_state.st_mode
            ):
                raise _repository_error(
                    "job_path_escape",
                    "复核版本 staging 目录不安全。",
                    "请检查 review/revisions 目录。",
                    logical_directory,
                )
            staging_identity = (staging_state.st_dev, staging_state.st_ino)
            atomic_write_json(
                staging / "revision.json",
                bundle.revision,
                logical_path=f"{logical_directory}/revision.json",
                serializer=lambda value: value.to_dict(),
                parser=REVIEW_REVISION_PARSER,
            )
            for document in bundle.round_documents:
                atomic_write_json(
                    staging / f"round_{document.round_id}.json",
                    document,
                    logical_path=(
                        f"{logical_directory}/round_{document.round_id}.json"
                    ),
                    serializer=lambda value: value.to_dict(),
                    parser=ROUND_REVIEW_PARSER,
                )
            _fsync_metadata_directory(
                staging,
                logical_directory,
                expected_identity=staging_identity,
            )
            if _lstat_optional(target, logical_path=logical_directory) is not None:
                raise self._invalid_shard_input(
                    "同一复核版本 ID 已存在。", logical_directory
                )
            parent_identity = _rename_directory_no_replace(
                staging,
                target,
                expected_source_identity=staging_identity,
                logical_path=logical_directory,
            )
            published_state = os.lstat(target)
            if (
                _is_link_or_reparse(published_state)
                or not stat.S_ISDIR(published_state.st_mode)
                or (published_state.st_dev, published_state.st_ino)
                != staging_identity
            ):
                raise _repository_error(
                    "job_path_escape",
                    "复核版本目录在发布期间发生变化。",
                    "请停止其他程序修改该 Job 后检查复核历史。",
                    logical_directory,
                )
            _fsync_metadata_directory(
                paths.review_revisions_dir,
                "review/revisions",
                expected_identity=parent_identity,
            )
        finally:
            if staging_identity is not None:
                self._cleanup_owned_review_staging(
                    staging,
                    staging_identity,
                    sys.exc_info()[1],
                )

    def _cleanup_owned_review_staging(
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
                primary.add_note(
                    f"review staging cleanup check failed: {type(exc).__name__}"
                )
                return
            raise _repository_error(
                "job_write_failed",
                "无法检查复核版本 staging 目录。",
                "请检查 review/revisions 中的隐藏 staging。",
                "review/revisions",
                exc,
            ) from exc
        safe = (
            not _is_link_or_reparse(current)
            and stat.S_ISDIR(current.st_mode)
            and (current.st_dev, current.st_ino) == identity
        )
        if not safe:
            if primary is not None:
                primary.add_note(
                    "review staging cleanup skipped because ownership changed"
                )
                return
            raise _repository_error(
                "job_path_escape",
                "复核版本 staging 目录所有权发生变化。",
                "请检查 review/revisions 中的隐藏 staging。",
                "review/revisions",
            )
        try:
            shutil.rmtree(staging)
        except OSError as exc:
            if primary is not None:
                primary.add_note(
                    f"review staging cleanup failed: {type(exc).__name__}"
                )
                return
            raise _repository_error(
                "job_write_failed",
                "无法清理复核版本 staging 目录。",
                "请检查 review/revisions 中的隐藏 staging。",
                "review/revisions",
                exc,
            ) from exc

    def _read_active_review_locked(
        self,
        paths: JobPaths,
        manifest: JobManifest,
    ) -> ReviewRevisionBundle:
        if manifest.active_review_id is None:
            raise _repository_error(
                "job_shard_missing",
                "Job 尚未激活复核版本。",
                "请先完整发布并激活一个复核版本。",
                "job.json",
            )
        return self._read_review_revision_locked(
            paths,
            manifest,
            manifest.active_review_id,
        )

    def _review_decisions(
        self,
        bundle: ReviewRevisionBundle,
    ) -> tuple:
        return tuple(
            decision
            for document in bundle.round_documents
            for decision in document.decisions
        )

    def _validate_reviewed(
        self,
        reviewed: ReviewedCommsTimeline,
        language: LanguageGraph,
        draft: DraftCommsTimeline,
        active: ReviewRevisionBundle,
    ) -> None:
        try:
            validate_reviewed_timeline_graph(
                reviewed,
                draft,
                language.timeline,
                self._review_decisions(active),
            )
        except DomainSchemaError as exc:
            raise self._invalid_shard_input(
                "Reviewed 通讯时间线与活动复核版本不一致。",
                "final/timelines/reviewed.json",
                exc,
            ) from exc

    def _read_reviewed_timeline(
        self,
        paths: JobPaths,
        *,
        expected_asset_id: str,
    ) -> ReviewedCommsTimeline:
        logical_path = "final/timelines/reviewed.json"
        value = read_strict_json(
            paths.final_timelines_dir / "reviewed.json",
            logical_path=logical_path,
            parser=REVIEWED_TIMELINE_PARSER,
        )
        if value.demo_asset_id != expected_asset_id:
            raise self._invalid_shard_input(
                "Reviewed 通讯时间线与 Job 素材身份不一致。", logical_path
            )
        return value

    def _read_validated_reviewed_locked(
        self,
        paths: JobPaths,
        language: LanguageGraph,
        draft: DraftCommsTimeline,
        active: ReviewRevisionBundle,
    ) -> ReviewedCommsTimeline:
        reviewed = self._read_reviewed_timeline(
            paths,
            expected_asset_id=language.timeline.descriptor.demo_asset_id,
        )
        self._validate_reviewed(reviewed, language, draft, active)
        return reviewed

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
        blocked_directories: set[str] = set()
        for relative in _INITIAL_DIRECTORIES:
            directory = paths.job_dir.joinpath(*relative.split("/"))
            try:
                self._assert_safe_directory_chain(
                    directory,
                    logical_path=relative,
                    missing_code="job_shard_missing",
                    invalid_code="job_shard_invalid",
                )
            except JobRepositoryError as exc:
                blocked_directories.add(relative)
                self._append_issue(issues, exc.to_issue())

        for issue in self._inspect_optional_files(
            paths, blocked_directories=frozenset(blocked_directories)
        ):
            self._append_issue(issues, issue)

        required_files = [(paths.event_journal, "events/job_events.jsonl")]
        if not write_lock_already_held:
            required_files.insert(0, (paths.write_lock, "events/.write.lock"))
        for path, logical_path in required_files:
            if self._logical_path_is_blocked(logical_path, blocked_directories):
                continue
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

    def _inspect_optional_files(
        self,
        paths: JobPaths,
        *,
        blocked_directories: frozenset[str] = frozenset(),
    ) -> tuple[JobIssue, ...]:
        issues: list[JobIssue] = []
        for relative in _OPTIONAL_EXACT_FILES:
            if self._logical_path_is_blocked(relative, blocked_directories):
                continue
            path = paths.job_dir.joinpath(*relative.split("/"))
            try:
                self._assert_safe_parent_chain(
                    path,
                    logical_path=relative,
                    missing_code="job_shard_missing",
                    invalid_code="job_shard_invalid",
                )
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
            if self._logical_path_is_blocked(
                relative_dir, blocked_directories
            ):
                continue
            directory = paths.job_dir.joinpath(*relative_dir.split("/"))
            try:
                self._assert_safe_directory_chain(
                    directory,
                    logical_path=relative_dir,
                    missing_code="job_shard_missing",
                    invalid_code="job_shard_invalid",
                )
                children = tuple(os.scandir(directory))
            except JobRepositoryError as exc:
                self._append_issue(issues, exc.to_issue())
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
        if self._logical_path_is_blocked(
            "review/revisions", blocked_directories
        ):
            return tuple(issues)
        try:
            self._assert_safe_directory_chain(
                revisions,
                logical_path="review/revisions",
                missing_code="job_shard_missing",
                invalid_code="job_shard_invalid",
            )
            revision_children = tuple(os.scandir(revisions))
        except JobRepositoryError as exc:
            self._append_issue(issues, exc.to_issue())
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
                self._assert_safe_parent_chain(
                    path,
                    logical_path=logical_path,
                    missing_code="job_shard_missing",
                    invalid_code="job_shard_invalid",
                )
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
        self._assert_safe_parent_chain(
            path,
            logical_path=logical_path,
            missing_code=missing_code,
            invalid_code=invalid_code,
        )
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

    @staticmethod
    def _logical_path_is_blocked(
        logical_path: str, blocked_directories: set[str] | frozenset[str]
    ) -> bool:
        return any(
            logical_path == directory
            or logical_path.startswith(f"{directory}/")
            for directory in blocked_directories
        )

    def _assert_safe_parent_chain(
        self,
        path: Path,
        *,
        logical_path: str,
        missing_code: str,
        invalid_code: str,
    ) -> None:
        self._assert_safe_directory_chain(
            path.parent,
            logical_path=logical_path,
            missing_code=missing_code,
            invalid_code=invalid_code,
        )

    def _assert_safe_directory_chain(
        self,
        directory: Path,
        *,
        logical_path: str,
        missing_code: str,
        invalid_code: str,
    ) -> None:
        try:
            relative = directory.relative_to(self.paths.jobs_dir)
        except ValueError as exc:
            raise _repository_error(
                "job_path_escape",
                "Job 路径超出当前工作区。",
                "请恢复工作区内的普通目录后重试。",
                logical_path,
                exc,
            ) from exc
        candidates = [self.paths.jobs_dir]
        current = self.paths.jobs_dir
        for part in relative.parts:
            current /= part
            candidates.append(current)
        for candidate in candidates:
            try:
                result = os.lstat(candidate)
            except FileNotFoundError as exc:
                raise _repository_error(
                    missing_code,
                    "Job 文件的父目录不存在。",
                    "请检查或恢复该 Job。",
                    logical_path,
                    exc,
                ) from exc
            except OSError as exc:
                raise _repository_error(
                    invalid_code,
                    "无法检查 Job 文件的父目录。",
                    "请检查该 Job。",
                    logical_path,
                    exc,
                ) from exc
            if _is_link_or_reparse(result):
                raise _repository_error(
                    "job_path_escape",
                    "Job 文件的父目录包含链接或重解析点。",
                    "请恢复普通目录后重试。",
                    logical_path,
                )
            if not stat.S_ISDIR(result.st_mode):
                raise _repository_error(
                    invalid_code,
                    "Job 文件的父路径不是目录。",
                    "请恢复普通目录后重试。",
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
