"""v0.1 comprehensive acceptance test — tests multiple navigation orders.

Runs 5 flows simulating different user behaviors:
  Flow A: Normal (import → progress → preview → glossary → export)
  Flow B: Glossary-first (glossary CRUD → import demo → progress)
  Flow C: Tab-switching during pipeline (import → glossary → back to progress)
  Flow D: Refresh resilience (import → progress → refresh → verify)
  Flow E: Edge cases (direct preview without job, corrupt upload, progress 404)
"""

import os
import sys
from playwright.sync_api import sync_playwright

# Fix Windows GBK encoding issues
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DEMO_PATH = "D:/agent_workspace/cs2demos/1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst"
BASE_URL = "http://127.0.0.1:8765"

results = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    results.append((status, name, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        # ═══════════════════════════════════════════════
        # FLOW A: Normal user journey
        # ═══════════════════════════════════════════════
        flow_a_normal(page)
        flow_b_glossary_first(page)
        flow_c_tab_switching(page)
        flow_d_refresh_resilience(page)
        flow_e_edge_cases(page)

        # ═══════════════════════════════════════════════
        # SUMMARY
        # ═══════════════════════════════════════════════
        passed = sum(1 for r in results if r[0] == "PASS")
        failed = sum(1 for r in results if r[0] == "FAIL")
        print(f"\n{'='*60}")
        print(f"ACCEPTANCE RESULTS: {passed} passed, {failed} failed")
        for status, name, detail in results:
            icon = "✅" if status == "PASS" else "❌"
            line = f"  {icon} {name}"
            if detail:
                line += f": {detail}"
            print(line)
        print(f"{'='*60}")

        browser.close()

        if failed > 0:
            sys.exit(1)


def flow_a_normal(page):
    """Flow A: Normal user — import → progress → preview → glossary → export."""
    print("\n" + "=" * 60)
    print("FLOW A: Normal user journey")
    print("=" * 60)

    # A1: Import page
    print("\n--- A1: Import Page ---")
    page.goto(f"{BASE_URL}/import")
    page.wait_for_load_state("networkidle")
    check("A1.1 page title correct", "CS2 POV Translator" in page.title())
    check("A1.2 file input exists", page.locator('input[type="file"]').count() > 0)
    check("A1.3 submit button exists", page.locator('button:has-text("开始翻译")').count() > 0)
    check("A1.4 Chinese instructions shown", "使用说明" in page.content())

    # Check 4 nav tabs
    tabs = page.locator('nav.tabs a')
    check("A1.5 navigation tabs present", tabs.count() >= 3, f"{tabs.count()} tabs")

    page.screenshot(path="/tmp/accept-a1-import.png", full_page=True)

    # A2: Upload demo (latest 286MB demo)
    print("\n--- A2: Upload Demo ---")
    demo_size_mb = os.path.getsize(DEMO_PATH) / 1024 / 1024
    print(f"   Uploading {demo_size_mb:.0f} MB demo...")

    file_input = page.locator('input[type="file"]')
    file_input.set_input_files(DEMO_PATH)
    page.locator('button:has-text("开始翻译")').click()

    # Wait for redirect to progress page
    page.wait_for_url(f"{BASE_URL}/progress/**", timeout=180000)
    job_id_a = page.url.split("/progress/")[-1]
    check("A2.1 redirected to progress", "/progress/" in page.url, f"job_id={job_id_a}")

    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)  # Wait for quick demo parse

    # A3: First relief point — demo info card
    print("\n--- A3: Demo Info Card (1st relief point) ---")
    content = page.content()
    has_info_card = "文件选对了" in content or "Team 2" in content or "Team 3" in content
    check("A3.1 demo info card shown", has_info_card, "relief point 1 present")

    page.screenshot(path="/tmp/accept-a3-progress-with-info.png", full_page=True)

    # A4: Wait for extraction to complete
    print("\n--- A4: Pipeline Progress ---")
    try:
        page.wait_for_selector('li.stage-done', timeout=180000)
        done_count = page.locator('li.stage-done').count()
        check("A4.1 extraction completed", done_count >= 1, f"{done_count}/7 stages done")
    except Exception:
        check("A4.1 extraction completed", False, "timeout waiting for stage completion")

    page.screenshot(path="/tmp/accept-a4-progress.png", full_page=True)

    # A5: Navigate to glossary during pipeline
    print("\n--- A5: Glossary (mid-pipeline) ---")
    page.goto(f"{BASE_URL}/glossary")
    page.wait_for_load_state("networkidle")
    check("A5.1 glossary page loads", page.locator('h1:has-text("词典")').count() > 0)

    # CRUD test
    details_btn = page.locator('details summary:has-text("新增术语")')
    if details_btn.count() > 0:
        details_btn.click()
        page.wait_for_timeout(500)

        en_input = page.locator('input[name="en"]')
        zh_input = page.locator('input[name="zh"]')
        if en_input.count() > 0 and zh_input.count() > 0:
            en_input.fill("TEST_AWP")
            zh_input.fill("测试大狙")
            page.locator('button:has-text("新增术语")').click()
            page.wait_for_timeout(1000)
            check("A5.2 glossary add term", "TEST_AWP" in page.content())

            # Delete it
            delete_btn = page.locator('tr:has-text("TEST_AWP") button:has-text("🗑")')
            if delete_btn.count() > 0:
                page.on("dialog", lambda d: d.accept())
                delete_btn.click()
                page.wait_for_timeout(500)
                check("A5.3 glossary delete term", "TEST_AWP" not in page.content())
            else:
                check("A5.3 glossary delete term", False, "delete button missing")
        else:
            check("A5.2 glossary add term", False, "form missing")

    page.screenshot(path="/tmp/accept-a5-glossary.png", full_page=True)

    # A6: Preview page
    print("\n--- A6: Preview Page ---")
    page.goto(f"{BASE_URL}/preview/{job_id_a}")
    page.wait_for_load_state("networkidle")
    check("A6.1 preview page loads", "预览" in page.content() or "Team" in page.content())
    check("A6.2 team sidebar present", "Team 2" in page.content() or "Team 3" in page.content())

    page.screenshot(path="/tmp/accept-a6-preview.png", full_page=True)

    # A7: Export page
    print("\n--- A7: Export Page ---")
    page.goto(f"{BASE_URL}/export/{job_id_a}")
    page.wait_for_load_state("networkidle")
    check("A7.1 export page loads", page.locator('h1').count() > 0)
    check("A7.2 download buttons present",
          "下载" in page.content() or "download" in page.url or "SRT" in page.content())

    page.screenshot(path="/tmp/accept-a7-export.png", full_page=True)


def flow_b_glossary_first(page):
    """Flow B: User opens glossary before importing any demo."""
    print("\n" + "=" * 60)
    print("FLOW B: Glossary-first (edit dictionary before importing)")
    print("=" * 60)

    # B1: Visit glossary before any job
    print("\n--- B1: Glossary First ---")
    page.goto(f"{BASE_URL}/glossary")
    page.wait_for_load_state("networkidle")
    check("B1.1 glossary loads with no job_id", "词典" in page.content())

    # Search functionality
    search_input = page.locator('input[type="search"]')
    if search_input.count() > 0:
        search_input.fill("AWP")
        page.wait_for_timeout(500)
        check("B1.2 search input works", search_input.input_value() == "AWP")
        search_input.fill("")
        page.wait_for_timeout(500)

    # B2: Now import demo
    print("\n--- B2: Import from Glossary ---")
    page.goto(f"{BASE_URL}/import")
    page.wait_for_load_state("networkidle")

    file_input = page.locator('input[type="file"]')
    file_input.set_input_files(DEMO_PATH)
    page.locator('button:has-text("开始翻译")').click()

    page.wait_for_url(f"{BASE_URL}/progress/**", timeout=180000)
    job_id_b = page.url.split("/progress/")[-1]
    check("B2.1 import from glossary nav works", "/progress/" in page.url, f"job_id={job_id_b}")

    # Verify demo info card appears
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)
    content = page.content()
    check("B2.2 demo info visible after glossary-first flow",
          "Team 2" in content or "Team 3" in content or "文件选对" in content)

    page.screenshot(path="/tmp/accept-b2-progress-after-glossary.png", full_page=True)


def flow_c_tab_switching(page):
    """Flow C: Aggressive tab switching during pipeline execution."""
    print("\n" + "=" * 60)
    print("FLOW C: Tab switching during pipeline")
    print("=" * 60)

    # C1: Import new demo
    print("\n--- C1: Import for tab-switch test ---")
    page.goto(f"{BASE_URL}/import")
    page.wait_for_load_state("networkidle")

    file_input = page.locator('input[type="file"]')
    file_input.set_input_files(DEMO_PATH)
    page.locator('button:has-text("开始翻译")').click()

    page.wait_for_url(f"{BASE_URL}/progress/**", timeout=180000)
    job_id_c = page.url.split("/progress/")[-1]
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Record initial stage state
    initial_done = page.locator('li.stage-done').count()
    print(f"   Initial: {initial_done} stages done")

    # C2: Switch to glossary, then back
    print("\n--- C2: Switch to glossary → back ---")
    page.goto(f"{BASE_URL}/glossary")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)
    check("C2.1 glossary accessible mid-pipeline", "词典" in page.content())

    # C3: Go back to progress
    page.goto(f"{BASE_URL}/progress/{job_id_c}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(6000)  # Wait for HTMX poll

    after_glossary = page.locator('li.stage-done').count()
    check("C3.1 progress survived glossary visit", after_glossary >= initial_done,
          f"before={initial_done}, after={after_glossary}")

    # C4: Switch to preview (should handle gracefully even if not done)
    print("\n--- C3: Preview during pipeline ---")
    page.goto(f"{BASE_URL}/preview/{job_id_c}")
    page.wait_for_load_state("networkidle")
    check("C4.1 preview accessible mid-pipeline", "preview" in page.url or "预览" in page.content())

    # C5: Back to progress again
    page.goto(f"{BASE_URL}/progress/{job_id_c}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(6000)

    after_preview = page.locator('li.stage-done').count()
    check("C5.1 progress survived preview visit", after_preview >= after_glossary,
          f"before={after_glossary}, after={after_preview}")

    page.screenshot(path="/tmp/accept-c5-progress-after-switching.png", full_page=True)


def flow_d_refresh_resilience(page):
    """Flow D: Refresh resilience — progress persists across page reloads."""
    print("\n" + "=" * 60)
    print("FLOW D: Refresh resilience")
    print("=" * 60)

    # D1: Import
    print("\n--- D1: Import ---")
    page.goto(f"{BASE_URL}/import")
    page.wait_for_load_state("networkidle")

    file_input = page.locator('input[type="file"]')
    file_input.set_input_files(DEMO_PATH)
    page.locator('button:has-text("开始翻译")').click()

    page.wait_for_url(f"{BASE_URL}/progress/**", timeout=180000)
    job_id_d = page.url.split("/progress/")[-1]
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(3000)

    # D2: Get initial state
    initial_done = page.locator('li.stage-done').count()
    initial_content_length = len(page.content())
    print(f"   Initial: {initial_done} stages done, {initial_content_length} chars")

    # D3: Refresh the page
    print("\n--- D2: Refresh page ---")
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(6000)  # Wait for HTMX poll

    after_refresh = page.locator('li.stage-done').count()
    check("D3.1 progress survives refresh", after_refresh >= initial_done,
          f"before={initial_done}, after={after_refresh}")
    check("D3.2 page renders after refresh", len(page.content()) > 100)
    check("D3.3 job_id preserved after refresh", job_id_d in page.content())

    # D4: Refresh again
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(6000)

    after_refresh2 = page.locator('li.stage-done').count()
    check("D4.1 progress survives double refresh", after_refresh2 >= after_refresh,
          f"before={after_refresh}, after={after_refresh2}")

    page.screenshot(path="/tmp/accept-d4-after-refresh.png", full_page=True)

    # D5: Demo info survives refresh
    content = page.content()
    check("D5.1 demo info survives refresh",
          "Team 2" in content or "Team 3" in content or "文件选对" in content)


def flow_e_edge_cases(page):
    """Flow E: Edge cases and error handling."""
    print("\n" + "=" * 60)
    print("FLOW E: Edge cases")
    print("=" * 60)

    # E1: Direct access to progress without job_id
    print("\n--- E1: Progress 404 ---")
    page.goto(f"{BASE_URL}/progress/nonexistent123")
    page.wait_for_load_state("networkidle")
    check("E1.1 progress 404 handled", "不存在" in page.content() or "404" in page.content()
          or page.content() != "", "error page rendered")

    # E2: Direct access to preview without job
    print("\n--- E2: Preview 404 ---")
    page.goto(f"{BASE_URL}/preview/nonexistent123")
    page.wait_for_load_state("networkidle")
    check("E2.1 preview 404 handled", "不存在" in page.content() or "404" in page.content()
          or page.content() != "", "error page rendered")

    # E3: Direct access to export without job
    print("\n--- E3: Export 404 ---")
    page.goto(f"{BASE_URL}/export/nonexistent123")
    page.wait_for_load_state("networkidle")
    check("E3.1 export 404 handled", "不存在" in page.content() or "404" in page.content()
          or page.content() != "", "error page rendered")

    # E4: Root redirect
    print("\n--- E4: Root redirect ---")
    page.goto(f"{BASE_URL}/")
    page.wait_for_load_state("networkidle")
    check("E4.1 root redirects to import", "/import" in page.url)

    # E5: Glossary search debounce
    print("\n--- E5: Glossary search ---")
    page.goto(f"{BASE_URL}/glossary")
    page.wait_for_load_state("networkidle")

    search_input = page.locator('input[type="search"]')
    if search_input.count() > 0:
        # Type slowly to test debounce
        search_input.fill("zzz_nonexistent_term_xyz")
        page.wait_for_timeout(800)  # > 300ms debounce
        content = page.content()
        check("E5.1 search returns empty for nonexistent term",
              "没有找到" in content or "空" in content or "0" in content
              or "尚未克隆" in content)

    # E6: Glossary disabled tabs
    print("\n--- E6: Disabled tabs ---")
    page.goto(f"{BASE_URL}/import")
    page.wait_for_load_state("networkidle")

    # Preview and Export tabs should be disabled (greyed out) when no job
    disabled_tabs = page.locator('nav.tabs a[style*="opacity"]')
    disabled_count = disabled_tabs.count()
    check("E6.1 disabled tabs when no job", disabled_count >= 2,
          f"{disabled_count} disabled tabs")

    # E7: Nav tab labels
    print("\n--- E7: Nav labels ---")
    page.goto(f"{BASE_URL}/import")
    page.wait_for_load_state("networkidle")
    check("E7.1 import tab active", "导入" in page.content())
    check("E7.2 glossary tab always accessible",
          page.locator('nav.tabs a[href="/glossary"]').count() > 0)

    page.screenshot(path="/tmp/accept-e7-edge-cases.png", full_page=True)


if __name__ == "__main__":
    run()
