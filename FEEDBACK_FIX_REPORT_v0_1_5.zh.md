# CS2 POV Translator v0.1.5 反馈修复报告

## 反馈来源

基于用户提交的 `feedback_v0_1_4.zip`。该反馈包包含：

- `coverage_round.json`
- `coverage_activity.json`
- `coverage_small_round.json`
- `coverage_player.json`
- `transcript_*.jsonl`
- `srt_*.srt`
- `progress_round.log`
- 用户手写验收总结

## v0.1.4 验收结论

v0.1.4 主链路已稳定通过真实 demo 验收：

- 安装与单元测试通过。
- `.dem.zst` 解压正常。
- 地图识别为 `de_mirage`。
- 语音提取正常。
- 回合清洗从 33 raw rounds 得到 30 cleaned rounds。
- `round` 模式转录前 3 个回合仅约 30 秒。
- `tiny + VAD ON + round` 达到 100% heuristic coverage。
- `clean` 命令可正常预览和删除大体积中间产物。

用户结论是：v0.1.4 是目前测试以来最满意版本，默认推荐 `tiny + VAD ON + round`。

## 发现的问题

### 1. Whisper 纯标点幻觉

反馈中 `jigokuraku` 在背景噪声段出现：

```text
,,,,,,,,,,,,,,,,,,,,
```

这是 Whisper 在低质量短语音/背景噪声下的常见行为。它不是 pipeline 错误，但会污染字幕成品。

### 2. 多语言 demo 的 ASR 语言选择

demo 中存在瑞典语、拉脱维亚语、罗马尼亚语、韩语等内容。默认 `auto` 合理，但用户希望在需要时可以强制英文识别。

### 3. round 模式仍可能出现几十秒 cue

v0.1.4 已把旧版 588s / 414s 级别超长 cue 压到约 91s，但 91s 对视频字幕仍然偏长。原因是 round 模式会给 Whisper 更完整上下文，少数模型仍可能把该玩家整个回合窗口合并为一个 ASR segment。

## v0.1.5 修复内容

### 1. 默认启用纯标点 hallucination 过滤

新增保守过滤函数：

```python
is_probable_whisper_hallucination(text)
```

默认只过滤安全可删的内容：

- 空文本
- 纯标点
- 重复逗号/句号等噪声

不会过滤：

- `go`
- `A`
- `one`
- `short`
- 中文/英文/俄文/带变音字母文本

新增 CLI：

```powershell
--filter-hallucinations
--no-filter-hallucinations
```

### 2. 默认启用长 cue 重贴到 voice activity 簇

新增后处理：

```python
rebase_long_segments_to_voice_activity(...)
```

当 ASR segment 超过默认 15 秒时，系统会：

1. 找到同一玩家在同一时间范围内的 voice activity。
2. 按间隔阈值聚合为 voice clusters。
3. 保留 round 模式得到的上下文文本。
4. 把文本分配回实际语音活动簇，避免字幕长时间挂在屏幕上。

新增 CLI：

```powershell
--max-subtitle-segment-seconds 15
--voice-cluster-gap 1.0
```

如需关闭该功能：

```powershell
--max-subtitle-segment-seconds 0
```

### 3. 增加 ASR 语言别名

原本已有：

```powershell
--language auto
```

v0.1.5 增加更直观别名：

```powershell
--asr-language en
```

### 4. 向导中增加 ASR 语言提示

`cs2pov-wizard` 不再硬编码 `auto`，会提示用户：

- 默认 `auto` 适合英语/俄语混合。
- 明确只想按英文识别时可输入 `en`。

### 5. coverage 诊断增强

`artifacts/transcription_coverage.json` 新增字段：

```json
{
  "filter_hallucinations": true,
  "filtered_hallucination_segments": 1,
  "max_subtitle_segment_seconds": 15.0,
  "voice_cluster_gap_seconds": 1.0,
  "long_segments_rebased_to_voice_activity": 2,
  "segments_created_by_long_cue_rebase": 5
}
```

这些字段用于判断后处理是否真正生效。

## 已验证

沙盒内完成纯代码验证：

```text
17 passed
python -m py_compile src scripts
cs2pov run --help
cs2pov doctor
```

沙盒仍然没有用户 Windows + demoparser2 + faster-whisper 环境，因此真实 demo 验收需要用户本机继续跑。
