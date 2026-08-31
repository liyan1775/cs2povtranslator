from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cs2pov.application.demo_assets import DemoAssetApplicationService
from cs2pov.application.workspace_runtime import WorkspaceRuntime
from cs2pov.domain.assets import DemoAssetRef, DemoImportResult


@dataclass(frozen=True, slots=True)
class PreparedDemoAsset:
    runtime: WorkspaceRuntime
    service: DemoAssetApplicationService
    result: DemoImportResult
    ref: DemoAssetRef
    display_name: str


def prepare_demo_asset(source: str | Path, *, runtime: WorkspaceRuntime) -> PreparedDemoAsset:
    """Import/reuse one external Demo and preflight its managed resolution."""
    service = DemoAssetApplicationService.for_runtime(runtime)
    result = service.import_demo(source)
    ref = result.asset.to_ref()
    service.resolve_asset(ref)
    return PreparedDemoAsset(runtime, service, result, ref, result.asset.display_name)
