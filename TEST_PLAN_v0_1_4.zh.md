# v0.1.4 测试计划

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
15 passed
Whisper VAD: ON
转录切片模式: round
```

如果你之前保存过配置，`doctor` 可能仍显示旧配置。可以重置：

```powershell
cs2pov config set --whisper-vad --transcription-mode round
```

## 1. 测默认 round 模式

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v014_round_tiny `
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
selected_round_numbers 只有 3 个回合
longest_transcript_segment_seconds 显著小于 v0.1.3 的 588 秒/414 秒
SRT 不再出现 10 分钟长 cue
```

## 2. 对照 legacy player 模式

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v014_player_tiny `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3 `
  --transcription-mode player
```

目的：确认旧模式仍可用，并和 round 模式对比。预期 player 模式可能仍有更长的 transcript cue。

## 3. 对照 activity 模式

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v014_activity_tiny `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3 `
  --transcription-mode activity
```

目的：看 activity 是否比 round 更细、更适合最终字幕。它调用次数更多，可能更慢。

## 4. 测 small + round

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v014_round_small `
  --whisper-model small `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

重点观察：small 在 round 模式下是否还出现 over-merge。

## 5. 测 VAD OFF 对照

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v014_round_tiny_no_vad `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3 `
  --no-whisper-vad
```

目的：确认 v0.1.4 默认 VAD ON 是否仍然比 OFF 好。

## 6. 测清理命令

先预览：

```powershell
cs2pov clean output_v014_round_tiny
```

预期：显示 `artifacts\voice` 和 `artifacts\temp_audio` 可释放空间，但不会删除。

确认删除：

```powershell
cs2pov clean output_v014_round_tiny --yes
```

预期：删除 voice/temp_audio 缓存。注意删除后如需重新转录，需要重新跑 extract_voice。

## 7. 反馈包建议包含

请打包每个模式的：

```text
manifest.json
progress.log
errors.log（如果有）
artifacts\transcription_coverage.json
artifacts\transcript_segments.jsonl
final\team_2.bilingual.srt
```

至少包含以下三个目录的结果：

```text
output_v014_round_tiny
output_v014_activity_tiny
output_v014_round_small
```

本轮最关键判断：

```text
round/activity 模式是否解决 v0.1.3 的超长字幕 cue；
VAD ON 是否应保留为默认；
clean 命令是否能控制磁盘膨胀。
```
