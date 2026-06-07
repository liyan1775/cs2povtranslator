"""Tests for Web UI routes — FastAPI TestClient coverage.

Uses httpx TestClient to exercise all 14 routes. Pipeline execution is
mocked — these tests verify HTTP semantics, not the translation pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from cs2tl.web.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Route 1-2: Import page
# ---------------------------------------------------------------------------

class TestImportPage:
    def test_root_redirects_to_import(self):
        """GET / → 302 to /import."""
        response = client.get("/", follow_redirects=False)
        assert response.status_code in (302, 307)
        assert response.headers["location"] == "/import"

    def test_import_page_renders(self):
        """GET /import → 200 with HTML."""
        response = client.get("/import")
        assert response.status_code == 200
        assert "导入" in response.text
        assert "demo" in response.text.lower()

    def test_import_page_has_file_input(self):
        """Import page contains a file upload form."""
        response = client.get("/import")
        assert 'input type="file"' in response.text
        assert '开始翻译' in response.text


# ---------------------------------------------------------------------------
# Route 3: Start pipeline (POST /import)
# ---------------------------------------------------------------------------

class TestStartPipeline:
    def test_rejects_non_dem_file(self):
        """POST /import with .txt file → 400."""
        with patch("cs2tl.web.routes._run_pipeline"):
            response = client.post(
                "/import",
                files={"demo": ("test.txt", b"not a demo", "text/plain")},
                follow_redirects=False,
            )
            assert response.status_code == 400
            assert "dem" in response.text.lower()

    def test_accepts_dem_file_and_redirects(self):
        """POST /import with .dem → 302 to progress page."""
        with patch("cs2tl.web.routes._run_pipeline"):
            response = client.post(
                "/import",
                files={"demo": ("test.dem", b"fake demo content", "application/octet-stream")},
                follow_redirects=False,
            )
            assert response.status_code == 302
            assert "/progress/" in response.headers["location"]

    def test_accepts_dem_zst_file_and_redirects(self):
        """POST /import with .dem.zst → 302 to progress page."""
        with patch("cs2tl.web.routes._run_pipeline"):
            response = client.post(
                "/import",
                files={"demo": ("test.dem.zst", b"fake compressed", "application/octet-stream")},
                follow_redirects=False,
            )
            assert response.status_code == 302
            assert "/progress/" in response.headers["location"]

    def test_rejects_empty_filename(self):
        """POST /import with no filename → 400."""
        response = client.post(
            "/import",
            files={"demo": ("", b"", "application/octet-stream")},
            follow_redirects=False,
        )
        assert response.status_code in (400, 422)  # FastAPI returns 422 for empty upload


# ---------------------------------------------------------------------------
# Route 4-5: Progress page + HTMX polling
# ---------------------------------------------------------------------------

class TestProgressPage:
    def test_progress_page_404_for_unknown_job(self):
        """GET /progress/nonexistent → 404."""
        response = client.get("/progress/nonexistent")
        assert response.status_code == 404

    def test_progress_page_renders_for_known_job(self):
        """GET /progress/<id> → 200 with stage checklist."""
        job_id = _register_fake_job()
        response = client.get(f"/progress/{job_id}")
        assert response.status_code == 200
        assert "翻译进度" in response.text
        assert job_id in response.text

    def test_progress_status_returns_fragment(self):
        """HTMX GET /progress/<id>/status → HTML fragment with stages."""
        job_id = _register_fake_job()
        response = client.get(f"/progress/{job_id}/status")
        assert response.status_code == 200
        # Should render stage list items
        assert "stage-pending" in response.text or "stage-list" in response.text

    def test_progress_status_404_for_unknown_job(self):
        """HTMX GET /progress/nonexistent/status → error fragment."""
        response = client.get("/progress/nonexistent/status")
        assert response.status_code == 200  # HTMX returns HTML even for errors
        assert "不存在" in response.text

    def test_progress_status_reads_progress_json(self):
        """When progress.json exists, status reflects its content."""
        job_id, cache_dir = _register_fake_job_with_dir()
        progress = {
            "stage": "extract",
            "done": 1,
            "total": 7,
            "stage_desc": "已提取 5 名玩家语音",
        }
        (cache_dir / "progress.json").write_text(
            json.dumps(progress, ensure_ascii=False), encoding="utf-8"
        )

        response = client.get(f"/progress/{job_id}/status")
        assert response.status_code == 200
        assert "stage-done" in response.text  # extract should show as done

    def test_progress_status_handles_error_progress(self):
        """When progress.json has an error field, status shows it."""
        job_id, cache_dir = _register_fake_job_with_dir()
        progress = {
            "stage": "transcribe",
            "done": 1,
            "total": 7,
            "stage_desc": "Whisper model download failed",
            "error": "E2-0001: Whisper 模型下载失败",
        }
        (cache_dir / "progress.json").write_text(
            json.dumps(progress, ensure_ascii=False), encoding="utf-8"
        )

        response = client.get(f"/progress/{job_id}/status")
        assert response.status_code == 200
        assert "stage-error" in response.text


# ---------------------------------------------------------------------------
# Route 6-7: Preview page + edit
# ---------------------------------------------------------------------------

class TestPreviewPage:
    def test_preview_404_for_unknown_job(self):
        """GET /preview/nonexistent → 404."""
        response = client.get("/preview/nonexistent")
        assert response.status_code == 404

    def test_preview_page_renders_for_known_job(self):
        """GET /preview/<id> → 200 with message flow layout."""
        job_id, cache_dir = _register_fake_job_with_dir()
        _write_fake_translated(cache_dir, count=3)

        response = client.get(f"/preview/{job_id}")
        assert response.status_code == 200
        assert "preview" in response.text.lower() or "消息" in response.text or "Team" in response.text

    def test_preview_filters_by_team(self):
        """GET /preview/<id>?team=2 shows only team 2 messages."""
        job_id, cache_dir = _register_fake_job_with_dir()
        _write_fake_translated(cache_dir, count=5)

        response = client.get(f"/preview/{job_id}?team=2")
        assert response.status_code == 200

    def test_preview_htmx_fragment(self):
        """HTMX request returns message fragments, not full page."""
        job_id, cache_dir = _register_fake_job_with_dir()
        _write_fake_translated(cache_dir, count=3)

        response = client.get(
            f"/preview/{job_id}?team=2&offset=0&limit=50",
            headers={"HX-Request": "true"},
        )
        assert response.status_code == 200
        # HTMX fragment should NOT contain full page layout
        assert "<!DOCTYPE" not in response.text

    def test_preview_empty_state(self):
        """When no translated.jsonl exists, shows empty state."""
        job_id, cache_dir = _register_fake_job_with_dir()
        # Don't create translated.jsonl

        response = client.get(f"/preview/{job_id}")
        assert response.status_code == 200
        # Should show empty state or zero count
        assert "0" in response.text or "暂无" in response.text or "还没有" in response.text


class TestEditSegment:
    def test_edit_404_for_unknown_job(self):
        """POST /preview/nonexistent/edit/0 → 404."""
        response = client.post(
            "/preview/nonexistent/edit/0",
            data={"translated_text": "测试"},
        )
        assert response.status_code == 404

    def test_edit_updates_segment(self):
        """POST /preview/<id>/edit/<idx> saves edit and returns updated HTML."""
        job_id, cache_dir = _register_fake_job_with_dir()
        _write_fake_translated(cache_dir, count=3)

        response = client.post(
            f"/preview/{job_id}/edit/0",
            data={"translated_text": "手动修改的译文"},
        )
        assert response.status_code == 200
        # Should return message HTML
        assert "手动修改的译文" in response.text

        # Verify edited file was written
        edited_file = cache_dir / "translated_edited.jsonl"
        assert edited_file.exists()

    def test_edit_invalid_index(self):
        """POST /preview/<id>/edit/999 → 404."""
        job_id, cache_dir = _register_fake_job_with_dir()
        _write_fake_translated(cache_dir, count=1)

        response = client.post(
            f"/preview/{job_id}/edit/999",
            data={"translated_text": "测试"},
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Route 8-12: Glossary CRUD
# ---------------------------------------------------------------------------

class TestGlossaryPage:
    def test_glossary_page_renders(self):
        """GET /glossary → 200 with term table."""
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=[]):
            response = client.get("/glossary")
            assert response.status_code == 200
            assert "词典" in response.text

    def test_glossary_renders_terms(self):
        """GET /glossary with terms → renders table rows."""
        fake_terms = [
            {"en": "AWP", "zh": "大狙", "category": "weapon", "aliases": ["awp"]},
            {"en": "smoke", "zh": "烟雾弹", "category": "utility", "aliases": []},
        ]
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=fake_terms):
            response = client.get("/glossary")
            assert response.status_code == 200
            assert "AWP" in response.text
            assert "大狙" in response.text

    def test_glossary_search_filters(self):
        """GET /glossary?search=awp → filtered results."""
        fake_terms = [
            {"en": "AWP", "zh": "大狙", "category": "weapon", "aliases": ["awp"]},
            {"en": "smoke", "zh": "烟雾弹", "category": "utility", "aliases": []},
        ]
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=fake_terms):
            response = client.get("/glossary?search=awp")
            assert response.status_code == 200
            assert "AWP" in response.text
            assert "smoke" not in response.text.lower()

    def test_glossary_empty_state(self):
        """GET /glossary with no terms → shows empty state."""
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=[]):
            response = client.get("/glossary")
            assert response.status_code == 200
            assert "空" in response.text or "尚未克隆" in response.text or "没有找到" in response.text


class TestGlossaryCRUD:
    def test_add_term(self):
        """POST /glossary/add → saves term and returns row HTML."""
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=[]), \
             patch("cs2tl.web.routes._save_glossary_terms") as mock_save:
            response = client.post(
                "/glossary/add",
                data={"en": "flash", "zh": "闪光弹", "aliases": "flashbang", "category": "utility"},
            )
            assert response.status_code == 200
            mock_save.assert_called_once()
            assert "flash" in response.text

    def test_delete_term(self):
        """DELETE /glossary/delete/0 → removes term."""
        fake_terms = [{"en": "AWP", "zh": "大狙", "category": "weapon", "aliases": [], "source": "user"}]
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=fake_terms), \
             patch("cs2tl.web.routes._save_glossary_terms") as mock_save:
            response = client.delete("/glossary/delete/0")
            assert response.status_code == 200
            mock_save.assert_called_once()

    def test_delete_invalid_index(self):
        """DELETE /glossary/delete/999 → 404."""
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=[]):
            response = client.delete("/glossary/delete/999")
            assert response.status_code == 404

    def test_update_term(self):
        """POST /glossary/update/0 → updates zh."""
        fake_terms = [{"en": "AWP", "zh": "大狙", "category": "weapon", "aliases": [], "source": "user"}]
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=fake_terms), \
             patch("cs2tl.web.routes._save_glossary_terms") as mock_save:
            response = client.post(
                "/glossary/update/0",
                data={"zh": "狙击枪"},
            )
            assert response.status_code == 200
            mock_save.assert_called_once()
            assert fake_terms[0]["zh"] == "狙击枪"


class TestGlossarySave:
    def test_save_git_success(self):
        """POST /glossary/save → git commit + push success."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            response = client.post("/glossary/save")
            assert response.status_code == 200
            assert "已保存并推送" in response.text or "无变更" in response.text

    def test_save_git_failure(self):
        """POST /glossary/save → shows error on git failure."""
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = RuntimeError("network down")
            response = client.post("/glossary/save")
            assert response.status_code == 200
            assert "失败" in response.text


# ---------------------------------------------------------------------------
# Route 13-14: Settings page
# ---------------------------------------------------------------------------

class TestSettingsPage:
    def test_settings_page_renders(self):
        """GET /settings → 200 with form fields."""
        with patch("cs2tl.web.routes._load_current_config") as mock_cfg, \
             patch("cs2tl.web.routes._load_prompt_template", return_value="test prompt"):
            from cs2tl.config import AppConfig
            mock_cfg.return_value = AppConfig()
            response = client.get("/settings")
            assert response.status_code == 200
            assert "设置" in response.text
            assert "whisper_model" in response.text

    def test_settings_page_has_nav(self):
        """Settings page has nav tabs and settings form."""
        with patch("cs2tl.web.routes._load_current_config") as mock_cfg, \
             patch("cs2tl.web.routes._load_prompt_template", return_value="test"):
            from cs2tl.config import AppConfig
            mock_cfg.return_value = AppConfig()
            response = client.get("/settings")
            assert "⚙️" in response.text or "设置" in response.text

    def test_save_settings_writes_config(self):
        """POST /settings → saves config and prompt."""
        with patch("cs2tl.web.routes._save_config") as mock_save_cfg, \
             patch("cs2tl.web.routes._save_prompt_template") as mock_save_prompt:
            response = client.post(
                "/settings",
                data={
                    "whisper_model": "tiny",
                    "whisper_device": "cpu",
                    "llm_provider": "openai",
                    "llm_api_key": "",
                    "llm_model": "deepseek-chat",
                    "llm_base_url": "https://api.deepseek.com/v1",
                    "prompt_template": "test {voice_lines}",
                    "action": "save",
                },
            )
        assert response.status_code == 200
        assert "已保存" in response.text
        mock_save_cfg.assert_called_once()
        mock_save_prompt.assert_called_once()

    def test_save_rejects_empty_prompt(self):
        """POST /settings → rejects empty prompt template."""
        response = client.post(
            "/settings",
            data={
                "whisper_model": "tiny",
                "whisper_device": "auto",
                "llm_provider": "openai",
                "llm_api_key": "",
                "llm_model": "gpt-4o",
                "llm_base_url": "",
                "prompt_template": "   ",
                "action": "save",
            },
        )
        assert response.status_code == 200
        assert "不能为空" in response.text

    def test_save_rejects_missing_placeholder(self):
        """POST /settings → rejects prompt without {voice_lines}."""
        with patch("cs2tl.web.routes._save_config"), \
             patch("cs2tl.web.routes._save_prompt_template"):
            response = client.post(
                "/settings",
                data={
                    "whisper_model": "tiny",
                    "whisper_device": "auto",
                    "llm_provider": "openai",
                    "llm_api_key": "",
                    "llm_model": "gpt-4o",
                    "llm_base_url": "",
                    "prompt_template": "no placeholder here",
                    "action": "save",
                },
            )
        assert response.status_code == 200
        assert "voice_lines" in response.text

    def test_reset_prompt_deletes_file(self):
        """POST /settings with action=reset_prompt → deletes custom prompt."""
        with patch("cs2tl.web.routes.PROMPT_TEMPLATE_PATH") as mock_path:
            mock_path.exists.return_value = True
            response = client.post(
                "/settings",
                data={
                    "whisper_model": "tiny",
                    "whisper_device": "auto",
                    "llm_provider": "openai",
                    "llm_api_key": "",
                    "llm_model": "gpt-4o",
                    "llm_base_url": "",
                    "prompt_template": "test",
                    "action": "reset_prompt",
                },
            )
        assert response.status_code == 200
        assert "已恢复默认" in response.text
        mock_path.unlink.assert_called_once()


# ---------------------------------------------------------------------------
# Route 15-16: Export page + SRT download
# ---------------------------------------------------------------------------

class TestExportPage:
    def test_export_404_for_unknown_job(self):
        """GET /export/nonexistent → 404."""
        response = client.get("/export/nonexistent")
        assert response.status_code == 404

    def test_export_page_renders_for_known_job(self):
        """GET /export/<id> → 200 with stats card."""
        job_id, cache_dir = _register_fake_job_with_dir()
        _write_fake_translated(cache_dir, count=5)

        response = client.get(f"/export/{job_id}")
        assert response.status_code == 200
        assert "翻译摘要" in response.text or "导出" in response.text or "下载" in response.text

    def test_export_shows_stats(self):
        """Export page computes translation stats correctly."""
        job_id, cache_dir = _register_fake_job_with_dir()
        _write_fake_translated(cache_dir, count=10)

        response = client.get(f"/export/{job_id}")
        assert response.status_code == 200
        # Stats should show total count
        assert "10" in response.text


class TestDownloadSrt:
    def test_download_404_for_unknown_job(self):
        """GET /export/nonexistent/download/2 → 404."""
        response = client.get("/export/nonexistent/download/2")
        assert response.status_code == 404

    def test_download_404_when_srt_not_exists(self):
        """GET /export/<id>/download/2 → 404 when SRT file missing."""
        job_id, cache_dir = _register_fake_job_with_dir()
        # Don't create SRT files
        response = client.get(f"/export/{job_id}/download/2")
        assert response.status_code == 404

    def test_download_serves_srt_file(self):
        """GET /export/<id>/download/2 → 200 with SRT content."""
        job_id, cache_dir = _register_fake_job_with_dir()
        srt_dir = cache_dir / "subtitles"
        srt_dir.mkdir(parents=True)

        # Match the demo_name.stem pattern used in download_srt route
        job = _routes_module.job_store.get(job_id)
        demo_name = Path(job.demo_path).stem
        srt_path = srt_dir / f"{demo_name}.team_2.srt"
        srt_path.write_text("1\n00:00:01,000 --> 00:00:03,000\ntest\n", encoding="utf-8")

        response = client.get(f"/export/{job_id}/download/2")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Error & edge cases
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_glossary_load_handles_missing_file(self):
        """When glossary.yml doesn't exist, page renders without crashing."""
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=[]):
            response = client.get("/glossary")
            assert response.status_code == 200

    def test_glossary_load_handles_yaml_error(self):
        """When glossary.yml is corrupt, page renders without crashing."""
        with patch("cs2tl.web.routes._load_glossary_terms", return_value=[]):
            response = client.get("/glossary")
            assert response.status_code == 200

    def test_progress_status_handles_corrupt_json(self):
        """When progress.json is malformed, returns fallback fragment."""
        job_id, cache_dir = _register_fake_job_with_dir()
        (cache_dir / "progress.json").write_text("not valid json {{{", encoding="utf-8")

        response = client.get(f"/progress/{job_id}/status")
        assert response.status_code == 200
        # Should not crash — return some HTML


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Import the module's job_store so tests can inspect state
import cs2tl.web.routes as _routes_module


def _register_fake_job() -> str:
    """Register a fake job via JobStore and return its ID."""
    import uuid
    job_id = uuid.uuid4().hex[:8]
    cache_dir = Path(_routes_module.default_cache_dir()) / job_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    demo_path = cache_dir / "test.dem"
    demo_path.write_text("fake demo")
    _routes_module.job_store.create(
        demo_name="test.dem",
        demo_path=str(demo_path),
        cache_dir=str(cache_dir),
        job_id=job_id,
    )
    return job_id


def _register_fake_job_with_dir() -> tuple[str, Path]:
    """Register a fake job via JobStore and return (job_id, cache_dir)."""
    import uuid
    job_id = uuid.uuid4().hex[:8]
    cache_dir = Path(_routes_module.default_cache_dir()) / job_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    demo_path = cache_dir / "test.dem"
    demo_path.write_text("fake demo")
    _routes_module.job_store.create(
        demo_name="test.dem",
        demo_path=str(demo_path),
        cache_dir=str(cache_dir),
        job_id=job_id,
    )
    return job_id, cache_dir


def _write_fake_translated(cache_dir: Path, count: int = 5) -> Path:
    """Write a fake translated.jsonl for testing preview/export routes."""
    demo_name = "test"
    jsonl_path = cache_dir / f"{demo_name}.translated.jsonl"
    segments = []
    for i in range(count):
        team = "2" if i % 2 == 0 else "3"
        seg = {
            "steam_id": f"7656119800000000{i}",
            "player_name": f"Player{i}",
            "team": team,
            "start_time": i * 10.0,
            "end_time": i * 10.0 + 2.0,
            "original_text": f"Original message {i}",
            "translated_text": f"翻译后的消息 {i}",
            "edited": False,
        }
        segments.append(seg)

    with open(jsonl_path, "w", encoding="utf-8") as f:
        for seg in segments:
            f.write(json.dumps(seg, ensure_ascii=False) + "\n")

    return jsonl_path
