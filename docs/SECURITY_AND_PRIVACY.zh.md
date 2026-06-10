# 隐私与安全说明

本项目是本地优先工具。默认不会上传 demo、WAV 或字幕。

## 可能离开本机的数据

只有启用真实 LLM 翻译时，待翻译文本会发送到你配置的 OpenAI-compatible API endpoint。demo 文件和音频不会发送给 LLM。

## API key

- `cs2pov config show` 默认隐藏 API key。
- `manifest.json` 不保存明文 API key。
- `feedback` 包会脱敏 key。
- 只有 `cs2pov config show --show-secrets` 会显示真实 key。

## feedback 包脱敏

`cs2pov feedback` 会排除：

- 原始 demo 文件
- 大型 WAV / temp audio
- API key
- 本地绝对路径

仍会保留用于排查的文本产物：

- progress.log
- errors.log
- manifest.json
- demo_info.json
- transcript / translation / coverage / glossary 报告
- final/review/debug SRT

## 不要公开上传的内容

即使经过脱敏，也建议在公开 issue 前人工检查：

- 玩家 ID 是否介意公开。
- 字幕文本是否包含隐私内容。
- LLM 翻译文本是否包含不适合公开的语音内容。

## 设计原则

反馈包是为了发给开发者排查问题，不是为了公开发布。开源仓库中不要提交真实 demo、真实语音、私有字幕工程或 API key。
