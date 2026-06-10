# v0.1.4 反馈修复报告

## 输入反馈

本轮来自 `feedback_v0_1_3.zip`。主链路已经通过，但反馈暴露出三个产品级问题：

1. `tiny + VAD ON` 在真实样本上反而比 VAD OFF 覆盖更多语音；
2. `small` 模型覆盖率很高，但出现整名玩家 compact WAV 被 Whisper 合并成超长 transcript 的 over-merge；
3. 多轮测试后 `artifacts/voice/*.wav` 累积导致项目目录膨胀到数 GB。

## 关键判断

v0.1.3 的问题不是翻译器，也不是 round context，而是 **ASR 输入切片粒度太粗**。

旧流程：

```text
每名玩家一个 compact WAV → Whisper 一次性转录 → 再映射回 demo 时间轴
```

风险：Whisper 会把同一个玩家在几百秒内的离散报点合并成一条长 transcript，导致 SRT cue 跨越几分钟。

v0.1.4 默认改为：

```text
按回合 + 玩家切片 → Whisper 转录短 WAV → 映射回 demo 时间轴
```

这样即使 Whisper 合并，也最多合并在一个回合窗口内，不会跨越半场。

## 已修复/新增

### 1. 新增转录切片模式

新增 `PipelineConfig.transcription_mode`：

```text
round    默认；按回合+玩家切片
activity 按 voice activity 切片，最细但调用次数更多
player   旧版整名玩家 compact WAV，主要用于对照
```

CLI 参数：

```powershell
--transcription-mode round|activity|player
```

### 2. 默认 VAD 改回 ON

基于 v0.1.3 真实反馈，tiny 下 VAD ON 的覆盖率更高，所以 v0.1.4 默认：

```text
whisper_vad_filter = true
```

仍可用：

```powershell
--no-whisper-vad
```

做对照。

### 3. `--max-rounds` 现在也限制转录范围

由于 pipeline 顺序是 `parse_rounds → transcribe`，v0.1.4 会在转录阶段读取 `rounds.json`。

如果传：

```powershell
--max-rounds 3
```

则默认 round/activity 模式只转录前 3 个含语音回合，不再先转完整场再丢弃后续 context。

### 4. 新增临时切片目录

新增：

```text
artifacts/temp_audio/
```

默认转录后自动清理。若要保留调试：

```powershell
--keep-temp-audio
```

### 5. 新增清理命令

预览可释放空间：

```powershell
cs2pov clean output
```

确认删除：

```powershell
cs2pov clean output --yes
```

默认清理：

```text
artifacts/voice/
artifacts/temp_audio/
```

### 6. coverage 增加诊断字段

`artifacts/transcription_coverage.json` 新增：

```text
transcription_mode
whisper_vad_filter
max_rounds_limit
selected_round_numbers
long_transcript_segments_gt_30s
longest_transcript_segment_seconds
```

核心观察指标：

```text
longest_transcript_segment_seconds
```

v0.1.4 的目标是显著降低 v0.1.3 中 588 秒、414 秒这类超长字幕片段。

## 已验证

在沙盒内通过：

```text
15 passed
cs2pov --help OK
cs2pov run --help OK
cs2pov doctor OK（按预期报告缺少可选依赖）
cs2pov clean . OK
```

沙盒没有 demoparser2 / faster-whisper / pyogg，所以真实 demo 仍需用户本机验证。
