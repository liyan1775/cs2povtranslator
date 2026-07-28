# CS2 POV Translator v0.9.3 测试计划

## 版本目标

验证 v0.9.3 的**发布入口可信性**：用户双击 `.bat` 时，必须进入当前 v0.9.3 的极简 Comms Overlay 菜单，而不是旧目录、旧 `.bat`、旧 `.venv` 或旧 editable install。

本版本不要求重新跑完整 demo，不要求重新测 overlay 观感。若要做 smoke test，只需使用已有 Job 验证菜单能进入即可。

---

## A. 测试前清洁要求（必须）

### A1. 不允许覆盖旧目录

不要把 `cs2pov_arch_project_v0_9_3.zip` 解压到旧的 `cs2pov_arch_project/` 目录里面。

推荐目录：

```powershell
D:\agent_workspace\cs2pov_release_tests\cs2pov_arch_project_v0_9_3\
```

### A2. 旧目录只能重命名或归档

可以这样处理旧目录：

```powershell
Rename-Item cs2pov_arch_project cs2pov_arch_project_OLD_v0_9_2
```

禁止误删：

```text
不要删除 demo 文件
不要删除 lim POV 视频
不要删除历史 output/job
不要删除 feedback 包
不要删除用户手动修改过的 round_XX.yaml
```

### A3. 记录 clean-room 证据

本地 agent 必须在反馈报告中包含：

```powershell
Get-Location
Get-ChildItem -Force | Select-Object Name,Mode,Length
cmd /c tree /f /a | Select-Object -First 120
```

如果看到：

```text
cs2pov_arch_project\
  cs2pov_arch_project\
    Start_CS2_POV_Translator.bat
```

立即停止测试，判定为测试环境污染。

---

## B. 发布包结构测试

### B1. zip 顶层目录

预期：zip 解压后顶层目录为：

```text
cs2pov_arch_project_v0_9_3/
```

不应只有通用名：

```text
cs2pov_arch_project/
```

### B2. 明显入口文件

预期存在：

```text
README_FIRST_先看我.txt
START_HERE_DOUBLE_CLICK.bat
Start_CS2_POV_Translator.bat
Install_CS2_POV_Translator.bat
scripts/launch_sanity_check.py
```

---

## C. 用户入口测试（核心）

### C1. 记录实际运行的 .bat 路径

本地 agent 必须输出：

```powershell
Resolve-Path .\Start_CS2_POV_Translator.bat
Get-Content .\Start_CS2_POV_Translator.bat -TotalCount 80
```

如果测试 `START_HERE_DOUBLE_CLICK.bat`，也要输出：

```powershell
Resolve-Path .\START_HERE_DOUBLE_CLICK.bat
Get-Content .\START_HERE_DOUBLE_CLICK.bat -TotalCount 40
```

### C2. 捕获启动菜单前 60 行

运行：

```powershell
.\Start_CS2_POV_Translator.bat
```

或等价非交互方式运行 launcher 后，必须保存启动输出前 60 行。

预期必须包含：

```text
CS2 POV Translator v0.9.3
主功能：CS2 POV 通讯流 Overlay
当前运行目录：
[启动自检] cs2pov 版本: 0.9.3
[启动自检] 通过
核心菜单
1. 新建 POV 通讯流工程
2. 渲染 Comms Overlay
6. 设置与高级工具
```

预期不得包含：

```text
v0.8.3 Release-ready local-first bilingual subtitle toolkit
v0.8.8 玩家识别与别名映射
新建字幕工程
13. 查看安装/首次使用教程
14. 查看命令帮助和常见场景
```

---

## D. 启动自检测试

### D1. 正常自检

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\launch_sanity_check.py
```

预期：

```text
[启动自检] cs2pov 版本: 0.9.3
[启动自检] Python 加载源码: ...\src\cs2pov\__init__.py
[启动自检] 通过
```

### D2. 旧源码污染模拟（可选）

若本地 agent 能安全模拟旧 `PYTHONPATH`，应验证自检会阻止版本不一致。不能模拟也可以跳过，但要说明原因。

---

## E. 菜单 smoke test

使用 Python 入口测试主菜单：

```powershell
$env:PYTHONPATH = "$PWD\src;$env:PYTHONPATH"
.\.venv\Scripts\python.exe -X utf8 -m cs2pov.cli.launcher --once
```

输入 `0` 退出。

预期：

```text
核心菜单
1. 新建 POV 通讯流工程
2. 渲染 Comms Overlay
3. 查看工程 / 输出说明
4. 打包反馈包
5. 启动前检查
6. 设置与高级工具
0. 退出
```

---

## F. 最小功能回归

不强制跑完整 demo。若已有 Job，可做最小回归：

```powershell
cs2pov inspect-job output
cs2pov explain-output output
cs2pov comms build-review output --rounds 1 --team 2 --export-scope pov_team
cs2pov comms render output --rounds 1 --formats png
```

预期：

```text
review/comms_rounds/round_01.yaml 存在
final/comms_overlay/round_01_overlay_frame.png 存在
```

---

## G. 反馈包要求

本地 agent 反馈包必须包含：

```text
1. v0.9.3 解压后的目录 tree 前 120 行
2. 实际运行的 .bat 绝对路径
3. Start_CS2_POV_Translator.bat 前 80 行
4. START_HERE_DOUBLE_CLICK.bat 前 40 行
5. 启动输出前 60 行
6. scripts/launch_sanity_check.py 输出
7. 若仍看到旧菜单，必须附旧菜单截图/文本和实际运行目录
8. 若跑了最小功能回归，再附 cs2pov_feedback_*.zip
```

注意：Job 反馈包只能证明工程产物，不足以证明用户入口通过。
