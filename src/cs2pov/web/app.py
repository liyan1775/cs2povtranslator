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


_REVIEW_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>回合复核 · CS2 POV Translator</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, sans-serif; }
    body { margin: 0; padding: 2rem; max-width: 1180px; margin-inline: auto; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { border: 1px solid CanvasText; padding: .55rem; text-align: left; vertical-align: top; }
    th { background: Canvas; }
    .muted { opacity: .75; }
    .risk { color: #b42318; }
    .decision { color: #16803c; }
    .text { white-space: pre-wrap; }
  </style>
</head>
<body>
  <main data-testid="review-page">
    <p><a href="/">返回 Job 列表</a></p>
    <h1>回合复核</h1>
    <p id="review-status" data-testid="review-status" aria-live="polite">正在读取复核数据……</p>
    <p id="media-status" data-testid="media-status" class="muted">正在检查音频试听状态……</p>
    <table data-testid="review-cues" aria-label="回合复核内容">
      <thead>
        <tr><th scope="col">时间</th><th scope="col">原始 ASR</th><th scope="col">解释与翻译</th><th scope="col">依据</th><th scope="col">复核状态</th></tr>
      </thead>
      <tbody id="review-cue-list"></tbody>
    </table>
  </main>
  <script>
    const jobId = __JOB_ID__;
    const roundId = __ROUND_ID__;
    const endpoint = `/api/v1/jobs/${encodeURIComponent(jobId)}/rounds/${encodeURIComponent(roundId)}/review`;
    const status = document.getElementById('review-status');
    const mediaStatus = document.getElementById('media-status');
    const list = document.getElementById('review-cue-list');
    function textCell(value, className = 'text') {
      const cell = document.createElement('td');
      cell.className = className;
      cell.textContent = value == null ? '—' : String(value);
      return cell;
    }
    function renderItems(items) {
      list.replaceChildren();
      for (const item of items) {
        const row = document.createElement('tr');
        row.dataset.cueId = item.cue_id;
        row.append(
          textCell(`${item.start_us ?? '—'}–${item.end_us ?? '—'}`),
          textCell(item.asr_original),
          textCell(item.understanding ? `${item.understanding.interpreted_source}\n${item.understanding.translated_zh}` : null),
          textCell(item.understanding?.evidence?.join('；')),
          textCell(item.decision ? item.decision.action : '待复核', item.decision ? 'decision' : 'risk')
        );
        list.append(row);
      }
      if (!items.length) {
        const row = document.createElement('tr');
        const cell = textCell('当前回合没有可复核 Cue。');
        cell.colSpan = 5;
        row.append(cell);
        list.append(row);
      }
    }
    async function load() {
      try {
        const response = await fetch(endpoint);
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error?.message_zh || '读取失败');
        const review = payload.review;
        status.textContent = `复核状态：${review.status}；已完成 ${review.completed_count} 条，待复核 ${review.pending_count} 条`;
        mediaStatus.textContent = payload.media?.message_zh || '音频试听状态未知。';
        renderItems(review.items || []);
      } catch (error) {
        status.textContent = '读取复核数据失败，请检查 Job 和本地服务。';
        mediaStatus.textContent = '音频试听状态暂不可用。';
        list.replaceChildren();
      }
    }
    load();
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
        page = self._page(path)
        if page is not None:
            return self._respond_bytes(200, "text/html; charset=utf-8", page, start_response, method == "HEAD")
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
        if len(parts) == 7 and parts[:3] == ("api", "v1", "jobs") and parts[4] == "rounds" and parts[6] == "review":
            return self.query_service.review(parts[3], parts[5])
        if len(parts) == 6 and parts[:3] == ("api", "v1", "jobs") and parts[4] == "rounds":
            return self.query_service.round(parts[3], parts[5])
        raise CurrentJobWebQueryError(
            "route_not_found",
            "找不到本地管理接口。",
            "请检查访问路径后重试。",
            status=404,
        )

    @staticmethod
    def _page(path: str) -> bytes | None:
        parts = tuple(unquote(part) for part in path.split("/") if part)
        if len(parts) != 5 or parts[0] != "jobs" or parts[2] != "rounds" or parts[4] != "review":
            return None
        job_id, round_id = parts[1], parts[3]
        html = _REVIEW_HTML.replace(
            "__JOB_ID__", json.dumps(job_id, ensure_ascii=False)
        ).replace("__ROUND_ID__", json.dumps(round_id, ensure_ascii=False))
        return html.encode("utf-8")

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
