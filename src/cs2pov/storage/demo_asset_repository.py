from __future__ import annotations

from datetime import datetime, timezone
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat as stat_module
from typing import Callable
from uuid import UUID, uuid4

from cs2pov.adapters.zstandard_adapter import DemoCompressionError, ZstandardDemoAdapter
from cs2pov.domain.assets import DemoAsset, DemoAssetInspection, DemoAssetRef, DemoAssetSummary, DemoImportResult
from cs2pov.workspace.paths import WorkspacePaths


class DemoAssetRepositoryError(RuntimeError):
    def __init__(self, code: str, message_zh: str, suggestion_zh: str) -> None:
        self.code = code
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh
        super().__init__(message_zh)


def _error(code: str) -> DemoAssetRepositoryError:
    messages = {
        "demo_source_required": ("请提供一个 Demo 源文件。", "请选择 .dem 文件后重试。"),
        "demo_source_not_found": ("找不到 Demo 源文件。", "请确认文件仍存在后重试。"),
        "demo_source_not_file": ("Demo 源不是普通文件。", "请选择一个普通 .dem 文件。"),
        "demo_source_format_unsupported": ("Demo 源格式暂不支持。", "请选择 .dem 或 .dem.zst 文件。"),
        "demo_source_empty": ("Demo 源文件为空。", "请选择包含内容的 .dem 文件。"),
        "demo_source_unreadable": ("无法读取 Demo 源文件。", "请检查文件权限后重试。"),
        "demo_source_changed": ("导入期间 Demo 源文件发生变化。", "请停止其他程序对该文件的修改后重试。"),
        "demo_decompression_failed": ("无法解压 Demo 源文件。", "请确认 .dem.zst 文件完整后重试。"),
        "demo_asset_path_escape": ("素材库路径超出当前工作区。", "请修复工作区目录后重试。"),
        "demo_asset_integrity_failed": ("已有 Demo 素材完整性校验失败。", "请保留现有素材并按 inspect 结果处理。"),
        "demo_asset_manifest_invalid": ("Demo 素材 manifest 无效。", "请检查该素材后再导入。"),
        "demo_asset_commit_failed": ("Demo 素材原子提交失败。", "请检查工作区权限和磁盘空间后重试。"),
        "demo_import_space_insufficient": ("工作区磁盘空间不足。", "请释放工作区所在磁盘空间后重试。"),
        "demo_cache_rebuild_failed": ("Demo 解压缓存重建失败。", "请检查工作区空间和权限后重试。"),
        "demo_asset_id_invalid": ("Demo 素材 ID 无效。", "请使用完整的 64 位小写 SHA-256。"),
        "demo_asset_not_found": ("当前工作区找不到该 Demo 素材。", "请切回原工作区或重新导入 Demo。"),
    }
    message, suggestion = messages[code]
    return DemoAssetRepositoryError(code, message, suggestion)


def _is_link(path: Path) -> bool:
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        attributes = 0
    reparse_point = getattr(stat_module, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(attributes & reparse_point)


def _normalize_display_name(value: str) -> str:
    normalized = "".join(
        "_" if char in {"/", "\\"} or ord(char) < 32 or ord(char) == 127 else char
        for char in value
    ).strip()
    normalized = normalized[:255].strip()
    return normalized or "demo.dem"


class FileSystemDemoAssetRepository:
    def __init__(
        self,
        paths: WorkspacePaths,
        *,
        decompressor: ZstandardDemoAdapter | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        id_factory: Callable[[], UUID] = uuid4,
        chunk_size: int = 1024 * 1024,
    ) -> None:
        if not isinstance(paths, WorkspacePaths):
            raise TypeError("paths 必须是 WorkspacePaths。")
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size <= 0:
            raise ValueError("chunk_size 必须是正整数。")
        if not callable(clock) or not callable(id_factory):
            raise TypeError("clock 和 id_factory 必须可调用。")
        self.paths = paths
        self.decompressor = decompressor or ZstandardDemoAdapter()
        self.clock = clock
        self.id_factory = id_factory
        self.chunk_size = chunk_size

    def import_source(self, source: str | Path | None) -> DemoImportResult:
        source_path = self._validate_source(source)
        source_format = self._source_format(source_path)
        self._validate_managed_roots()
        before = self._source_stat(source_path)
        if before[0] == 0:
            raise _error("demo_source_empty")

        staging_root: Path | None = None
        try:
            self.paths.demo_library_dir.mkdir(parents=True, exist_ok=True)
            imports_root = self.paths.temp_dir / "demo_imports"
            imports_root.mkdir(parents=True, exist_ok=True)
            staging_root = self._make_staging_root(imports_root)
            staging_asset = staging_root / "asset"
            staging_asset.mkdir()
            staged_source = staging_asset / ("source.dem.zst" if source_format == "dem.zst" else "source.dem")
            if source_format == "dem.zst":
                logical_path = staging_root / "logical.dem"
                source_hash, source_size, logical_hash, logical_size = self._copy_zst(
                    source_path, staged_source, logical_path
                )
            else:
                logical_path = None
                logical_hash, logical_size = self._copy_dem(source_path, staged_source)
                source_hash, source_size = logical_hash, logical_size
            if self._source_stat(source_path) != before:
                raise _error("demo_source_changed")

            asset_id = logical_hash
            imported_at = self._imported_at()
            asset = DemoAsset(
                schema_version=1,
                asset_id=asset_id,
                logical_sha256=logical_hash,
                logical_size_bytes=logical_size,
                source_sha256=source_hash,
                source_size_bytes=source_size,
                source_format=source_format,
                source_relative_path=f"library/demos/{asset_id}/source.{source_format}",
                display_name=_normalize_display_name(source_path.name),
                imported_at=imported_at,
            )
            manifest = staging_asset / "asset.json"
            manifest_tmp = staging_asset / ".asset.json.tmp"
            manifest_tmp.write_text(
                json.dumps(asset.to_dict(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(manifest_tmp, manifest)
            persistent_bytes = staged_source.stat().st_size + manifest.stat().st_size
            imported_result = DemoImportResult(asset, "imported", persistent_bytes)
            final_asset = self.paths.demo_library_dir / asset_id
            self._validate_final_target(final_asset)
            if final_asset.exists() or final_asset.is_symlink():
                existing = self._load_asset(final_asset)
                if existing.asset_id != asset_id:
                    raise _error("demo_asset_integrity_failed")
                self._repair_existing_cache_from_candidate(
                    existing,
                    logical_path if logical_path is not None else staged_source,
                    staging_root,
                )
                return DemoImportResult(existing, "reused", 0)
            try:
                staging_asset.rename(final_asset)
            except OSError as exc:
                if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                    raise
                existing = self._load_asset(final_asset)
                self._repair_existing_cache_from_candidate(
                    existing,
                    logical_path if logical_path is not None else staged_source,
                    staging_root,
                )
                return DemoImportResult(existing, "reused", 0)
            if logical_path is not None:
                self._commit_cache(logical_path, asset_id, staging_root, logical_size)
            return imported_result
        except DemoAssetRepositoryError:
            raise
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise _error("demo_import_space_insufficient") from exc
            raise _error("demo_asset_commit_failed") from exc
        finally:
            if staging_root is not None:
                self._cleanup_staging(staging_root)

    def _repair_existing_cache_from_candidate(
        self,
        existing: DemoAsset,
        logical_candidate: Path,
        staging_root: Path,
    ) -> None:
        if existing.source_format != "dem.zst" or self._cache_status(existing) == "valid":
            return
        self._commit_cache(
            logical_candidate,
            existing.asset_id,
            staging_root,
            existing.logical_size_bytes,
        )

    def list_assets(self) -> tuple[DemoAssetSummary, ...]:
        self._validate_managed_directory(self.paths.demo_library_dir)
        library = self.paths.demo_library_dir
        if not library.exists():
            return ()
        summaries: list[DemoAssetSummary] = []
        for candidate in library.iterdir():
            if candidate.name.startswith("_") or not re.fullmatch(r"[0-9a-f]{64}", candidate.name):
                continue
            if _is_link(candidate) or not candidate.is_dir():
                continue
            try:
                asset = self._load_asset(candidate)
            except DemoAssetRepositoryError as exc:
                asset = None
                try:
                    asset = self._read_manifest(candidate)
                except DemoAssetRepositoryError:
                    pass
                summaries.append(self._summary_for(candidate.name, asset, healthy=False, issue_code=exc.code))
            else:
                summaries.append(self._summary_for(asset.asset_id, asset, healthy=True, issue_code=None))
        summaries.sort(key=lambda item: (item.imported_at is None, item.imported_at or "", item.asset_id))
        return tuple(summaries)

    def inspect_asset(self, asset_id: str) -> DemoAssetInspection:
        self._validate_asset_id(asset_id)
        asset_dir = self.paths.demo_library_dir / asset_id
        self._validate_managed_directory(self.paths.demo_library_dir)
        if _is_link(asset_dir):
            raise _error("demo_asset_path_escape")
        if not asset_dir.exists() or not asset_dir.is_dir():
            raise _error("demo_asset_not_found")
        asset = self._read_manifest(asset_dir)
        try:
            self._validate_asset_files(asset_dir, asset)
        except DemoAssetRepositoryError as exc:
            if exc.code == "demo_asset_path_escape":
                raise
            cache_status = "not_applicable" if asset.source_format == "dem" else self._cache_status(asset)
            return DemoAssetInspection(asset, False, cache_status, ("demo_asset_integrity_failed",))
        return DemoAssetInspection(asset, True, self._cache_status(asset), ())

    def resolve_asset(self, ref: DemoAssetRef) -> Path:
        if not isinstance(ref, DemoAssetRef):
            raise _error("demo_asset_id_invalid")
        inspection = self.inspect_asset(ref.asset_id)
        if not inspection.ok:
            raise _error("demo_asset_integrity_failed")
        asset = inspection.asset
        if asset.source_format == "dem":
            return self.paths.demo_library_dir / ref.asset_id / "source.dem"
        cache = self._cache_path(ref.asset_id)
        if inspection.cache_status == "valid":
            return cache
        staging_root: Path | None = None
        try:
            self._validate_managed_roots()
            staging_root = self._make_staging_root(self.paths.temp_dir / "demo_imports")
            logical_path = staging_root / "logical.dem"
            source_path = self.paths.root / asset.source_relative_path
            self._decompress_to_path(source_path, logical_path)
            self._commit_cache(logical_path, ref.asset_id, staging_root, asset.logical_size_bytes)
            return cache
        except DemoAssetRepositoryError:
            raise
        except OSError as exc:
            raise _error("demo_cache_rebuild_failed") from exc
        finally:
            if staging_root is not None:
                self._cleanup_staging(staging_root)

    def _validate_source(self, source: str | Path | None) -> Path:
        if source is None or (isinstance(source, str) and not source.strip()):
            raise _error("demo_source_required")
        try:
            candidate = Path(source).expanduser()
            if _is_link(candidate):
                raise _error("demo_source_not_file")
            resolved = candidate.resolve(strict=False)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            raise _error("demo_source_not_found") from exc
        if _is_link(resolved) or not resolved.exists():
            if not resolved.exists():
                raise _error("demo_source_not_found")
            raise _error("demo_source_not_file")
        if not resolved.is_file():
            raise _error("demo_source_not_file")
        lower_name = resolved.name.lower()
        if not (lower_name.endswith(".dem") or lower_name.endswith(".dem.zst")):
            raise _error("demo_source_format_unsupported")
        for managed in (self.paths.demo_library_dir, self.paths.temp_dir):
            try:
                resolved.relative_to(managed.resolve())
            except (OSError, RuntimeError, ValueError):
                continue
            raise _error("demo_source_not_file")
        return resolved

    @staticmethod
    def _source_format(source: Path) -> str:
        return "dem.zst" if source.name.lower().endswith(".dem.zst") else "dem"

    def _validate_managed_roots(self) -> None:
        for path in (self.paths.demo_library_dir, self.paths.temp_dir, self.paths.decompressed_demos_cache_dir):
            self._validate_managed_directory(path)

    def _validate_managed_directory(self, path: Path) -> None:
        root = self.paths.root
        try:
            relative = path.absolute().relative_to(root)
        except ValueError as exc:
            raise _error("demo_asset_path_escape") from exc
        current = root
        for part in relative.parts:
            current /= part
            if current.exists() or current.is_symlink():
                if _is_link(current) or not current.is_dir():
                    raise _error("demo_asset_path_escape")
                try:
                    current.resolve(strict=False).relative_to(root.resolve())
                except (OSError, RuntimeError, ValueError) as exc:
                    raise _error("demo_asset_path_escape") from exc

    def _validate_final_target(self, path: Path) -> None:
        self._validate_managed_directory(path.parent)
        if _is_link(path):
            raise _error("demo_asset_path_escape")

    def _make_staging_root(self, imports_root: Path) -> Path:
        try:
            staging_id = self.id_factory()
        except Exception:
            raise
        if not isinstance(staging_id, UUID):
            raise TypeError("id_factory 必须返回 UUID。")
        staging_root = imports_root / str(staging_id)
        self._validate_managed_directory(imports_root)
        staging_root.mkdir()
        return staging_root

    def _cleanup_staging(self, staging_root: Path) -> None:
        imports_root = self.paths.temp_dir / "demo_imports"
        try:
            staging_root.resolve(strict=False).relative_to(imports_root.resolve(strict=False))
        except (OSError, RuntimeError, ValueError):
            return
        if _is_link(staging_root) or not staging_root.is_dir():
            return
        shutil.rmtree(staging_root, ignore_errors=True)

    def _copy_dem(self, source: Path, destination: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        try:
            src = source.open("rb")
        except OSError as exc:
            raise _error("demo_source_unreadable") from exc
        try:
            dst = destination.open("wb")
        except OSError as exc:
            src.close()
            if exc.errno == errno.ENOSPC:
                raise _error("demo_import_space_insufficient") from exc
            raise _error("demo_asset_commit_failed") from exc
        try:
            with src, dst:
                while True:
                    try:
                        chunk = src.read(self.chunk_size)
                    except OSError as exc:
                        raise _error("demo_source_unreadable") from exc
                    if not chunk:
                        break
                    digest.update(chunk)
                    try:
                        dst.write(chunk)
                    except OSError as exc:
                        if exc.errno == errno.ENOSPC:
                            raise _error("demo_import_space_insufficient") from exc
                        raise _error("demo_asset_commit_failed") from exc
                    size += len(chunk)
        except DemoAssetRepositoryError:
            raise
        return digest.hexdigest(), size

    def _copy_zst(self, source: Path, destination: Path, logical_destination: Path) -> tuple[str, int, str, int]:
        source_hash, source_size = self._copy_dem(source, destination)
        logical_digest = hashlib.sha256()
        logical_size = 0
        try:
            with destination.open("rb") as compressed, logical_destination.open("wb") as logical:
                for chunk in self.decompressor.iter_decompressed(compressed, chunk_size=self.chunk_size):
                    logical_digest.update(chunk)
                    logical.write(chunk)
                    logical_size += len(chunk)
        except DemoCompressionError as exc:
            raise _error("demo_decompression_failed") from exc
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise _error("demo_import_space_insufficient") from exc
            raise _error("demo_asset_commit_failed") from exc
        if logical_size == 0:
            raise _error("demo_source_empty")
        return source_hash, source_size, logical_digest.hexdigest(), logical_size

    @staticmethod
    def _source_stat(source: Path) -> tuple[int, int, int | None, int | None]:
        try:
            stat = source.stat()
        except OSError as exc:
            raise _error("demo_source_unreadable") from exc
        return stat.st_size, stat.st_mtime_ns, getattr(stat, "st_dev", None), getattr(stat, "st_ino", None)

    def _imported_at(self) -> str:
        value = self.clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise TypeError("clock 必须返回带 UTC 时区的 datetime。")
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    def _load_asset(self, asset_dir: Path) -> DemoAsset:
        if _is_link(asset_dir) or not asset_dir.is_dir():
            raise _error("demo_asset_path_escape")
        try:
            relative = asset_dir.resolve().relative_to(self.paths.demo_library_dir.resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise _error("demo_asset_path_escape") from exc
        if len(relative.parts) != 1:
            raise _error("demo_asset_path_escape")
        asset = self._read_manifest(asset_dir)
        self._validate_asset_files(asset_dir, asset)
        return asset

    def _read_manifest(self, asset_dir: Path) -> DemoAsset:
        manifest_path = asset_dir / "asset.json"
        if _is_link(manifest_path) or not manifest_path.is_file():
            raise _error("demo_asset_manifest_invalid")
        try:
            manifest = json.loads(manifest_path.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise _error("demo_asset_manifest_invalid") from exc
        if isinstance(manifest, dict):
            raw_relative = manifest.get("source_relative_path")
            if isinstance(raw_relative, str) and (".." in raw_relative.split("/") or raw_relative.startswith(("/", "\\")) or ":" in raw_relative):
                raise _error("demo_asset_path_escape")
        try:
            return DemoAsset.from_dict(manifest)
        except (TypeError, ValueError) as exc:
            raise _error("demo_asset_manifest_invalid") from exc

    def _validate_asset_files(self, asset_dir: Path, asset: DemoAsset) -> Path:
        if asset.asset_id != asset_dir.name:
            raise _error("demo_asset_integrity_failed")
        raw_source = self.paths.root / asset.source_relative_path
        if _is_link(raw_source):
            raise _error("demo_asset_path_escape")
        try:
            source = raw_source.resolve(strict=False)
            expected_source = (asset_dir / f"source.{asset.source_format}").resolve()
        except (OSError, RuntimeError) as exc:
            raise _error("demo_asset_path_escape") from exc
        if source != expected_source:
            raise _error("demo_asset_path_escape")
        if not raw_source.is_file():
            raise _error("demo_asset_integrity_failed")
        source_hash, source_size = self._hash_stream(source)
        if source_hash != asset.source_sha256 or source_size != asset.source_size_bytes:
            raise _error("demo_asset_integrity_failed")
        if asset.source_format == "dem" and (
            source_hash != asset.logical_sha256 or source_size != asset.logical_size_bytes or source_hash != asset.asset_id
        ):
            raise _error("demo_asset_integrity_failed")
        if asset.source_format == "dem.zst":
            logical_hash, logical_size = self._hash_decompressed_source(source)
            if logical_hash != asset.logical_sha256 or logical_size != asset.logical_size_bytes:
                raise _error("demo_asset_integrity_failed")
        children = {child.name for child in asset_dir.iterdir()}
        if children != {"asset.json", f"source.{asset.source_format}"}:
            raise _error("demo_asset_integrity_failed")
        return source

    def _cache_path(self, asset_id: str) -> Path:
        self._validate_asset_id(asset_id)
        return self.paths.decompressed_demos_cache_dir / f"{asset_id}.dem"

    def _cache_status(self, asset: DemoAsset) -> str:
        if asset.source_format == "dem":
            return "not_applicable"
        cache = self._cache_path(asset.asset_id)
        self._validate_managed_directory(self.paths.decompressed_demos_cache_dir)
        if _is_link(cache):
            raise _error("demo_asset_path_escape")
        if not cache.exists():
            return "missing"
        if not cache.is_file():
            raise _error("demo_asset_path_escape")
        try:
            cache_hash, cache_size = self._hash_stream(cache)
        except DemoAssetRepositoryError:
            return "corrupt"
        if cache_hash != asset.logical_sha256 or cache_size != asset.logical_size_bytes:
            return "corrupt"
        return "valid"

    def _decompress_to_path(self, source: Path, destination: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as compressed, destination.open("wb") as logical:
                for chunk in self.decompressor.iter_decompressed(compressed, chunk_size=self.chunk_size):
                    digest.update(chunk)
                    logical.write(chunk)
                    size += len(chunk)
        except DemoCompressionError as exc:
            raise _error("demo_cache_rebuild_failed") from exc
        except OSError as exc:
            if exc.errno == errno.ENOSPC:
                raise _error("demo_cache_rebuild_failed") from exc
            raise _error("demo_cache_rebuild_failed") from exc
        if size == 0:
            raise _error("demo_cache_rebuild_failed")
        return digest.hexdigest(), size

    def _hash_decompressed_source(self, source: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        try:
            with source.open("rb") as compressed:
                for chunk in self.decompressor.iter_decompressed(compressed, chunk_size=self.chunk_size):
                    digest.update(chunk)
                    size += len(chunk)
        except (DemoCompressionError, OSError) as exc:
            raise _error("demo_asset_integrity_failed") from exc
        if size == 0:
            raise _error("demo_asset_integrity_failed")
        return digest.hexdigest(), size

    def _commit_cache(self, candidate: Path, asset_id: str, staging_root: Path, logical_size: int) -> Path:
        cache_root = self.paths.decompressed_demos_cache_dir
        self._validate_managed_directory(cache_root)
        try:
            cache_root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _error("demo_cache_rebuild_failed") from exc
        self._validate_managed_directory(cache_root)
        try:
            candidate.resolve(strict=False).relative_to(staging_root.resolve(strict=False))
        except (OSError, RuntimeError, ValueError) as exc:
            raise _error("demo_asset_path_escape") from exc
        if _is_link(candidate) or not candidate.is_file():
            raise _error("demo_asset_path_escape")
        try:
            candidate_hash, candidate_size = self._hash_stream(candidate)
        except DemoAssetRepositoryError as exc:
            raise _error("demo_cache_rebuild_failed") from exc
        if candidate_hash != asset_id or candidate_size != logical_size:
            raise _error("demo_cache_rebuild_failed")
        target = self._cache_path(asset_id)
        if _is_link(target):
            raise _error("demo_asset_path_escape")
        if target.exists():
            if not target.is_file():
                raise _error("demo_asset_path_escape")
            if self._cache_file_matches(target, asset_id, logical_size):
                return target
            try:
                os.replace(candidate, target)
            except OSError as exc:
                raise _error("demo_cache_rebuild_failed") from exc
            return target
        try:
            # A hard-link is an atomic no-clobber commit on both Windows and
            # POSIX.  The staging name remains until normal staging cleanup,
            # so no fallible cleanup occurs after the cache becomes visible.
            os.link(candidate, target)
        except FileExistsError:
            if _is_link(target) or not target.is_file():
                raise _error("demo_asset_path_escape")
            if self._cache_file_matches(target, asset_id, logical_size):
                return target
            try:
                os.replace(candidate, target)
            except OSError as exc:
                raise _error("demo_cache_rebuild_failed") from exc
        except OSError as exc:
            raise _error("demo_cache_rebuild_failed") from exc
        return target

    def _cache_file_matches(self, path: Path, asset_id: str, logical_size: int) -> bool:
        if _is_link(path) or not path.is_file():
            return False
        try:
            target_hash, target_size = self._hash_stream(path)
        except DemoAssetRepositoryError:
            return False
        return target_hash == asset_id and target_size == logical_size

    def _summary_for(self, asset_id: str, asset: DemoAsset | None, *, healthy: bool, issue_code: str | None) -> DemoAssetSummary:
        if asset is None:
            return DemoAssetSummary(asset_id, None, None, None, None, None, healthy, issue_code)
        return DemoAssetSummary(
            asset_id,
            asset.display_name,
            asset.source_format,
            asset.source_size_bytes,
            asset.logical_size_bytes,
            asset.imported_at,
            healthy,
            issue_code,
        )

    @staticmethod
    def _validate_asset_id(asset_id: str) -> None:
        if not isinstance(asset_id, str) or re.fullmatch(r"[0-9a-f]{64}", asset_id) is None:
            raise _error("demo_asset_id_invalid")

    def _hash_stream(self, path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        try:
            with path.open("rb") as source:
                while True:
                    chunk = source.read(self.chunk_size)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
        except OSError as exc:
            raise _error("demo_asset_integrity_failed") from exc
        return digest.hexdigest(), size
