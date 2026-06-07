"""Design review screenshot capture for all pages."""
import sys, os
sys.path.insert(0, 'src')
os.environ['CS2TL_CONFIG'] = ''

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
OUT = "D:/agent_workspace/cs2povtranslator/tests/screenshots"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})

    pages = [
        ("design-import", f"{BASE}/import"),
        ("design-glossary", f"{BASE}/glossary"),
        # Preview/export need a job_id
    ]
    for name, url in pages:
        print(f"Capturing {name}...")
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)
        page.screenshot(path=f"{OUT}/{name}.png", full_page=True)

    # Also capture with a job (use the completed job 8e862255)
    # Register it via the API
    import urllib.request, json
    # We can't register via API, just check if the progress page works for it
    for name, url in [
        ("design-progress", f"{BASE}/progress/8e862255"),
        ("design-preview", f"{BASE}/preview/8e862255"),
        ("design-export", f"{BASE}/export/8e862255"),
    ]:
        print(f"Capturing {name}...")
        page.goto(url)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)
        page.screenshot(path=f"{OUT}/{name}.png", full_page=True)

    browser.close()
    print("Done")
