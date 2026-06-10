# v0.3.0 发布说明：字幕工程工具化

v0.3.0 基于 v0.2.2 稳定基线开发。本版不继续微调 ASR 参数，而是把项目从“跑一次生成字幕”升级为“可查看、可导出、可重翻、可恢复的字幕工程工具”。

## 新增功能

### 1. 菜单式 `.bat` 启动器

`Start_CS2_POV_Translator.bat` 不再只启动向导，而是打开一个带说明的主菜单：

1. 新建字幕工程
2. 查看已有工程状态
3. 重新导出字幕
4. 重新翻译
5. 从某阶段恢复
6. 打包反馈包
7. 环境诊断
8. 查看帮助

每个菜单项都会说明适合什么场景，以及执行后应该看哪些输出。

### 2. `cs2pov inspect-job`

用于检查已有 Job：

```powershell
cs2pov inspect-job output
cs2pov inspect-job "output\20260610_120000_de_mirage"
cs2pov inspect-job output --json
```

输出内容包括：阶段状态、地图、队伍、Whisper/LLM 配置、转录/翻译条数、SRT 文件、转录覆盖参考、推荐下一步命令。

### 3. `cs2pov export`

基于已有产物重新导出 SRT，不重新转录、不重新调用 LLM：

```powershell
cs2pov export output --format all
cs2pov export output --format zh
cs2pov export output --format bilingual --bilingual-format arrow
```

支持格式：`all / bilingual / zh / original / voice`。

### 4. `cs2pov retranslate`

基于已有 `round_contexts.jsonl` 重新翻译，不重新跑 Whisper：

```powershell
cs2pov retranslate output
cs2pov retranslate output --dry-run
cs2pov retranslate output --model deepseek-v4-flash
```

适合 LLM 临时失败、换模型、或把 dry-run 结果换成真实翻译。

### 5. `cs2pov resume`

从已有 Job 的某个阶段恢复执行：

```powershell
cs2pov resume output --from-stage translate
cs2pov resume output --from-stage export_subtitles
cs2pov resume output --from-stage transcribe --demo "D:\demos\match.dem.zst"
```

适合程序中途失败后继续，不必每次从头跑完整 demo。

## 兼容性说明

- v0.3.0 保留 v0.2.2 的默认转录策略：round 模式、VAD ON、10 秒字幕重贴阈值。
- `feedback` 仍然排除 `artifacts/voice/`、`artifacts/temp_audio/` 和原始 demo。
- `manifest.json` 仍然会脱敏 API key。

## 建议测试重点

本版重点不是重新比较 ASR tiny/base/small，而是验证工程命令是否可用：

1. `.bat` 菜单是否有足够提示。
2. `inspect-job` 是否能看懂 Job 状态。
3. `export` 是否能在不转录的情况下生成不同格式。
4. `retranslate --dry-run` 是否能快速重翻并重新导出。
5. `resume --from-stage export_subtitles` 是否能只重跑导出阶段。
6. `feedback` 是否仍然不包含大音频、原始 demo、明文 key。
