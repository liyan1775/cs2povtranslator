import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import UUID, uuid4

from .errors import (WorkspaceConfigError, WorkspaceInitializationError,
                     WorkspaceInsufficientSpaceError, WorkspaceLayoutError,
                     WorkspaceNotWritableError)
from .models import (WORKSPACE_LAYOUT_VERSION, WORKSPACE_SCHEMA_VERSION,
                     WorkspaceConfig, WorkspaceDiagnostic, WorkspaceIssue)
from .paths import WorkspacePaths

DEFAULT_MINIMUM_FREE_BYTES = 5 * 1024**3


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceService:
    def __init__(self, paths: WorkspacePaths, *, minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES,
                 id_factory: Callable[[], UUID] = uuid4, clock: Callable[[], datetime] = utc_now,
                 disk_usage: Callable[[Path], object] = shutil.disk_usage) -> None:
        if not isinstance(minimum_free_bytes, int) or minimum_free_bytes < 0:
            raise ValueError("minimum_free_bytes 必须是非负整数。")
        self.paths, self.minimum_free_bytes = paths, minimum_free_bytes
        self.id_factory, self.clock, self.disk_usage = id_factory, clock, disk_usage

    def _usage(self) -> int:
        parent = self.paths.root
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        try:
            usage = self.disk_usage(parent)
            free = usage.free if hasattr(usage, "free") else usage[2]
            if not isinstance(free, int) or free < 0:
                raise ValueError
            return free
        except Exception as exc:
            raise WorkspaceInitializationError("无法检查工作区磁盘空间，请检查磁盘后重试。") from exc

    def _check_space(self) -> int:
        free = self._usage()
        if free < self.minimum_free_bytes:
            raise WorkspaceInsufficientSpaceError("工作区所在磁盘空间不足，请释放空间后重试。")
        return free

    def _check_boundaries(self) -> None:
        try:
            self.paths._inside(self.paths.config_file)
            for directory in self.paths.all_directories():
                self.paths._inside(directory)
        except Exception as exc:
            raise WorkspaceLayoutError("工作区路径包含越界符号链接，请更换根目录或修复链接。") from exc

    def _read_existing(self) -> WorkspaceConfig | None:
        config = self.paths.config_file
        if not config.exists() and not config.is_symlink():
            return None
        if config.is_symlink() or not config.is_file():
            raise WorkspaceConfigError("workspace.json 不是普通配置文件，请移除后重新选择工作区。")
        try:
            return WorkspaceConfig.from_dict(json.loads(config.read_text(encoding="utf-8")))
        except WorkspaceConfigError:
            raise
        except Exception as exc:
            raise WorkspaceConfigError("workspace.json 已损坏，请恢复有效配置或选择新工作区。") from exc

    def _probe(self) -> None:
        probe_name = None
        handle = None
        try:
            handle = tempfile.NamedTemporaryFile(dir=self.paths.root, prefix=".workspace-probe-", delete=False)
            probe_name = handle.name
            handle.write(b"ok")
            handle.flush()
        except Exception as exc:
            raise WorkspaceNotWritableError("工作区不可写，请选择可写目录或修复权限。") from exc
        finally:
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
            if probe_name:
                try:
                    Path(probe_name).unlink(missing_ok=True)
                except OSError:
                    pass

    def initialize(self) -> WorkspaceConfig:
        self._check_space()
        if self.paths.root.exists() and not self.paths.root.is_dir():
            raise WorkspaceLayoutError("工作区根路径不是目录，请选择一个目录。")
        self._check_boundaries()
        existing = self._read_existing()
        try:
            self.paths.root.mkdir(parents=True, exist_ok=True)
            for directory in self.paths.all_directories():
                directory.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            raise WorkspaceLayoutError("无法创建工作区目录，请检查路径和权限。") from exc
        self._probe()
        if existing is not None:
            return existing
        now = self.clock()
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise WorkspaceConfigError("创建时间必须带时区，请提供 UTC 时间。")
        now_utc = now.astimezone(timezone.utc)
        workspace_id = self.id_factory()
        if not isinstance(workspace_id, UUID):
            raise WorkspaceConfigError("工作区 ID 工厂返回值无效，请重试或修复配置。")
        config = WorkspaceConfig(WORKSPACE_SCHEMA_VERSION, WORKSPACE_LAYOUT_VERSION,
                                 str(workspace_id), now_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.paths.root, prefix=".workspace-config-", suffix=".tmp",
                                             mode="w", encoding="utf-8", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(config.to_dict(), stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.paths.config_file)
        except Exception as exc:
            raise WorkspaceInitializationError("无法写入工作区配置，请检查权限后重试。") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return config

    def load_config(self) -> WorkspaceConfig:
        config = self._read_existing()
        if config is None:
            raise WorkspaceConfigError("未找到 workspace.json，请先显式初始化工作区。")
        return config

    def diagnose(self) -> WorkspaceDiagnostic:
        issues: list[WorkspaceIssue] = []
        root = self.paths.root
        free = None
        if not root.exists():
            try:
                parent = root
                while not parent.exists() and parent != parent.parent:
                    parent = parent.parent
                usage = self.disk_usage(parent)
                free = usage.free if hasattr(usage, "free") else usage[2]
                if not isinstance(free, int) or free < 0:
                    raise ValueError
                if free < self.minimum_free_bytes:
                    issues.append(WorkspaceIssue("workspace_space_low", "error", "工作区磁盘空间不足。", "释放磁盘空间后重试。"))
            except Exception:
                issues.append(WorkspaceIssue("workspace_inspection_failed", "error", "无法检查工作区位置。", "请检查磁盘和路径权限后重试。"))
            issues.insert(0, WorkspaceIssue("workspace_missing", "error", "工作区目录尚未创建。", "请先选择目录并执行初始化。"))
            return WorkspaceDiagnostic(False, False, None, free, self.minimum_free_bytes, tuple(issues))
        if not root.is_dir():
            return WorkspaceDiagnostic(False, False, None, None, self.minimum_free_bytes,
                                       (WorkspaceIssue("workspace_not_directory", "error", "工作区路径不是目录。", "请选择一个目录。"),))
        layout_bad = False
        try:
            self._check_boundaries()
        except WorkspaceLayoutError:
            layout_bad = True
        config_bad = False
        config_code = "workspace_config_invalid"
        try:
            self.load_config()
        except WorkspaceConfigError:
            config_bad = True
            config_code = "workspace_config_missing" if not self.paths.config_file.exists() else "workspace_config_invalid"
        if config_bad:
            issues.append(WorkspaceIssue(config_code, "error", "工作区配置缺失或损坏。", "请恢复有效配置或重新选择工作区。"))
        missing = any(not d.is_dir() for d in self.paths.all_directories())
        if missing:
            layout_bad = True
        if layout_bad:
            issues.append(WorkspaceIssue("workspace_layout_missing", "error", "工作区目录布局不完整。", "请执行初始化以补齐受管目录。"))
        try:
            writable = os.access(root, os.W_OK)
        except Exception:
            writable = None
            issues.append(WorkspaceIssue("workspace_inspection_failed", "error", "无法检查工作区权限。", "请检查目录权限后重试。"))
        if writable is False:
            issues.append(WorkspaceIssue("workspace_not_writable", "error", "工作区不可写。", "请选择可写目录或修复权限。"))
        try:
            usage = self.disk_usage(root)
            free = usage.free if hasattr(usage, "free") else usage[2]
            if not isinstance(free, int) or free < 0:
                raise ValueError
            if free < self.minimum_free_bytes:
                issues.append(WorkspaceIssue("workspace_space_low", "error", "工作区磁盘空间不足。", "释放磁盘空间后重试。"))
        except Exception:
            issues.append(WorkspaceIssue("workspace_inspection_failed", "error", "无法检查工作区磁盘空间。", "请检查磁盘状态后重试。"))
        initialized = not any(i.code in {"workspace_config_missing", "workspace_config_invalid"} for i in issues)
        return WorkspaceDiagnostic(not issues and writable is True, initialized, writable, free, self.minimum_free_bytes, tuple(issues))
