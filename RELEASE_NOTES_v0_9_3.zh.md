# CS2 POV Translator v0.9.3 Release Notes

## 版本主题

**发布入口可信版：修复旧目录 / 旧 `.bat` / 旧 `.venv` 污染导致用户打开过时菜单的问题。**

v0.9.3 不改 Comms Overlay 主链路，也不调整 overlay 画面参数。它只解决 v0.9.2 暴露出的发布体验问题：用户双击 `.bat` 时必须一眼看到当前版本、当前目录和核心流程，不能再被旧 v0.8.x / v0.9.x 菜单误导。

## 新增 / 修改

1. **发布包顶层目录改名**
   - 新 zip 的根目录为 `cs2pov_arch_project_v0_9_3/`。
   - 避免用户把新版本解压进旧 `cs2pov_arch_project/` 后形成 `cs2pov_arch_project/cs2pov_arch_project/`。

2. **新增明显启动入口**
   - 新增 `README_FIRST_先看我.txt`。
   - 新增 `START_HERE_DOUBLE_CLICK.bat`，它会转入 `Start_CS2_POV_Translator.bat`。

3. **启动器显示真实运行目录**
   - `Start_CS2_POV_Translator.bat` 会打印：
     - `CS2 POV Translator v0.9.3`
     - 当前运行目录
     - Comms Overlay 核心流程

4. **启动自检**
   - 新增 `scripts/launch_sanity_check.py`。
   - 启动前检查：
     - `cs2pov.__version__` 必须是 `0.9.3`。
     - Python 必须加载当前目录 `src/` 里的源码。
   - 如果被旧 `.venv` / 旧 editable install 污染，会直接阻止进入菜单。

5. **嵌套目录警告**
   - 如果当前目录下面还存在 `cs2pov_arch_project/Start_CS2_POV_Translator.bat`，启动器和安装器会提示可能解压到了旧项目目录里。

6. **安装器升级**
   - `Install_CS2_POV_Translator.bat` 显示当前安装目录。
   - 安装后运行启动自检。
   - 明确提示不要覆盖旧目录。

7. **测试计划升级**
   - v0.9.3 测试计划要求本地 agent 使用 clean-room 目录。
   - 必须记录实际运行的 `.bat` 绝对路径、目录结构、启动菜单前 60 行。
   - 不能只用 Job 反馈包证明用户入口通过。

## 未改动

- 不改 Comms Overlay 渲染逻辑。
- 不改字幕导出。
- 不改 demo 解析 / ASR / 翻译链路。
- 不改玩家识别和队伍过滤逻辑。

## 建议验收重点

1. 解压后顶层目录应为 `cs2pov_arch_project_v0_9_3`。
2. 双击 `START_HERE_DOUBLE_CLICK.bat` 或 `Start_CS2_POV_Translator.bat` 后，首页必须显示 v0.9.3。
3. 启动输出必须显示当前运行目录。
4. 主菜单必须仍是 6 个核心入口。
5. 如果人为制造旧版本污染，启动自检应能报错或警告。
