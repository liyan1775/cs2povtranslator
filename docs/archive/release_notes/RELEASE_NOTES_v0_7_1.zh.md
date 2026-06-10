# v0.7.1 发布说明：feedback 日志路径脱敏小修版

v0.7.1 是 v0.7.0 的小修版本，不新增核心功能。

## 背景

v0.7.0 反馈包验证中，`manifest.json`、`demo_info.json`、`README_FEEDBACK.txt` 的路径脱敏是正常的，但 `progress.log` 中仍可能出现 Windows 本地绝对路径，例如 `D:\个人项目\...`。

这不属于 API key 级别的严重泄露，但 feedback 包是用于上传给开发者或聊天窗口排查问题的，因此也应该隐藏本地目录结构。

## 修复

- `cs2pov feedback` 现在会对 `.log` / `.txt` 诊断文件做路径脱敏。
- 指向当前 Job 内部的路径会变成相对路径，例如：
  - `final/team_2.bilingual.srt`
  - `artifacts/glossary_used.json`
- 指向本地其他位置的路径会变成：
  - `[已隐藏-本地路径]/match.dem.zst`
- 新增 feedback progress log 脱敏回归测试。

## 没有改动

- 没有改 Whisper / faster-whisper。
- 没有改 DeepSeek / LLM 翻译。
- 没有改字幕 cue 策略。
- 没有改 Mirage 词典内容。
- 没有改 `.bat` 主菜单功能。
