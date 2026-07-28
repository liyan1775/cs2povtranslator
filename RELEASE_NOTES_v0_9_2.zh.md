# CS2 POV Translator v0.9.2 Release Notes

## 版本主题

**极简 `.bat` 主菜单 + Comms Overlay 默认主流程收敛。**

v0.9.1 的真实反馈显示：Comms Overlay 功能已经成立，但 `.bat` 入口仍然继承了旧字幕工具时代的长菜单和过时提示，用户一打开会被 10+ 个专家入口干扰。本版本只解决这个入口体验问题，不改 ASR、翻译、overlay 渲染算法。

## 主要变化

- 主菜单从 15 个入口收敛为 6 个核心入口：
  1. 新建 POV 通讯流工程
  2. 渲染 Comms Overlay
  3. 查看工程 / 输出说明
  4. 打包反馈包
  5. 启动前检查
  6. 设置与高级工具
- SRT 导出、重翻译、恢复、词典、玩家别名、模型管理、doctor 等功能移入「设置与高级工具」。
- `.bat` 启动页改为只说明三步核心流程：新建工程 → 校对 YAML → 渲染 overlay → 剪映叠加。
- `Start_CS2_POV_Translator.bat` 和 `Install_CS2_POV_Translator.bat` 显式设置 `PYTHONPATH=%CD%\src;%PYTHONPATH%`，优先加载当前文件夹源码，避免旧虚拟环境/旧 editable install 导致 v0.8.x 菜单残留。
- 更新 README、CHANGELOG、ROADMAP 和 launcher 测试。

## 未改变

- 不改 demo 主 pipeline。
- 不改 faster-whisper / LLM 调用逻辑。
- 不改 overlay 默认视觉参数。
- 不改 SRT stack 策略。
- 不移除专家命令；只是从主菜单隐藏到高级工具里。

## 升级建议

从旧版本升级时，建议重新双击一次 `Install_CS2_POV_Translator.bat`，然后再双击 `Start_CS2_POV_Translator.bat`。若仍看到 v0.8.x 菜单，说明打开的是旧文件夹或旧快捷方式，请确认当前目录里的启动脚本版本为 v0.9.2。
