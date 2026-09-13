from __future__ import annotations

import json
import hashlib
from pathlib import Path

from cs2pov.domain.media import AudioMediaReference
from cs2pov.storage.demo_asset_repository import FileSystemDemoAssetRepository
from cs2pov.web.query import CurrentJobWebQueryService
from cs2pov.workspace.service import WorkspaceService
from cs2pov.web.app import CurrentJobWebApplication
from tests.test_voice_asr_ports_v1 import _job, _write_test_audio
from tests.test_web_query_v1 import _service


def _call(app, path: str, method: str = "GET", **overrides):
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
    environ.update(overrides)
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


def test_http_media_endpoint_serves_only_persisted_audio_and_supports_ranges(tmp_path: Path):
    workspace, repository, request, _ = _job(tmp_path)
    source = _write_test_audio(tmp_path / "media.wav", sample_count=10)
    payload = source.read_bytes()
    reference = AudioMediaReference(
        "player-audio",
        "player-a",
        "voice/audio/player-audio.wav",
        hashlib.sha256(payload).hexdigest(),
        24_000,
        10,
    )
    with repository.acquire_write(request.job_id, lease_us=1_000_000) as session:
        repository.save_audio_media(
            request.job_id,
            (reference,),
            {reference.media_id: source},
            session.claim,
        )
    service = CurrentJobWebQueryService(
        workspace,
        workspace_service=WorkspaceService(workspace, minimum_free_bytes=0),
        demo_assets=FileSystemDemoAssetRepository(workspace),
        jobs=repository,
    )
    app = CurrentJobWebApplication(service)

    status, headers, body = _call(
        app,
        "/api/v1/jobs/job-voice-asr/media/player-audio",
    )
    assert status == "200 OK"
    assert headers["Content-Type"] == "audio/wav"
    assert headers["Accept-Ranges"] == "bytes"
    assert body == payload

    status, headers, body = _call(
        app,
        "/api/v1/jobs/job-voice-asr/media/player-audio",
        HTTP_RANGE="bytes=0-3",
    )
    assert status == "206 Partial Content"
    assert headers["Content-Range"] == f"bytes 0-3/{len(payload)}"
    assert body == payload[:4]

    status, headers, body = _call(
        app,
        "/api/v1/jobs/job-voice-asr/media/player-audio",
        HTTP_RANGE=f"bytes={len(payload)}-",
    )
    assert status == "416 Range Not Satisfiable"
    assert headers["Content-Range"] == f"bytes */{len(payload)}"
    assert body == b""

    status, headers, body = _call(
        app,
        "/api/v1/jobs/job-voice-asr/media/not-registered",
    )
    assert status == "404 Not Found"
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert json.loads(body)["error"]["code"] == "media_not_found"
