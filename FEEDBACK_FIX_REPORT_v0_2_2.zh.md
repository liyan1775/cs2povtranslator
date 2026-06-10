# v0.2.2 反馈修复报告

基于用户上传的 `feedback_v0_2_1.zip`，本轮把本地 agent 报告作为线索，并直接核查了真实产物：`manifest.json`、`progress.log`、`transcription_coverage.json`、`srt_label.srt`、`srt_arrow.srt`。

## 1. 核查结论

v0.2.1 的主要修复成立：

- `Bench` 不再被拆成 `Ben` + `ch.`。
- round 模式保留完整句子，不再按词硬拆。
- 转录和翻译阶段已有持续进度输出。
- 默认双语字幕格式为 `[中文]` label 格式，arrow 格式仍可用。
- `manifest.json` 中 API key 已脱敏。
- DeepSeek 模型已是 `deepseek-v4-flash`。

同时，直接看 SRT 后发现一个体验问题：

- 多条字幕 cue 被顶到精确 `15.0s`，例如 `00:01:12,062 --> 00:01:27,062`。
- 这不属于严重 bug，但对剪辑来说字幕挂屏时间偏长。

## 2. v0.2.2 修复内容

### 2.1 默认长 cue 阈值从 15s 调整为 10s

默认配置改为：

```text
max_subtitle_segment_seconds = 10.0
```

这会让异常长 ASR cue 更早进入后处理，避免字幕长时间挂屏。

### 2.2 round 模式长 cue 锚定加入“可读时长估计”

v0.2.1 的 round 模式逻辑是：

```text
保留完整句子，把 cue 锚定到真实 voice activity，最多显示到 hard cap。
```

v0.2.2 改为：

```text
保留完整句子，但根据文本长度估算一个更适合阅读的显示时长，再与 hard cap 取较小值。
```

这样会避免大量 cue 都正好等于 10s 或 15s。

示意：

```text
短句 Bench.              → 约 2s
中等句 Speak to me...    → 约 3-5s
长句 Smoke window...     → 最多 10s
```

### 2.3 测试覆盖

新增测试：

- round 模式不拆完整句子；
- round 模式异常长 cue 不再简单顶到 hard cap；
- 默认产品配置使用 `10.0s` 长 cue 阈值。

## 3. 已验证

沙盒内完成：

```text
32 passed
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov doctor
```

`doctor` 在沙盒里由于缺少真实依赖会返回非零状态，这是预期行为；输出内容正常，且能看到默认长 cue 阈值为 `10.0s`。

## 4. 未改变的内容

v0.2.2 没有改变：

- PipelineEngine 架构；
- round 模式默认路线；
- label / arrow 双字幕格式；
- feedback 命令；
- 密钥脱敏策略；
- DeepSeek 默认模型。

这是一个小范围剪辑体验修复版。
