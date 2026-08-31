from __future__ import annotations

from pathlib import Path
from typing import Callable

from cs2pov.application.workspace_runtime import WorkspaceRuntimeResolver
from cs2pov.domain.assets import (
    DemoAssetInspection,
    DemoAssetRef,
    DemoAssetSummary,
    DemoImportResult,
)
from cs2pov.storage.demo_asset_repository import (
    DemoAssetRepositoryError,
    FileSystemDemoAssetRepository,
)
from cs2pov.workspace.paths import WorkspacePaths


class DemoAssetUseCaseError(RuntimeError):
    def __init__(self, code: str, message_zh: str, suggestion_zh: str) -> None:
        self.code = code
        self.message_zh = message_zh
        self.suggestion_zh = suggestion_zh
        super().__init__(message_zh)


class DemoAssetApplicationService:
    def __init__(
        self,
        runtime_resolver: WorkspaceRuntimeResolver,
        *,
        repository_factory: Callable[[WorkspacePaths], FileSystemDemoAssetRepository] = FileSystemDemoAssetRepository,
    ) -> None:
        if not callable(repository_factory):
            raise TypeError("repository_factory 必须可调用。")
        self.runtime_resolver = runtime_resolver
        self.repository_factory = repository_factory

    def import_demo(self, source: str | Path) -> DemoImportResult:
        repository = self._write_repository()
        return self._call(repository.import_source, Path(source))

    def list_assets(self) -> tuple[DemoAssetSummary, ...]:
        repository = self._read_repository()
        return self._call(repository.list_assets)

    def inspect_asset(self, asset_id: str) -> DemoAssetInspection:
        repository = self._read_repository()
        return self._call(repository.inspect_asset, asset_id)

    def resolve_asset(self, ref: DemoAssetRef) -> Path:
        repository = self._write_repository()
        return self._call(repository.resolve_asset, ref)

    def _read_repository(self) -> FileSystemDemoAssetRepository:
        runtime = self.runtime_resolver.resolve_for_read()
        return self.repository_factory(runtime.paths)

    def _write_repository(self) -> FileSystemDemoAssetRepository:
        runtime = self.runtime_resolver.resolve_for_write()
        return self.repository_factory(runtime.paths)

    @staticmethod
    def _call(operation, *args):
        try:
            return operation(*args)
        except DemoAssetRepositoryError as exc:
            raise DemoAssetUseCaseError(exc.code, exc.message_zh, exc.suggestion_zh) from exc
