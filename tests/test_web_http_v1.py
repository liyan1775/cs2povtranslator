from __future__ import annotations

import json
from pathlib import Path

from cs2pov.web.app import CurrentJobWebApplication
from tests.test_web_query_v1 import _service


def _call(app, path: str, method: str = "GET"):
    captured = {}

    def start_response(status, headers, exc_info=None):
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "wsgi.url_scheme": "http",
        "SERVER_NAME": "127.0.0.1",
        "SERVER_PORT": "8765",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "wsgi.input": __import__("io").BytesIO(),
    }
    body = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], body


def test_http_api_returns_json_for_health_and_job_routes(tmp_path: Path):
    app = CurrentJobWebApplication(_service(tmp_path))

    status, headers, body = _call(app, "/api/v1/health")
    assert status == "200 OK"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    health = json.loads(body)
    assert health["ok"] is True
    assert "workspace_id" in health
    assert str(tmp_path) not in body.decode()

    status, _, body = _call(app, "/api/v1/jobs/job-web/rounds/round-001")
    assert status == "200 OK"
    assert json.loads(body)["round"]["round_id"] == "round-001"

    status, headers, body = _call(app, "/api/v1/jobs/job-web/rounds/round-001/review")
    assert status == "200 OK"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body)["review"]["items"][1]["decision"]["action"] == "edit"


def test_http_api_has_stable_errors_and_accessible_index(tmp_path: Path):
    app = CurrentJobWebApplication(_service(tmp_path))

    status, headers, body = _call(app, "/api/v1/jobs/unknown")
    assert status == "404 Not Found"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    error = json.loads(body)["error"]
    assert error["code"] == "job_not_found"
    assert error["message_zh"] and error["suggestion_zh"]

    status, headers, body = _call(app, "/")
    assert status == "200 OK"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    html = body.decode("utf-8")
    assert 'id="job-list"' in html
    assert 'aria-live="polite"' in html
    assert "刷新 Job" in html

    status, headers, body = _call(app, "/jobs/job-web/rounds/round-001/review")
    assert status == "200 OK"
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    review_html = body.decode("utf-8")
    assert 'data-testid="review-page"' in review_html
    assert 'data-testid="review-cues"' in review_html
    assert 'data-testid="media-status"' in review_html
    assert "/api/v1/jobs/" in review_html

    status, _, body = _call(app, "/api/v1/unknown")
    assert status == "404 Not Found"
    assert json.loads(body)["error"]["code"] == "route_not_found"
