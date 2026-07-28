# CS2 POV Translator v0.9.4 Release Notes

## 版本主题

**Windows 发布入口测试修复版：修复 v0.9.3 在 Windows/GBK 环境下的 release-entry pytest 编码失败。**

v0.9.4 不改 Comms Overlay 主链路、不改渲染参数、不改 demo/ASR/翻译流程。它只修复 v0.9.3 反馈包暴露出的一个测试可靠性问题：`test_launch_sanity_check_uses_current_src` 在 Windows 上通过 `subprocess.run(..., text=True)` 捕获中文启动自检输出时，可能被父进程按 GBK 解码，从而出现测试失败。

## 修复内容

1. `tests/test_release_entry_v094.py` 显式使用：
   - `sys.executable -X utf8`
   - `encoding="utf-8"`
   - `errors="replace"`

2. 版本号统一更新为 `0.9.4`：
   - `pyproject.toml`
   - `src/cs2pov/__init__.py`
   - `.bat` 标题与启动提示
   - `scripts/launch_sanity_check.py`
   - launcher / wizard / README / 测试断言

3. 继续保留 v0.9.3 的发布入口可信设计：
   - 版本化顶层目录
   - `README_FIRST_先看我.txt`
   - `START_HERE_DOUBLE_CLICK.bat`
   - 启动自检
   - clean-room 测试要求

## 未改动

- 不改 Comms Overlay 渲染逻辑。
- 不改字幕导出。
- 不改 demo 解析 / ASR / 翻译链路。
- 不改玩家识别和队伍过滤逻辑。

## 验收重点

1. Windows 下全量 pytest 应为全通过，而不是 `114 passed, 1 failed`。
2. 双击入口仍应显示：
   - `CS2 POV Translator v0.9.4`
   - 当前运行目录
   - 启动自检通过
   - 6 项核心菜单
3. 若测试失败，不应再是 GBK/UTF-8 解码问题。
