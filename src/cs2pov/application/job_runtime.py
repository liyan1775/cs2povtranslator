from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

from cs2pov.domain.models import PipelineConfig
from cs2pov.workspace.errors import WorkspaceError

if TYPE_CHECKING:
    from cs2pov.application.workspace_runtime import WorkspaceRuntime
    from cs2pov.pipeline.manifest import PipelineManifest
    from cs2pov.storage.artifact_store import ArtifactStore


class JobRuntimeError(WorkspaceError):
    """A stable application error for job identifiers and output roots."""

    def __init__(self, code: str, message_zh: str, suggestion_zh: str) -> None:
        self.code = code
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh
        super().__init__(message_zh)


@dataclass(frozen=True, slots=True)
class JobRuntime:
    """The one application boundary that adapts a config to a workspace job."""

    runtime: "WorkspaceRuntime"
    output_root: Path
    config: PipelineConfig | None = None
    legacy_external_output: bool = False

    @classmethod
    def from_config(
        cls,
        runtime: "WorkspaceRuntime",
        config: PipelineConfig,
        *,
        output_root: str | Path | None = None,
    ) -> "JobRuntime":
        explicit = output_root is not None
        if explicit and isinstance(output_root, str) and not output_root.strip():
            raise JobRuntimeError(
                "job_path_escape",
                "Job 输出目录不能为空。",
                "请提供可访问的输出目录，或移除 --output 使用当前工作区。",
            )
        root = Path(output_root).expanduser() if explicit else runtime.paths.jobs_dir
        if "\x00" in str(root):
            raise JobRuntimeError("job_path_escape", "Job 输出目录路径无效。", "请提供可访问的输出目录后重试。")
        try:
            root = root.resolve()
            workspace_root = runtime.root.resolve()
        except (OSError, RuntimeError, ValueError) as exc:
            raise JobRuntimeError(
                "job_path_escape", "Job 输出目录路径无效。", "请提供可访问的输出目录后重试。"
            ) from exc
        if not explicit and not root.is_relative_to(workspace_root):
            raise JobRuntimeError(
                "job_path_escape", "工作区 jobs 目录超出工作区根目录。", "请修复工作区目录布局后重试。"
            )
        return cls(runtime, root, config, explicit)

    @property
    def jobs_dir(self) -> Path:
        return self.runtime.paths.jobs_dir.resolve()

    def adapt_config(self, config: PipelineConfig | None = None) -> PipelineConfig:
        """Return a copy; the caller's legacy config is never mutated."""
        config = config or self.config or PipelineConfig()
        return replace(
            config,
            output_root=str(self.output_root),
            whisper_cache_dir=str(self.runtime.paths.whisper_cache_dir),
        )

    def create_store(
        self,
        config: PipelineConfig | None = None,
        *,
        map_name: str | None = None,
        job_id: str | None = None,
    ) -> "ArtifactStore":
        from cs2pov.storage.artifact_store import ArtifactStore

        config = config or self.config or PipelineConfig()
        return ArtifactStore.create(
            self.output_root,
            map_name=map_name if map_name is not None else config.map_name,
            job_id=job_id if job_id is not None else config.job_id,
        )

    def create_manifest(self, job_id: str, config: PipelineConfig | None = None) -> "PipelineManifest":
        from cs2pov.pipeline.manifest import PipelineManifest

        config = self.adapt_config(config)
        return PipelineManifest.create(
            job_id,
            config,
            path_policy_version=self.runtime.path_policy_version,
            legacy_external_output=self.legacy_external_output,
        )
