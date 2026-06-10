# CS2 POV Translator v0.4.1 发布说明

这是 v0.4.0 的 Windows 路径兼容修复版。

## 修复

- 修复 `cs2pov explain-output` 在 Windows 上无法识别 `final\...` / `review\...` / `debug\...` 字幕路径的问题。
- `inspect-job` 返回的字幕相对路径现在统一使用 POSIX 风格 `/`，方便后续命令、测试和反馈包跨平台解析。
- `output_explainer` 增加防御性路径标准化，即使遇到旧 Job 或旧工具生成的反斜杠路径，也能正常分类显示。

## 没有改动

- 没有修改 demo 解析、Whisper、LLM、字幕时间轴策略。
- 不需要重新大规模测试 ASR/翻译质量。
