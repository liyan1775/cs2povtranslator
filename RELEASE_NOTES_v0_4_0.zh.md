# CS2 POV Translator v0.4.0 发布说明

## 版本主题

v0.4.0：发布准备 / 普通用户可用性版。

v0.3.x 已经证明字幕工程命令可用。本版不继续微调 ASR 参数，而是补齐普通用户首次使用所需的安装、检查、输出解释和验收流程。

## 新增功能

### 1. `cs2pov setup-check`

普通用户版启动前检查。它会用检查表说明：

- Python / venv / 启动器是否存在；
- demoparser2 / zstandard / pyogg / faster-whisper 是否可用；
- Whisper 默认配置；
- LLM 是否配置；
- 当前能否 dry-run；
- 当前能否真实翻译。

### 2. `cs2pov explain-output`

解释已有 Job 的输出文件：

- `final/`：给剪辑软件导入；
- `review/`：校对；
- `debug/`：开发者排查；
- `artifacts/`：resume/retranslate/export 依赖的中间产物。

### 3. `Install_CS2_POV_Translator.bat`

一键安装脚本：

1. 检查 Python；
2. 创建 `.venv`；
3. 安装 `pip install -e ".[all]"`；
4. 运行 `cs2pov setup-check`。

### 4. `.bat` 主菜单升级

`Start_CS2_POV_Translator.bat` 启动后显示 v0.4.0 菜单，并增加：

- setup-check；
- explain-output；
- 安装 / 首次使用教程。

### 5. `scripts/acceptance_smoke.ps1`

真实 demo 验收脚本，用于验证普通用户路径：

```text
setup-check -> run dry-run -> inspect-job -> export -> feedback
```

## 未做事项

- 没有提前做词典系统；词典属于翻译质量增强，不是当前发布准备阻塞项。
- 没有做 UI；当前仍保持本地 CLI 产品形态。
- 没有继续改 ASR 默认参数；v0.2.2 已作为稳定字幕策略基线。

## 兼容性

v0.4.0 基于 v0.3.1。已有 v0.3.x Job 可以继续用 `inspect-job / explain-output / export / retranslate / resume / feedback` 处理。
