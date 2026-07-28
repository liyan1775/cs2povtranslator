# CS2 POV Translator v0.9.4 测试计划

## 版本目标

验证 v0.9.4 修复了 v0.9.3 在 Windows/GBK 环境下的 release-entry pytest 编码失败，同时保持 v0.9.3 的发布入口可信能力。

本版本不要求重新跑完整 demo，不要求重新测 overlay 观感。重点是：**clean-room 入口 + 全量 pytest 必须通过**。

## A. Clean-room 目录要求

不要覆盖旧目录。推荐解压到：

```powershell
D:\agent_workspace\cs2pov_release_tests\cs2pov_arch_project_v0_9_4\
```

反馈报告必须包含：

```powershell
Get-Location
Resolve-Path .\Start_CS2_POV_Translator.bat
Get-Content .\Start_CS2_POV_Translator.bat -TotalCount 80
cmd /c tree /f /a | Select-Object -First 120
```

## B. 启动入口验证

运行：

```powershell
.\Start_CS2_POV_Translator.bat
```

启动输出前 60 行必须包含：

```text
CS2 POV Translator v0.9.4
主功能：CS2 POV 通讯流 Overlay
当前运行目录：
[启动自检] cs2pov 版本: 0.9.4
[启动自检] 通过
核心菜单
1. 新建 POV 通讯流工程
2. 渲染 Comms Overlay
6. 设置与高级工具
```

不得包含：

```text
v0.8.3 Release-ready
v0.8.8 玩家识别与别名映射
新建字幕工程
13. 查看安装/首次使用教程
14. 查看命令帮助和常见场景
```

## C. Windows pytest 验证（本版本核心）

运行：

```powershell
$env:PYTHONPATH = "$PWD\src;$env:PYTHONPATH"
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\python.exe -X utf8 -m pytest -q
```

预期：全部通过。

特别关注：

```text
tests/test_release_entry_v094.py::test_launch_sanity_check_uses_current_src
```

不得再出现 GBK / UnicodeDecodeError / 中文输出解码失败。

## D. 启动自检直接运行

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\launch_sanity_check.py
```

预期：

```text
[启动自检] cs2pov 版本: 0.9.4
[启动自检] Python 加载源码: ...\src\cs2pov\__init__.py
[启动自检] 通过
```

## E. 最小功能回归（可选）

如果已有 Job，可运行：

```powershell
cs2pov inspect-job output
cs2pov comms build-review output --rounds 1 --team 2 --export-scope pov_team
cs2pov comms render output --rounds 1 --formats png
```

预期：

```text
review/comms_rounds/round_01.yaml 存在
final/comms_overlay/round_01_overlay_frame.png 存在
```

## F. 反馈包要求

本地 agent 反馈包必须包含：

1. v0.9.4 解压后的目录 tree 前 120 行。
2. 实际运行的 `.bat` 绝对路径。
3. 启动输出前 60 行。
4. `launch_sanity_check.py` 输出。
5. pytest 完整摘要，必须能看到 release-entry 测试已通过。
6. 若仍失败，附完整 traceback。
