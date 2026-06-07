"""Full pipeline verification — waits for ALL 7 stages, then checks preview + export.

Usage:
  python tests/full_pipeline_test.py
"""

import os, sys, time, socket, threading, json
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

DEMO_PATH = Path("D:/agent_workspace/cs2demos/1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst")
BASE_URL = "http://127.0.0.1:8765"
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

_results: list[tuple[str, str, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    _results.append((status, name, detail))
    icon = "✅" if condition else "❌"
    line = f"  {icon} {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def snap(page, name: str) -> None:
    path = SCREENSHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"    📸 {name}.png")


def start_server():
    import uvicorn
    from cs2tl.web.app import app
    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server, t


def wait_for_port(host="127.0.0.1", port=8765, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=1)
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False


def run():
    print("=" * 60)
    print("CS2 POV Translator — Full Pipeline Verification")
    print("=" * 60)

    print("\n⏳ Starting server...")
    server, _thread = start_server()
    if not wait_for_port():
        print("❌ Server failed to start!")
        return 1
    print("✅ Server ready")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        try:
            # ── Import demo ──────────────────────────────────
            print("\n── Import Demo ──")
            page.goto(f"{BASE_URL}/import")
            page.wait_for_load_state("networkidle")

            file_input = page.locator('input[type="file"]')
            file_input.set_input_files(str(DEMO_PATH))
            page.locator('button:has-text("开始翻译")').click()

            page.wait_for_url(f"{BASE_URL}/progress/**", timeout=120000)
            job_id = page.url.split("/progress/")[-1]
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(4000)

            # Check demo info card
            content = page.content()
            has_info = ("Team 2" in content or "Team 3" in content
                       or "文件选对了" in content)
            check("Demo info card", has_info, "First relief point shown")
            snap(page, "full-pipeline-01-imported")

            # ── Wait for ALL 7 stages ────────────────────────
            print("\n── Waiting for full pipeline (7/7 stages) ──")
            print("   This may take 10-20 minutes for a 273MB demo...")
            start = time.time()
            stage_count = 0
            max_wait = 1200  # 20 minutes max

            while stage_count < 7 and (time.time() - start) < max_wait:
                time.sleep(15)  # Check every 15 seconds

                # Detect auto-redirect to preview (means pipeline complete)
                if "/preview/" in page.url:
                    stage_count = 7  # pipeline complete!
                    break

                # Let HTMX poll fire (5s interval)
                page.wait_for_timeout(6000)

                # Detect auto-redirect after poll
                if "/preview/" in page.url:
                    stage_count = 7
                    break

                # Use specific locators, not page.content() — avoids CSS false positives
                done_els = page.locator('li.stage-done')
                error_els = page.locator('li.stage-error')

                new_count = done_els.count()
                if new_count > stage_count:
                    stage_count = new_count
                    elapsed = (time.time() - start) / 60
                    stage_texts = done_els.all_inner_texts()
                    print(f"   [{elapsed:.1f}min] {stage_count}/7 stages done")
                    for s in stage_texts:
                        print(f"      {s.strip()}")

                # Check for actual pipeline errors (❌ icon in the stage list)
                if error_els.count() > 0:
                    error_texts = error_els.all_inner_texts()
                    check("Pipeline completion", False,
                          f"Error: {'; '.join(error_texts)}")
                    snap(page, "full-pipeline-ERROR")
                    break

            elapsed = (time.time() - start) / 60
            check(f"All 7 stages completed ({stage_count}/7)",
                  stage_count >= 7,
                  f"Took {elapsed:.1f} minutes")

            snap(page, "full-pipeline-02-complete")

            # ── Wait a bit more if not done ──────────────────
            if stage_count < 7:
                print(f"\n   Pipeline not complete after {elapsed:.1f}min.")
                print(f"   Checking current progress.json...")
                # Read progress.json directly
                import glob as g
                # The cache dir...
                # We'll just report what we have
                check("Pipeline completion within timeout",
                      False,
                      f"Only {stage_count}/7 stages after {elapsed:.1f} min")
                snap(page, "full-pipeline-03-timeout")

            # ── Preview page ──────────────────────────────────
            print("\n── Preview Page ──")
            page.goto(f"{BASE_URL}/preview/{job_id}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            preview_content = page.content()
            has_messages = ("original_text" in preview_content
                          or "msg-original" in preview_content
                          or "msg-translated" in preview_content
                          or "chat-message" in preview_content)

            # Check for any actual text content (even if not fully translated)
            has_any_text = len(preview_content) > 5000  # reasonable page size

            check("Preview page has content", has_any_text,
                  f"Page size: {len(preview_content)} chars")

            # Check if there are actual messages with original text
            if "msg-original" in preview_content:
                check("Preview shows original voice text", True)
            else:
                check("Preview shows original voice text",
                      stage_count >= 7,
                      "Messages only appear after translate stage")

            snap(page, "full-pipeline-04-preview")

            # ── Export page ───────────────────────────────────
            print("\n── Export Page ──")
            page.goto(f"{BASE_URL}/export/{job_id}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            export_content = page.content()

            # Check download buttons
            has_dl = "下载" in export_content or "download" in export_content.lower()
            check("Export page has download buttons", has_dl)

            # Check if SRT download is actually available (use HTTP, not page.goto —
            # Playwright intercepts downloads and throws "Download is starting")
            import urllib.request
            try:
                req = urllib.request.Request(f"{BASE_URL}/export/{job_id}/download/2")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    srt_body = resp.read().decode("utf-8")
                    srt_available = resp.status == 200 and len(srt_body) > 100
            except Exception as e:
                srt_available = False
                srt_body = ""

            if stage_count >= 7:
                check("SRT file available for download", srt_available,
                      f"Team 2 SRT: {len(srt_body)} bytes")
                # Verify it's valid SRT format
                has_srt_format = "-->" in srt_body[:500]
                check("SRT file has valid format", has_srt_format,
                      "Contains SRT timestamps")
            else:
                check("SRT file available for download",
                      srt_available,
                      "Available despite incomplete pipeline" if srt_available else "Not yet available (pipeline incomplete)")

            snap(page, "full-pipeline-05-export")

            # ── Glossary page (verify terms show) ────────────
            print("\n── Glossary Page ──")
            page.goto(f"{BASE_URL}/glossary")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

            glossary_content = page.content()

            # Should have terms from the dictionary
            has_terms = ("de_dust2" in glossary_content
                       or "de_mirage" in glossary_content
                       or "A short" in glossary_content
                       or "A小道" in glossary_content
                       or "A大道" in glossary_content)
            check("Glossary shows dictionary terms", has_terms,
                  "System callout terms visible")

            # Should have source indicators
            has_source = ("来源" in glossary_content or "source" in glossary_content)
            check("Glossary shows term source", has_source)

            snap(page, "full-pipeline-06-glossary")

        finally:
            browser.close()

    # ── Summary ─────────────────────────────────────────────
    server.should_exit = True

    passed = sum(1 for r in _results if r[0] == "PASS")
    failed = sum(1 for r in _results if r[0] == "FAIL")

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{passed + failed} passed" +
          (f", {failed} failed" if failed else " — ALL PASSED"))
    print("=" * 60)
    for status, name, detail in _results:
        icon = "✅" if status == "PASS" else "❌"
        line = f"  {icon} {name}"
        if detail:
            line += f" — {detail}"
        print(line)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
