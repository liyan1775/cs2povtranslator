from __future__ import annotations

import argparse
from wsgiref.simple_server import WSGIServer, make_server

from cs2pov.workspace.paths import WorkspacePaths

from .app import CurrentJobWebApplication
from .query import CurrentJobWebQueryService


def create_server(
    workspace_root: str,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> WSGIServer:
    paths = WorkspacePaths(workspace_root)
    application = CurrentJobWebApplication(CurrentJobWebQueryService(paths))
    return make_server(host, port, application)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cs2pov-web",
        description="启动当前版本 Job 的本地管理界面与 API。",
    )
    parser.add_argument("--workspace", required=True, help="工作区绝对路径。")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认只监听本机。")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765。")
    args = parser.parse_args(argv)
    server = create_server(args.workspace, host=args.host, port=args.port)
    print(f"CS2 POV Translator 本地界面：http://{args.host}:{args.port}/")
    print("按 Ctrl+C 停止服务。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
