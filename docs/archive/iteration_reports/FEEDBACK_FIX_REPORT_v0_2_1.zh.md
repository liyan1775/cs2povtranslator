# v0.2.1 反馈修复报告

基于 `feedback_v0_2_0.zip` 的真实产物核查，而不是只采信本地 agent 报告。

## 核查结论

v0.2.0 主流程通过：

- 双击 `.bat` 进入向导：通过
- 8 步向导：通过
- small + auto + round + 5 回合 + deepseek-v4-flash：通过
- `cs2pov feedback`：通过，未打包 WAV
- `manifest.json`：未发现 `sk-` 明文 key
- 默认 smoke：无 30s+ cue

但真实 SRT 和 JSONL 暴露出 4 个需要修的问题：

1. round 模式下长 cue 重贴把完整句子切碎，例如 `Bench` 被拆成 `Ben` + `ch.`。
2. 某些回合 LLM 临时失败时，fallback 文案仍写“未配置”，会误导用户。
3. 转录/翻译长阶段只有开始和结束日志，终端看起来像卡住。
4. 双语 SRT 使用 `→`，用户反馈在剪辑软件里观感一般。

## v0.2.1 修复内容

### 1. round 模式长 cue 不再按词硬拆

v0.2.0 的后处理会把一个语义完整的长 ASR cue 按 voice activity 簇拆成多个文本碎片。v0.2.1 改为：

- `round` 模式：保留完整句子，只把显示时间锚定到真实 voice activity 附近，并按阈值裁短。
- `activity/player` 模式：保留旧的按簇拆分能力，用于 debug/对照。

coverage 新增字段：

```json
"long_segments_clamped_without_text_split": 1
```

### 2. 翻译失败文案更准确

旧文案：

```text
[未翻译：未配置或调用 LLM 失败]
```

新文案按原因区分：

```text
[未翻译：未配置 LLM]
[未翻译：已跳过翻译]
[未翻译：LLM 调用失败，请稍后重试该回合]
```

同时 `_translate_one_round()` 对 LLM 调用失败会重试 1 次。

### 3. 转录/翻译阶段增加细粒度进度

新增终端/progress.log 输出，例如：

```text
转录中... Round 1，玩家 Magnojezzz（窗口 3/25）
翻译中... Round 2（2/5）
```

### 4. 双语字幕默认格式改为 `[中文]`

旧格式：

```text
[玩家] original
→ translation
```

新默认格式：

```text
[玩家] original
[中文] translation
```

如果需要旧格式，可用：

```powershell
cs2pov run ... --bilingual-format arrow
```

或保存默认配置：

```powershell
cs2pov config set --bilingual-format arrow
```

### 5. 修复 coverage 统计中的重复 unmatched 计数

v0.2.0 中 `build_transcription_coverage()` 对未匹配 voice cue 有重复 append，v0.2.1 已修复。

## 验证

本地沙盒已完成：

```text
31 passed
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov doctor
```

真实 demo 仍需用户本机验证，因为沙盒没有 Windows + demoparser2 + faster-whisper + 本地 Whisper 模型环境。
