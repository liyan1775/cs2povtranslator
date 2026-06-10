# v0.1.6 反馈修复报告

## 反馈来源

本轮基于 `feedback_v0_1_5.zip` 核查。注意：反馈包中的 `README.md` 由本地 agent 生成，我没有直接采信报告结论，而是逐项核查了：

- `coverage_v015_default.json`
- `coverage_no_postprocess.json`
- `coverage_small_round.json`
- `coverage_asr_en.json`
- `srt_*.srt`
- `transcript_v015_default.jsonl`
- `manifest_v015_default.json`
- `progress_v015_default.log`

## 核查结论

v0.1.5 的字幕质量判断基本成立：

- 默认模式 `tiny + VAD ON + round + 后处理 ON` 成功把最长 cue 控制到约 13.2s。
- 关闭后处理时最长 cue 约 91.26s，且有 5 条 >30s cue。
- 默认模式过滤了 1 条纯标点/噪声幻觉。
- `small + round` 的 coverage 指标更高，但 SRT cue 数和 coverage 片段数不能直接混为一谈。

但我发现本地 agent 报告没有提到的严重问题：

> `manifest.json` 里明文写入了 `llm_api_key`。

Job manifest 很容易被打包进反馈包，所以它必须视为可分享调试产物，不能包含 API key。

## v0.1.6 修复内容

### 1. Manifest 不再写入明文 API key

`PipelineManifest.save()` 现在写出的是安全版 manifest：

```json
{
  "llm_api_key": "[已配置-已隐藏]",
  "llm_api_key_configured": true
}
```

内存中的 `PipelineConfig` 仍然保留真实 key，运行时翻译不受影响。

### 2. `cs2pov config show` 默认隐藏 API key

旧行为会直接打印本地配置中的 key。新行为默认隐藏：

```powershell
cs2pov config show
```

确实需要查看明文时，必须显式使用：

```powershell
cs2pov config show --show-secrets
```

### 3. 向导输入 API key 时不再把默认值显示在屏幕上

`cs2pov-wizard` 现在用隐藏输入方式读取 API key。已有 key 时会提示“已配置，直接回车沿用”，但不会显示 key 内容。

### 4. Coverage 报告新增 before/after 字段

v0.1.5 的报告里提到“后处理后 coverage 下降不是质量下降”。这个判断基本合理，但工具本身应该把口径写清楚。

v0.1.6 的 `transcription_coverage.json` 新增：

- `raw_transcript_segments_before_postprocess`
- `postprocessed_transcript_segments`
- `coverage_ratio_before_postprocess`
- `coverage_ratio_after_postprocess`
- `matched_voice_cues_before_postprocess`
- `unmatched_voice_cues_before_postprocess`
- `coverage_note_after_postprocess`

这样以后不用靠人工解释，报告里能直接看出后处理前后口径差异。

## 已验证

在沙盒中完成纯代码验证：

```text
20 passed
python -m compileall -q src scripts
cs2pov config show 默认隐藏 API key
cs2pov doctor 只显示 API key 是否已配置
```

真实 demo + Whisper 仍需要在本机继续验收。

## 安全提醒

本次反馈包里的 `manifest_v015_default.json` 已经包含过一个 DeepSeek API key。建议你到 DeepSeek 控制台立刻吊销/轮换该 key，之后改用新 key。
