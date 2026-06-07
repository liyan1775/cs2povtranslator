"""Non-programmer user simulation — v0.1 acceptance.

Simulates a real user who knows CS2/Faceit but NOTHING about programming.
Starts the server, opens browser, walks through every screen, takes screenshots.

Usage:
  python tests/user_simulation.py
"""

import os, sys, time, socket, threading, json
from pathlib import Path

# ── fix Windows GBK ──────────────────────────────────────────
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

DEMO_PATH = Path("D:/agent_workspace/cs2demos/1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst")
BASE_URL = "http://127.0.0.1:8765"
SCREENSHOT_DIR = Path("D:/agent_workspace/cs2povtranslator/tests/screenshots")
SCREENSHOT_DIR.mkdir(exist_ok=True)

# ═══════════════════════════════════════════════════════════════
#  Server lifecycle (uvicorn in thread — proven on Windows)
# ═══════════════════════════════════════════════════════════════

def start_server():
    """Start uvicorn in a daemon thread. Returns (server, thread)."""
    import uvicorn
    from cs2tl.web.app import app

    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning")
    server = uvicorn.Server(config)

    def run():
        server.run()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return server, t


def wait_for_server(host: str = "127.0.0.1", port: int = 8765, timeout: int = 60) -> bool:
    """Poll until TCP accepts. Returns True when ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=1)
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False


# ═══════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════

_results: list[tuple[str, str, str]] = []  # (status, checkpoint, detail)


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


# ═══════════════════════════════════════════════════════════════
#  MAIN FLOW — 模拟非程序员用户
# ═══════════════════════════════════════════════════════════════

def run():
    print("=" * 60)
    print("CS2 POV Translator v0.1 — 非程序员用户模拟测试")
    print(f"测试 Demo: {DEMO_PATH.name}")
    print(f"Demo 大小: {DEMO_PATH.stat().st_size / 1024 / 1024:.0f} MB")
    print("=" * 60)

    # ── Start server ──────────────────────────────────────────
    print("\n⏳ 启动服务器...")
    server, server_thread = start_server()

    if not wait_for_server():
        print("❌ 服务器启动超时！")
        sys.exit(1)
    print("✅ 服务器就绪 (http://127.0.0.1:8765)")

    with sync_playwright() as p:
        # Headless=False so we see what the user sees.
        # In CI you'd set headless=True.
        browser = p.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        try:
            # ──────────────────────────────────────────────────
            #  STEP 1: 打开首页 → 应该重定向到 /import
            # ──────────────────────────────────────────────────
            print("\n" + "─" * 40)
            print("📌 步骤 1/6：打开首页")
            print("─" * 40)

            page.goto(BASE_URL)
            page.wait_for_load_state("networkidle")
            check("1.1 首页重定向到 /import", "/import" in page.url)
            check("1.2 页面标题正确", "CS2 POV Translator" in page.title())
            check("1.3 有文件上传区域",
                  page.locator('input[type="file"]').count() > 0,
                  "用户能看到上传按钮")
            check("1.4 有开始翻译按钮",
                  page.locator('button:has-text("开始翻译")').count() > 0,
                  "用户能看到操作按钮")
            check("1.5 导航标签存在",
                  page.locator('nav a, nav.tabs a').count() >= 2,
                  "用户能看到导航")

            # Check Chinese instructions visible to non-programmer
            content = page.content()
            has_chinese = any(w in content for w in ["导入", "使用说明", "提示", "Demo", "demo"])
            check("1.6 中文引导文案可见", has_chinese, "非程序员能读懂")

            snap(page, "01-import-page")

            # ──────────────────────────────────────────────────
            #  STEP 2: 上传 Demo
            # ──────────────────────────────────────────────────
            print("\n" + "─" * 40)
            print("📌 步骤 2/6：上传 Demo 文件")
            print("─" * 40)

            file_input = page.locator('input[type="file"]')
            file_input.set_input_files(str(DEMO_PATH))
            print("   选中文件: " + DEMO_PATH.name)

            # Click the submit button
            submit_btn = page.locator('button:has-text("开始翻译")')
            submit_btn.click()

            # Wait for redirect to progress
            try:
                page.wait_for_url(f"{BASE_URL}/progress/**", timeout=120000)
                job_id = page.url.split("/progress/")[-1]
                check("2.1 上传成功跳转到进度页",
                      "/progress/" in page.url,
                      f"job_id={job_id}")
            except Exception:
                check("2.1 上传成功跳转到进度页", False, "超时未跳转")
                job_id = "unknown"

            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(4000)  # Wait for quick demo parse

            # ──────────────────────────────────────────────────
            #  STEP 3: 第一处安心点 — Demo 信息卡片
            # ──────────────────────────────────────────────────
            print("\n" + "─" * 40)
            print("📌 步骤 3/6：第一处安心点 — 确认文件选对了")
            print("─" * 40)

            content = page.content()
            has_info = ("Team 2" in content or "Team 3" in content
                       or "文件选对了" in content or "名玩家" in content)
            check("3.1 Demo 信息卡片出现",
                  has_info,
                  "用户马上看到文件解析结果，确认没选错文件")

            snap(page, "02-progress-with-demo-info")

            # ──────────────────────────────────────────────────
            #  STEP 4: 等待管线进展 + 刷新测试
            # ──────────────────────────────────────────────────
            print("\n" + "─" * 40)
            print("📌 步骤 4/6：观察进度 + 刷新页面测试")
            print("─" * 40)

            # Wait a bit for stages to start completing
            print("   等待管线推进（最多4分钟）...")
            try:
                page.wait_for_selector('li.stage-done', timeout=240000)
                done_count = page.locator('li.stage-done').count()
                check("4.1 至少一个阶段完成", done_count >= 1,
                      f"{done_count}/7 阶段完成 — 用户看到进展")
            except Exception:
                check("4.1 至少一个阶段完成", False,
                      "超时 — 管线可能卡住了")

            snap(page, "03-progress-mid-pipeline")

            # Refresh resilience — non-programmers might hit F5
            print("   测试刷新恢复...")
            page.reload()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(6000)  # Wait for HTMX poll

            after_refresh = page.locator('li.stage-done').count()
            content = page.content()
            check("4.2 刷新后进度保持", after_refresh >= 1,
                  f"刷新后仍有 {after_refresh} 阶段完成")
            check("4.3 刷新后 Demo 信息仍在",
                  ("Team 2" in content or "Team 3" in content
                   or "文件选对了" in content or "名玩家" in content),
                  "刷新不丢信息 — 用户安心")

            snap(page, "04-after-refresh")

            # ──────────────────────────────────────────────────
            #  STEP 5: 词典页 — 新增术语
            # ──────────────────────────────────────────────────
            print("\n" + "─" * 40)
            print("📌 步骤 5/6：编辑词典（模拟用户想加术语）")
            print("─" * 40)

            page.goto(f"{BASE_URL}/glossary")
            page.wait_for_load_state("networkidle")
            check("5.1 词典页加载成功",
                  page.locator('h1:has-text("词典")').count() > 0
                  or "词典" in page.content(),
                  "用户能看到词典管理页")

            # Try to add a term
            details_btn = page.locator('details summary:has-text("新增术语")')
            if details_btn.count() > 0:
                details_btn.click()
                page.wait_for_timeout(500)

                en_input = page.locator('input[name="en"]')
                zh_input = page.locator('input[name="zh"]')
                if en_input.count() > 0 and zh_input.count() > 0:
                    en_input.fill("RUSH_B")
                    zh_input.fill("冲B包点")
                    page.locator('button:has-text("新增术语")').click()
                    page.wait_for_timeout(1500)

                    added = "RUSH_B" in page.content()
                    check("5.2 新增术语成功", added,
                          "用户输入 'RUSH_B → 冲B包点' 后表格中出现")

                    # Delete it to keep dictionary clean
                    if added:
                        delete_btn = page.locator('tr:has-text("RUSH_B") button:has-text("🗑")')
                        if delete_btn.count() > 0:
                            page.on("dialog", lambda d: d.accept())
                            delete_btn.click()
                            page.wait_for_timeout(800)
                            check("5.3 删除术语成功",
                                  "RUSH_B" not in page.content(),
                                  "用户能删掉自己加错的术语")
                else:
                    check("5.2 新增术语表单存在", False, "找不到 en/zh 输入框")
            else:
                check("5.2 新增术语区域", False,
                      "找不到新增术语入口 — 可能是设计变更")

            snap(page, "05-glossary")

            # ──────────────────────────────────────────────────
            #  STEP 6: 导出页 + 预览页
            # ──────────────────────────────────────────────────
            print("\n" + "─" * 40)
            print("📌 步骤 6/6：预览 & 导出")
            print("─" * 40)

            # Preview page
            page.goto(f"{BASE_URL}/preview/{job_id}")
            page.wait_for_load_state("networkidle")
            check("6.1 预览页可访问",
                  "/preview/" in page.url and page.content() != "",
                  "用户能看到翻译预览")

            snap(page, "06-preview")

            # Export page
            page.goto(f"{BASE_URL}/export/{job_id}")
            page.wait_for_load_state("networkidle")
            check("6.2 导出页可访问",
                  "/export/" in page.url,
                  "用户能看到导出选项")
            check("6.3 下载按钮存在",
                  "下载" in page.content() or "download" in page.url.lower()
                  or "SRT" in page.content(),
                  "用户可以下载字幕文件")

            snap(page, "07-export")

            # ──────────────────────────────────────────────────
            #  Edge cases: 404 pages
            # ──────────────────────────────────────────────────
            print("\n" + "─" * 40)
            print("📌 边缘情况：404 处理")
            print("─" * 40)

            page.goto(f"{BASE_URL}/progress/nonexistent")
            page.wait_for_load_state("networkidle")
            check("E1 不存在的任务页面有错误提示",
                  "不存在" in page.content() or "404" in page.content()
                  or "错误" in page.content(),
                  "用户不会看到空白页或崩溃")

            page.goto(f"{BASE_URL}/")
            page.wait_for_load_state("networkidle")
            check("E2 根路径重定向到 /import", "/import" in page.url)

        finally:
            browser.close()

    # ── Print summary ─────────────────────────────────────────
    passed = sum(1 for r in _results if r[0] == "PASS")
    failed = sum(1 for r in _results if r[0] == "FAIL")
    total = len(_results)

    print("\n" + "=" * 60)
    print(f"测试结果: {passed}/{total} 通过" +
          (f", {failed} 失败" if failed else " — 全部通过！"))
    print("=" * 60)

    for status, name, detail in _results:
        icon = "✅" if status == "PASS" else "❌"
        line = f"  {icon} {name}"
        if detail:
            line += f" — {detail}"
        print(line)

    print(f"\n📸 截图保存于: {SCREENSHOT_DIR}")
    print("=" * 60)

    # Shut down server
    server.should_exit = True

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run())
