from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from urllib.parse import unquote

from .query import CurrentJobWebQueryError, CurrentJobWebQueryService


_INDEX_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>CS2 POV Translator</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { margin: 0; padding: 2rem; max-width: 960px; margin-inline: auto; }
    button { font: inherit; padding: .45rem .8rem; cursor: pointer; }
    li { margin: .5rem 0; }
    .muted { opacity: .75; }
    .healthy { color: #16803c; }
    .unhealthy { color: #b42318; }
  </style>
</head>
<body>
  <main>
    <h1>CS2 POV Translator</h1>
    <p id="workspace-status" aria-live="polite">正在读取工作区状态……</p>
    <button id="refresh-jobs" type="button">刷新 Job</button>
    <h2>当前 Job</h2>
    <ul id="job-list" aria-label="当前 Job 列表" aria-live="polite"></ul>
  </main>
  <script>
    const status = document.getElementById('workspace-status');
    const list = document.getElementById('job-list');
    const refresh = document.getElementById('refresh-jobs');
    function renderJobs(items) {
      list.replaceChildren();
      if (!items.length) {
        const empty = document.createElement('li');
        empty.className = 'muted';
        empty.textContent = '当前工作区还没有当前版本 Job。';
        list.append(empty);
        return;
      }
      for (const job of items) {
        const item = document.createElement('li');
        const healthy = document.createElement('span');
        healthy.className = job.healthy ? 'healthy' : 'unhealthy';
        healthy.textContent = job.healthy ? '健康' : '需要处理';
        item.append(`${job.display_name || job.job_id} · ${job.phase || '未开始'} · `, healthy);
        list.append(item);
      }
    }
    async function load() {
      status.textContent = '正在读取工作区和 Job……';
      try {
        const [workspaceResponse, jobsResponse] = await Promise.all([
          fetch('/api/v1/workspace'),
          fetch('/api/v1/jobs')
        ]);
        const workspace = await workspaceResponse.json();
        const jobs = await jobsResponse.json();
        status.textContent = workspace.diagnostic.ok ? '工作区状态：健康' : '工作区状态：需要处理';
        renderJobs(jobs.items || []);
      } catch (error) {
        status.textContent = '读取失败，请检查本地服务和工作区。';
        list.replaceChildren();
      }
    }
    refresh.addEventListener('click', load);
    load();
    window.setInterval(load, 3000);
  </script>
</body>
</html>
"""


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class CurrentJobWebApplication:
    """Small WSGI application for the loopback-only local manager."""

    def __init__(self, query_service: CurrentJobWebQueryService) -> None:
        if not isinstance(query_service, CurrentJobWebQueryService):
            raise TypeError("query_service 必须是 CurrentJobWebQueryService。")
        self.query_service = query_service

    def __call__(self, environ: dict[str, object], start_response: Callable) -> Iterable[bytes]:
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        if method not in {"GET", "HEAD"}:
            return self._respond(
                405,
                {"ok": False, "error": self._error_payload(
                    CurrentJobWebQueryError(
                        "method_not_allowed",
                        "当前接口只支持读取请求。",
                        "请使用 GET 请求访问本地管理界面。",
                        status=405,
                    )
                )},
                start_response,
                head=method == "HEAD",
            )
        path = str(environ.get("PATH_INFO", "/")) or "/"
        if path == "/":
            body = _INDEX_HTML.encode("utf-8")
            return self._respond_bytes(200, "text/html; charset=utf-8", body, start_response, method == "HEAD")
        try:
            payload = self._route(path)
            return self._respond(200, payload, start_response, head=method == "HEAD")
        except CurrentJobWebQueryError as exc:
            return self._respond(exc.status, {"ok": False, "error": self._error_payload(exc)}, start_response, head=method == "HEAD")
        except Exception:
            exc = CurrentJobWebQueryError(
                "web_internal_error",
                "本地管理服务发生未分类错误。",
                "请检查日志和工作区状态后重试。",
                status=500,
            )
            return self._respond(500, {"ok": False, "error": self._error_payload(exc)}, start_response, head=method == "HEAD")

    def _route(self, path: str) -> dict[str, object]:
        parts = tuple(unquote(part) for part in path.split("/") if part)
        if parts == ("api", "v1", "health"):
            return self.query_service.health()
        if parts == ("api", "v1", "workspace"):
            return self.query_service.workspace()
        if parts == ("api", "v1", "demos"):
            return self.query_service.demos()
        if parts == ("api", "v1", "jobs"):
            return self.query_service.jobs()
        if len(parts) == 4 and parts[:3] == ("api", "v1", "jobs"):
            return self.query_service.job(parts[3])
        if len(parts) == 5 and parts[:3] == ("api", "v1", "jobs") and parts[4] == "events":
            return self.query_service.events(parts[3])
        if len(parts) == 6 and parts[:3] == ("api", "v1", "jobs") and parts[4] == "rounds":
            return self.query_service.round(parts[3], parts[5])
        raise CurrentJobWebQueryError(
            "route_not_found",
            "找不到本地管理接口。",
            "请检查访问路径后重试。",
            status=404,
        )

    @staticmethod
    def _error_payload(exc: CurrentJobWebQueryError) -> dict[str, object]:
        return {
            "code": exc.code,
            "message_zh": exc.message_zh,
            "suggestion_zh": exc.suggestion_zh,
        }

    @staticmethod
    def _respond(status: int, payload: object, start_response: Callable, *, head: bool) -> Iterable[bytes]:
        return CurrentJobWebApplication._respond_bytes(
            status,
            "application/json; charset=utf-8",
            _json_bytes(payload),
            start_response,
            head,
        )

    @staticmethod
    def _respond_bytes(status: int, content_type: str, body: bytes, start_response: Callable, head: bool) -> Iterable[bytes]:
        reason = {
            200: "OK",
            400: "Bad Request",
            404: "Not Found",
            405: "Method Not Allowed",
            409: "Conflict",
            500: "Internal Server Error",
        }.get(status, "Error")
        start_response(
            f"{status} {reason}",
            [("Content-Type", content_type), ("Content-Length", str(len(body)))],
        )
        return [b""] if head else [body]
