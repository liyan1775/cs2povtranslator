from __future__ import annotations

import os
from collections.abc import Iterator
from threading import Thread
from wsgiref.simple_server import make_server

import pytest

pytest.importorskip("playwright")
pytest.importorskip("pytest_playwright")

from playwright.sync_api import Page, expect

from cs2pov.web.app import CurrentJobWebApplication
from tests.test_web_query_v1 import _service


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.environ.get("CS2POV_RUN_BROWSER_E2E") != "1",
        reason="设置 CS2POV_RUN_BROWSER_E2E=1 后运行浏览器验收。",
    ),
]


@pytest.fixture
def web_base_url(tmp_path) -> Iterator[str]:
    app = CurrentJobWebApplication(_service(tmp_path))
    server = make_server("127.0.0.1", 0, app)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_job_list_refresh_review_page_and_export_gate(
    page: Page, web_base_url: str
) -> None:
    page.goto(web_base_url + "/")
    expect(page).to_have_title("CS2 POV Translator")
    expect(page.locator("#workspace-status")).to_contain_text("工作区状态：健康")
    expect(page.locator("#job-list")).to_contain_text("Web fixture")

    page.get_by_role("button", name="刷新 Job").click()
    expect(page.locator("#job-list")).to_contain_text("draft_timeline_ready")

    page.goto(web_base_url + "/jobs/job-web/rounds/round-001/review")
    expect(page.get_by_test_id("review-page")).to_be_visible()
    expect(page.get_by_test_id("review-status")).to_contain_text("已完成 2 条")
    expect(page.get_by_test_id("review-cues").locator("tbody tr")).to_have_count(2)
    expect(page.get_by_test_id("media-status")).to_contain_text("持久音频")

    response = page.request.get(web_base_url + "/api/v1/jobs/job-web/exports")
    assert response.ok
    payload = response.json()
    assert payload["gates"]["draft"] is True
    assert payload["gates"]["reviewed"] is False
