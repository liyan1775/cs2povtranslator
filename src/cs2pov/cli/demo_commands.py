from __future__ import annotations

import json
from pathlib import Path

from cs2pov.application.demo_assets import DemoAssetApplicationService, DemoAssetUseCaseError
from cs2pov.application.workspace_runtime import WorkspaceRuntimeError, WorkspaceRuntimeResolver
from cs2pov.storage.workspace_selection_store import (
    JsonWorkspaceSelectionStore,
    WorkspaceSelectionStoreError,
    default_state_file,
)


def add_demos_parser(subparsers) -> None:
    demos = subparsers.add_parser("demos", help="导入、查看和检查当前工作区 Demo 素材")
    commands = demos.add_subparsers(dest="demos_cmd", required=True)

    import_demo = commands.add_parser("import", help="把 .dem 或 .dem.zst 导入当前工作区素材库")
    import_demo.add_argument("path", help="外部 Demo 文件；只读取，不移动或修改")
    import_demo.add_argument("--json", action="store_true", help="输出单个 JSON 文档")

    list_demos = commands.add_parser("list", help="列出当前工作区 Demo 素材及健康状态")
    list_demos.add_argument("--json", action="store_true", help="输出单个 JSON 文档")

    inspect_demo = commands.add_parser("inspect", help="只读检查一个 Demo 素材和解压缓存")
    inspect_demo.add_argument("asset_id", help="完整的 64 位素材 ID")
    inspect_demo.add_argument("--json", action="store_true", help="输出单个 JSON 文档")


def _application() -> DemoAssetApplicationService:
    resolver = WorkspaceRuntimeResolver(JsonWorkspaceSelectionStore(default_state_file()))
    return DemoAssetApplicationService(resolver)


def _error_document(command: str, error) -> dict[str, object]:
    return {
        "ok": False,
        "command": command,
        "error": {
            "code": error.code,
            "message_zh": error.message_zh,
            "suggestion_zh": error.suggestion_zh,
        },
    }


def run_demos(args) -> int:
    command = f"demos.{args.demos_cmd}"
    try:
        app = _application()
        if args.demos_cmd == "import":
            result = app.import_demo(Path(args.path))
            document = {"ok": True, "command": command, "result": result.to_dict()}
            exit_code = 0
        elif args.demos_cmd == "list":
            assets = app.list_assets()
            document = {
                "ok": True,
                "command": command,
                "count": len(assets),
                "assets": [asset.to_dict() for asset in assets],
            }
            exit_code = 0
        else:
            inspection = app.inspect_asset(args.asset_id)
            document = {
                "ok": inspection.ok,
                "command": command,
                "inspection": inspection.to_dict(),
            }
            exit_code = 0 if inspection.ok else 1
    except (DemoAssetUseCaseError, WorkspaceRuntimeError, WorkspaceSelectionStoreError) as exc:
        document = _error_document(command, exc)
        exit_code = 1

    if getattr(args, "json", False):
        print(json.dumps(document, ensure_ascii=False, indent=2))
    else:
        _print_text(args.demos_cmd, document)
    return exit_code


def _print_text(demos_cmd: str, document: dict[str, object]) -> None:
    if "error" in document:
        error = document["error"]
        print(f"操作失败[{error['code']}]：{error['message_zh']}")
        print(f"建议：{error['suggestion_zh']}")
        return
    if demos_cmd == "import":
        result = document["result"]
        asset = result["asset"]
        if result["disposition"] == "imported":
            print("已导入到当前工作区素材库。")
            print(f"素材 ID：{asset['asset_id']}")
            print(f"名称：{asset['display_name']}")
            print(f"长期新增空间：{_format_bytes(result['persistent_bytes_added'])}")
        else:
            print("工作区已有相同 Demo，本次直接复用。")
            print(f"素材 ID：{asset['asset_id']}")
            print(f"首次导入名称：{asset['display_name']}")
        return
    if demos_cmd == "list":
        assets = document["assets"]
        if not assets:
            print("当前工作区还没有 Demo 素材。")
            print("可运行：cs2pov demos import <你的-demo.dem>")
            return
        print(f"当前工作区共有 {document['count']} 个 Demo 素材：")
        for asset in assets:
            state = "健康" if asset["healthy"] else f"需要检查（{asset['issue_code']}）"
            name = asset["display_name"] or "名称不可读"
            print(f"- {name} | {asset['asset_id']} | {state}")
        return

    inspection = document["inspection"]
    asset = inspection["asset"]
    print(f"素材 ID：{asset['asset_id']}")
    print(f"名称：{asset['display_name']}")
    if not inspection["source_ok"]:
        print("持久源完整性检查失败；现有素材不会被自动覆盖。")
        print("建议：保留当前资产用于诊断，并从可信原始 Demo 重新导入。")
        return
    print("持久源完整。")
    cache_status = inspection["cache_status"]
    if cache_status == "missing":
        print("解压缓存当前缺失；需要时可自动重建，不影响持久素材。")
    elif cache_status == "corrupt":
        print("解压缓存损坏；需要时可从完整持久源自动重建。")
    elif cache_status == "valid":
        print("解压缓存有效。")
    else:
        print("该素材不需要单独的解压缓存。")


def _format_bytes(value: int) -> str:
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KiB"
    if value < 1024 * 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} MiB"
    return f"{value / (1024 * 1024 * 1024):.2f} GiB"
