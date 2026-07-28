# CS2 POV Translator v0.9.7 Release Notes

## 版本定位

v0.9.7 是 Windows 双击启动入口的补丁版。

它不改 Comms Overlay 主链路、不改 demo / ASR / 翻译 / 渲染逻辑。它只修复 v0.9.5 暴露出的一个真实用户问题：

```text
用户装了 Anaconda，但 Anaconda 的 python.exe 不在系统 PATH 中。
双击 .bat 时找不到 python，导致安装器无法继续。
```

## 修复的问题

v0.9.5 已经把 `.bat` 改成 ASCII-only，解决了中文 Windows CMD 把 UTF-8 中文解析成乱码命令的问题。

但 v0.9.5 的安装器仍然假设：

```text
python --version
```

可以在普通 CMD 中找到 Python。

这对“Python 官网安装 + 勾选 Add to PATH”的用户成立，但对很多 Anaconda 用户不成立。Anaconda 的 Python 往往只在 Anaconda Prompt 中可用，不一定加入系统 PATH。

## 本版改动

1. `Install_CS2_POV_Translator.bat` 增加 Python 自动发现逻辑。

   会依次尝试：

   ```text
   python
   py -3
   python3
   %USERPROFILE%\anaconda3\python.exe
   %USERPROFILE%\miniconda3\python.exe
   %LOCALAPPDATA%\anaconda3\python.exe
   %LOCALAPPDATA%\miniconda3\python.exe
   %ProgramData%\Anaconda3\python.exe
   %ProgramData%\Miniconda3\python.exe
   常见 Python311 / Python312 / Python313 安装路径
   ```

2. 如果找到了 Python 3.11+，就用它创建 `.venv`。

3. `Start_CS2_POV_Translator.bat` 在 `.venv` 不存在时，会自动调用安装器，而不是只报错。

4. `.bat` 仍然保持 ASCII-only，不重新引入中文 echo / 中文注释。

5. 增加 release-entry 测试：

   - `.bat` 必须 ASCII-only。
   - 安装器必须包含 `py -3` / Anaconda / Miniconda 自动发现。
   - 启动器必须在 `.venv` 缺失时调用安装器。
   - 启动自检仍必须加载当前目录源码。

## 不变内容

- 不改 Comms Overlay 样式。
- 不改每回合 YAML 中间产物。
- 不改 team filter / export_scope。
- 不改 SRT 导出。
- 不改 feedback 包结构。

## 用户预期体验

首次使用可以直接：

```text
1. 解压到全新目录 cs2pov_arch_project_v0_9_7
2. 双击 START_HERE_DOUBLE_CLICK.bat
3. 如果 .venv 不存在，它会自动进入安装流程
4. 安装成功后进入中文菜单
```

也可以手动：

```text
1. 双击 Install_CS2_POV_Translator.bat
2. 双击 START_HERE_DOUBLE_CLICK.bat
```

## 验收标准

v0.9.7 只有在以下条件都满足时才能冻结：

```text
1. 中文 Windows 双击 .bat 不乱码。
2. Anaconda 用户即使 python 不在 PATH，也能被常见路径发现。
3. 如果 .venv 不存在，START_HERE_DOUBLE_CLICK.bat 能自动触发安装器。
4. 启动器进入 v0.9.7 中文菜单。
5. pytest 全通过。
```
