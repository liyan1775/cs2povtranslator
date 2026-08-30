from pathlib import Path
from .errors import (
    WorkspacePathOutsideRootError,
    WorkspaceResourcePathError,
    WorkspaceRootRequiredError,
)


class WorkspacePaths:
    def __init__(self, root: str | Path) -> None:
        if root is None or not isinstance(root, (str, Path)):
            raise WorkspaceRootRequiredError("请显式提供一个绝对工作区根目录。")
        if isinstance(root, str) and not root.strip():
            raise WorkspaceRootRequiredError("请显式提供一个非空绝对工作区根目录。")
        candidate = Path(root)
        if not candidate.is_absolute():
            raise WorkspaceRootRequiredError("工作区根目录必须是绝对路径，请重新选择目录。")
        self.root = candidate.resolve()

    @property
    def config_file(self) -> Path:
        return self.root / "workspace.json"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def demo_library_dir(self) -> Path:
        return self.root / "library" / "demos"

    @property
    def jobs_dir(self) -> Path:
        return self.root / "jobs"

    @property
    def knowledge_dir(self) -> Path:
        return self.root / "knowledge"

    @property
    def knowledge_inbox_dir(self) -> Path:
        return self.knowledge_dir / "inbox"

    @property
    def knowledge_exports_dir(self) -> Path:
        return self.knowledge_dir / "exports"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def decompressed_demos_cache_dir(self) -> Path:
        return self.cache_dir / "decompressed_demos"

    @property
    def audio_cache_dir(self) -> Path:
        return self.cache_dir / "audio"

    @property
    def render_cache_dir(self) -> Path:
        return self.cache_dir / "render"

    @property
    def huggingface_cache_dir(self) -> Path:
        return self.cache_dir / "huggingface"

    @property
    def huggingface_hub_cache_dir(self) -> Path:
        return self.huggingface_cache_dir / "hub"

    @property
    def whisper_cache_dir(self) -> Path:
        return self.cache_dir / "whisper"

    @property
    def temp_dir(self) -> Path:
        return self.cache_dir / "tmp"

    @property
    def render_bundles_dir(self) -> Path:
        return self.root / "render_bundles"

    def persistent_directories(self) -> tuple[Path, ...]:
        return (self.models_dir, self.demo_library_dir, self.jobs_dir,
                self.knowledge_dir, self.knowledge_inbox_dir,
                self.knowledge_exports_dir, self.render_bundles_dir)

    def cache_directories(self) -> tuple[Path, ...]:
        return (self.cache_dir, self.decompressed_demos_cache_dir,
                self.audio_cache_dir, self.render_cache_dir,
                self.huggingface_cache_dir, self.huggingface_hub_cache_dir,
                self.whisper_cache_dir, self.temp_dir)

    def all_directories(self) -> tuple[Path, ...]:
        return self.persistent_directories() + self.cache_directories()

    def _inside(self, path: Path, *, allow_root: bool = False) -> Path:
        if not path.is_absolute():
            raise WorkspacePathOutsideRootError("路径必须位于工作区内，请提供工作区下的绝对路径。")
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.root)
        except ValueError as exc:
            raise WorkspacePathOutsideRootError("路径超出工作区，请改用工作区内的路径。") from exc
        if not allow_root and not relative.parts:
            raise WorkspacePathOutsideRootError("不能使用工作区根目录本身，请指定其内部资源。")
        return resolved

    def to_relative(self, path: str | Path) -> str:
        try:
            candidate = Path(path)
        except (TypeError, ValueError) as exc:
            raise WorkspaceResourcePathError("资源路径无效，请提供工作区内的路径。") from exc
        resolved = self._inside(candidate)
        return resolved.relative_to(self.root).as_posix()

    def resolve_relative(self, value: str) -> Path:
        if not isinstance(value, str) or not value:
            raise WorkspaceResourcePathError("相对路径不能为空，请提供规范化的工作区相对路径。")
        if value != value.strip() or "\\" in value or ":" in value or "://" in value:
            raise WorkspaceResourcePathError("相对路径格式无效，请使用工作区内的 POSIX 路径。")
        candidate = Path(value)
        if candidate.is_absolute() or value.startswith("/") or value.startswith("//"):
            raise WorkspacePathOutsideRootError("相对路径不能是绝对路径，请改用工作区内路径。")
        if value in {".", ".."} or any(part in {"", ".", ".."} for part in value.split("/")):
            raise WorkspacePathOutsideRootError("相对路径不能包含空段或穿越段，请重新输入。")
        if candidate.as_posix() != value:
            raise WorkspaceResourcePathError("相对路径必须规范化并使用 '/' 分隔。")
        return self._inside(self.root / candidate)

    def cache_paths(self) -> dict[str, Path]:
        return {"huggingface": self.huggingface_cache_dir,
                "huggingface_hub": self.huggingface_hub_cache_dir,
                "whisper": self.whisper_cache_dir, "temporary": self.temp_dir}

    def environment_overrides(self) -> dict[str, str]:
        return {"HF_HOME": str(self.huggingface_cache_dir),
                "HF_HUB_CACHE": str(self.huggingface_hub_cache_dir),
                "HUGGINGFACE_HUB_CACHE": str(self.huggingface_hub_cache_dir),
                "TMP": str(self.temp_dir), "TEMP": str(self.temp_dir),
                "TMPDIR": str(self.temp_dir)}
