from __future__ import annotations

import json
from pathlib import Path

from cs2pov.application.workspace import WorkspaceApplicationService, WorkspaceUseCaseError
from cs2pov.storage.workspace_selection_store import JsonWorkspaceSelectionStore, WorkspaceSelectionStoreError, default_state_file


def add_workspace_parser(subparsers):
    workspace = subparsers.add_parser("workspace", help="选择、检查和管理工作区")
    commands = workspace.add_subparsers(dest="workspace_cmd", required=True)
    init = commands.add_parser("init", help="初始化并选择工作区")
    init.add_argument("path")
    init.add_argument("--json", action="store_true")
    use = commands.add_parser("use", help="选择已有工作区")
    use.add_argument("path")
    use.add_argument("--json", action="store_true")
    show = commands.add_parser("show", help="显示当前工作区")
    show.add_argument("--json", action="store_true")
    doctor = commands.add_parser("doctor", help="诊断工作区")
    doctor.add_argument("path", nargs="?")
    doctor.add_argument("--json", action="store_true")
    forget = commands.add_parser("forget", help="忘记当前工作区选择")
    forget.add_argument("--json", action="store_true")


def _application():
    return WorkspaceApplicationService(JsonWorkspaceSelectionStore(default_state_file()))


def _error_document(command, error):
    body = {"code": error.code, "message_zh": error.message_zh, "suggestion_zh": error.suggestion_zh}
    result = {"ok": False, "command": command, "error": body}
    if getattr(error, "diagnostic", None) is not None:
        result["diagnostic"] = error.diagnostic.to_dict()
    return result


def run_workspace(args):
    command = f"workspace.{args.workspace_cmd}"
    try:
        app = _application()
        if args.workspace_cmd == "init":
            view = app.initialize_and_select(args.path)
            result, code = {"ok": True, "command": command, **view.to_dict()}, 0
        elif args.workspace_cmd == "use":
            view = app.select_existing(args.path)
            result, code = {"ok": True, "command": command, **view.to_dict()}, 0
        elif args.workspace_cmd == "show":
            view = app.show_current()
            result, code = {"ok": view.diagnostic.ok, "command": command, **view.to_dict()}, 0 if view.diagnostic.ok else 1
        elif args.workspace_cmd == "doctor":
            view = app.diagnose(args.path)
            result, code = {"ok": view.diagnostic.ok, "command": command, **view.to_dict()}, 0 if view.diagnostic.ok else 1
        else:
            forgotten = app.forget_current()
            result = {"ok": True, "command": command, "selected_workspace": None, "diagnostic": None, **forgotten.to_dict()}
            code = 0
    except (WorkspaceUseCaseError, WorkspaceSelectionStoreError) as exc:
        result, code = _error_document(command, exc), 1
    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        if args.workspace_cmd == "forget":
            print("已忘记当前工作区选择；不会删除工作区文件。")
        else:
            print(f"当前工作区：{result.get('selected_workspace')}")
            print("状态：健康" if result.get("diagnostic", {}).get("ok") else "状态：需要修复")
    else:
        print(f"操作失败：{result['error']['message_zh']}")
        print(f"建议：{result['error']['suggestion_zh']}")
    return code
