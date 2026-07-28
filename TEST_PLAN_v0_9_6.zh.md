# CS2 POV Translator v0.9.7 测试计划

## 测试目标

验证 v0.9.7 修复 Anaconda / PATH 场景下 `.bat` 无法一键安装启动的问题，同时保持 v0.9.5 的 ASCII-only `.bat` 编码修复。

本轮重点不是跑完整 demo，而是证明：

```text
普通用户双击 START_HERE_DOUBLE_CLICK.bat 能找到 Python、创建 .venv、进入 v0.9.7 菜单。
```

## A. Clean-room 前置要求

1. 不允许覆盖旧目录。
2. 将 v0.9.7 zip 解压到全新目录，例如：

```text
D:\agent_workspace\cs2pov_release_tests\cs2pov_arch_project_v0_9_7\
```

3. 测试报告必须记录：

```text
实际双击 / 运行的 .bat 绝对路径
当前工作目录
解压目录 tree 前 80 行
Start_CS2_POV_Translator.bat 前 120 行
Install_CS2_POV_Translator.bat 前 180 行
启动 / 安装输出前 120 行
```

## B. .bat 编码验证

在 PowerShell 中运行：

```powershell
$files = @(
  "Start_CS2_POV_Translator.bat",
  "Install_CS2_POV_Translator.bat",
  "START_HERE_DOUBLE_CLICK.bat"
)
foreach ($f in $files) {
  $bytes = [System.IO.File]::ReadAllBytes($f)
  $isAscii = $true
  foreach ($b in $bytes) {
    if ($b -gt 127) { $isAscii = $false; break }
  }
  "$f ASCII=$isAscii FirstBytes=$($bytes[0..2] -join ',')"
}
```

预期：

```text
ASCII=True
FirstBytes 不是 239,187,191
```

## C. Python 自动发现验证

在普通 CMD 或 PowerShell 中运行：

```cmd
Install_CS2_POV_Translator.bat
```

预期：

```text
[1/5] Finding Python 3.11+...
Found Python command: ...
```

可以接受的发现结果包括：

```text
python
py -3
python3
"C:\Users\...\anaconda3\python.exe"
"C:\Users\...\miniconda3\python.exe"
```

如果用户使用 Anaconda 且 `python` 不在系统 PATH 中，本测试必须确认安装器能通过常见 Anaconda 路径找到 Python。

## D. START 一键路径验证

删除或重命名 `.venv` 后，双击：

```text
START_HERE_DOUBLE_CLICK.bat
```

预期：

```text
[INFO] Local virtual environment not found.
[INFO] Starting installer first. This may take a while.
```

随后进入安装器流程。

安装完成后，再次双击 `START_HERE_DOUBLE_CLICK.bat`，预期：

```text
CS2 POV Translator v0.9.7
启动自检通过
进入 6 项核心菜单
```

## E. pytest

运行：

```powershell
python -m pytest
```

预期：

```text
全部通过
```

重点检查：

```text
tests/test_release_entry_v096.py
```

其中必须包含：

```text
.bat ASCII-only 检查
py -3 / Anaconda / Miniconda 自动发现检查
START 自动调用 installer 检查
launch_sanity_check 当前源码检查
```

## F. 最小功能烟测

不需要重新跑完整 demo。可选使用已有 job：

```powershell
cs2pov comms build-review output --rounds 1 --team 2 --export-scope pov_team
cs2pov comms render output --rounds 1 --formats png,preview
```

预期：

```text
review/comms_rounds/round_01.yaml
final/comms_overlay/round_01_overlay_preview.mp4
```

## G. 失败时需要打包的内容

如果仍然失败，请提供：

```text
终端完整报错截图
Start_CS2_POV_Translator.bat 原始文件
Install_CS2_POV_Translator.bat 原始文件
PowerShell ASCII 检查输出
启动 / 安装输出前 120 行
当前目录 tree 前 80 行
where python 输出
where py 输出
dir %USERPROFILE%\anaconda3\python.exe 输出
dir %USERPROFILE%\miniconda3\python.exe 输出
```

如果已经有 output job，再附：

```text
cs2pov feedback output
```

## 通过标准

v0.9.7 只有在以下条件都满足时才能冻结：

```text
1. 中文 Windows 双击 .bat 不再乱码。
2. Anaconda / Miniconda 常见路径能被发现。
3. .venv 不存在时，START 能自动调用安装器。
4. 安装后启动器进入 v0.9.7 菜单。
5. pytest 全通过。
6. 没有旧目录 / 旧 .venv 污染。
```
