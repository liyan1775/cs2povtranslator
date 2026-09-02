from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import os
from pathlib import Path
import shutil
import stat
import sys
from uuid import UUID, uuid4

from cs2pov.domain.errors import DomainSchemaError
from cs2pov.domain.job import (
    CreateJobRequest,
    JobDemoSource,
    JobManifest,
    JobPhase,
    JobRepositoryMarker,
    JobRunStatus,
    RoundProgressSummary,
)
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


def _lstat_optional(path: Path) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except FileNotFoundError:
        return None


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
        return OpenedJob(marker, manifest, source, paths, manifest.run_status)

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
