"""Verify preview, export, SRT, glossary against a completed job."""
import sys, time, socket, threading, urllib.request, json, os
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

JOB_ID = "8e862255"
BASE_URL = "http://127.0.0.1:8765"

_results = []

def check(name, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    _results.append((status, name, detail))
    print(f"  {'✅' if condition else '❌'} {name}" + (f" — {detail}" if detail else ""))


def start_server():
    import uvicorn
    from cs2tl.web.app import app
    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    return server, t


def wait_for_port(host="127.0.0.1", port=8765, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=1)
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.5)
    return False


def run():
    print("=" * 60)
    print("Verification of completed job:", JOB_ID)
    print("=" * 60)

    # Must register the job in the in-memory _jobs dict
    from cs2tl.web.routes import _jobs
    from cs2tl.config import default_cache_dir
    cache_dir = Path(default_cache_dir()) / JOB_ID

    # Check what's in the cache
    print(f"\nCache dir: {cache_dir}")
    progress_file = cache_dir / "progress.json"
    pdata = json.loads(progress_file.read_text(encoding="utf-8"))
    print(f"Progress: {pdata['done']}/{pdata['total']} — {pdata['stage_desc']}")

    # Start server and register the job
    print("\nStarting server...")
    server, _ = start_server()
    if not wait_for_port():
        print("❌ Server failed")
        return 1
    print("✅ Server ready")

    # Find the demo file in cache
    demos = list(cache_dir.glob("*.dem.zst")) + list(cache_dir.glob("*.dem"))
    demo_path = str(demos[0]) if demos else "unknown"

    _jobs[JOB_ID] = {
        "demo_path": demo_path,
        "pid": 0,
        "cache_dir": str(cache_dir),
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        try:
            # ── Preview ───────────────────────────────────
            print("\n── Preview Page ──")
            page.goto(f"{BASE_URL}/preview/{JOB_ID}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            content = page.content()
            check("Preview loads", len(content) > 5000,
                  f"{len(content)} chars")

            # Check for messages
            msg_count = page.locator('.chat-message').count()
            check("Messages visible", msg_count > 0,
                  f"{msg_count} messages rendered")

            # Check team sidebar
            has_sidebar = "Team 2" in content or "Team 3" in content
            check("Team sidebar", has_sidebar)

            # Get some message text
            first_orig = page.locator('.msg-original').first
            first_trans = page.locator('.msg-translated').first
            if first_orig.count() > 0:
                orig_text = first_orig.inner_text()
                check("Original text present", len(orig_text) > 0,
                      orig_text[:50])
            if first_trans.count() > 0:
                trans_text = first_trans.inner_text()
                check("Translation text present", len(trans_text) > 0,
                      trans_text[:50])

            page.screenshot(path="D:/agent_workspace/cs2povtranslator/tests/screenshots/verify-preview.png",
                          full_page=True)

            # ── Export ────────────────────────────────────
            print("\n── Export Page ──")
            page.goto(f"{BASE_URL}/export/{JOB_ID}")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            content = page.content()
            check("Export page loads", len(content) > 3000)

            # Check stats
            has_total = "900" in content or "total" in content.lower()
            check("Stats show segment count", has_total)

            has_dl = "下载" in content or "SRT" in content
            check("Download buttons", has_dl)

            page.screenshot(path="D:/agent_workspace/cs2povtranslator/tests/screenshots/verify-export.png",
                          full_page=True)

            # ── SRT Download ──────────────────────────────
            print("\n── SRT Download ──")
            for team in ["2", "3"]:
                try:
                    req = urllib.request.Request(
                        f"{BASE_URL}/export/{JOB_ID}/download/{team}")
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        body = resp.read().decode("utf-8")
                    is_valid = "-->" in body
                    check(f"Team {team} SRT download", is_valid,
                          f"{len(body)} bytes, {body.count(chr(10))} lines")
                except Exception as e:
                    check(f"Team {team} SRT download", False, str(e)[:80])

            # ── Glossary ──────────────────────────────────
            print("\n── Glossary Page ──")
            page.goto(f"{BASE_URL}/glossary")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(2000)

            content = page.content()

            # Should have de_dust2 or de_mirage terms
            has_dust2 = "de_dust2" in content or "A short" in content or "A大道" in content
            has_mirage = "de_mirage" in content or "Mirage" in content
            check("Shows de_dust2 terms", has_dust2)
            check("Shows de_mirage terms", has_mirage)

            # Count terms in table
            rows = page.locator('table tbody tr').count()
            check("Term table has rows", rows > 10,
                  f"{rows} terms visible")

            # Try search
            search_input = page.locator('input[type="search"]')
            if search_input.count() > 0:
                # Use press_sequentially to trigger 'keyup' events HTMX listens for
                search_input.click()
                search_input.press_sequentially("ninja", delay=50)
                page.wait_for_timeout(1500)  # 300ms debounce + HTMX request + render
                after_search = page.locator('table tbody tr').count()
                check("Search filters terms", after_search < rows and after_search > 0,
                      f"{rows} → {after_search} (searched 'ninja')")
                # Navigate back to clear search (HTMX full-page response can duplicate DOM)
                page.goto(f"{BASE_URL}/glossary")
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(500)

            # Verify locked (system) terms can't be deleted
            lock_icons = page.locator('text=🔒').count()
            check("System terms show lock icon", lock_icons > 0,
                  f"{lock_icons} locked terms")

            page.screenshot(path="D:/agent_workspace/cs2povtranslator/tests/screenshots/verify-glossary.png",
                          full_page=True)

        finally:
            browser.close()

    # Clean up the in-memory job
    _jobs.pop(JOB_ID, None)
    server.should_exit = True

    # ── Summary ─────────────────────────────────────────
    passed = sum(1 for r in _results if r[0] == "PASS")
    failed = sum(1 for r in _results if r[0] == "FAIL")

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{passed+failed} passed" +
          (f", {failed} FAILED" if failed else " — ALL PASSED"))
    print("=" * 60)
    for status, name, detail in _results:
        print(f"  {'✅' if status=='PASS' else '❌'} {name}" +
              (f" — {detail}" if detail else ""))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
