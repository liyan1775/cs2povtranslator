# CS2 POV Translator v0.1.5 测试计划

## 测试目标

v0.1.5 不改变 v0.1.4 的默认主路线：

```text
tiny + VAD ON + round
```

本轮重点验证新增后处理是否提升字幕成品质量：

1. 纯标点 Whisper 幻觉是否被过滤。
2. 91s 级别长 cue 是否被重贴到 voice activity 簇。
3. `--asr-language en` 是否可用于强制英文 ASR 对照。
4. 新增 coverage 字段是否正确生成。
5. 默认 round 模式的整体链路是否没有被破坏。

---

## 0. 安装与基础检查

```powershell
cd D:\个人项目\cs2pov_arch_project
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
pytest -q
cs2pov doctor
```

预期：

```text
17 passed
Whisper VAD: ON
转录切片模式: round
幻觉过滤: ON
最长字幕重贴阈值: 15.0s
```

---

## 1. 默认 round 模式烟测

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v015_round_tiny `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

重点检查：

```text
artifacts\transcription_coverage.json
artifacts\transcript_segments.jsonl
final\team_2.bilingual.srt
progress.log
```

预期：

```text
transcription_mode = round
whisper_vad_filter = true
filter_hallucinations = true
max_subtitle_segment_seconds = 15.0
filtered_hallucination_segments >= 0
long_segments_rebased_to_voice_activity >= 0
longest_transcript_segment_seconds 应显著低于 v0.1.4 的 91s
SRT 中不应再出现纯逗号字幕
```

---

## 2. 对照：关闭后处理

用于确认 v0.1.5 新功能是否真的起作用。

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v015_no_postprocess `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3 `
  --no-filter-hallucinations `
  --max-subtitle-segment-seconds 0
```

对比：

```text
output_v015_round_tiny\...\final\team_2.bilingual.srt
output_v015_no_postprocess\...\final\team_2.bilingual.srt
```

预期：

```text
关闭后处理的版本更接近 v0.1.4，可能保留纯标点和长 cue。
默认版本应更适合直接导入剪辑软件。
```

---

## 3. 强制英文 ASR 对照

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v015_asr_en `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3 `
  --asr-language en
```

对比：

```text
output_v015_round_tiny\...\review\team_2.original.srt
output_v015_asr_en\...\review\team_2.original.srt
```

重点观察：

```text
auto 是否更适合多语言
还是 en 是否更适合做英文到中文翻译素材
```

---

## 4. small + round 对照

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v015_small_round `
  --whisper-model small `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

预期：

```text
small 的文字可能更准，但仍可能更爱合并。
v0.1.5 后处理应降低 small 的长 cue 风险。
```

---

## 5. 需要反馈给开发者的文件

如果本轮仍有问题，请打包这些文件：

```text
manifest.json
progress.log
errors.log
artifacts\transcription_coverage.json
artifacts\transcript_segments.jsonl
artifacts\round_contexts.jsonl
final\team_2.bilingual.srt
review\team_2.original.srt
```

如果长 cue 仍存在，请额外说明：

```text
最长 cue 的开始/结束时间
对应字幕文本
你认为实际应该拆成几段
```
