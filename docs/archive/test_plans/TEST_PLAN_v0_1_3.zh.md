# v0.1.3 测试计划

本版重点测试两个问题：

1. `.bat` 是否能正确使用项目 `.venv`；
2. Whisper 短语音漏检是否有所改善，并能否通过覆盖率产物量化。

## 0. 安装与基础检查

在项目根目录运行：

```powershell
cd D:\个人项目\cs2pov_arch_project
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
pytest -q
cs2pov doctor
```

预期：

```text
pytest: 13 passed
cs2pov doctor: demoparser2 / zstandard / pyogg / faster_whisper 均为 OK
Whisper VAD: OFF
```

## 1. 测试双击启动脚本

直接双击：

```text
Start_CS2_POV_Translator.bat
```

预期：

- 不再出现 `ModuleNotFoundError: No module named 'cs2pov'`；
- 能进入中文向导；
- 如果 `.venv` 不存在，脚本应提示安装步骤，而不是直接调用系统 Python 报错。

中文脚本也可以测一次：

```text
启动 CS2 POV Translator.bat
```

但仍推荐优先使用英文文件名脚本。

## 2. tiny 默认关闭 VAD 对照测试

运行：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v013_tiny_no_vad `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

重点看：

```text
artifacts\transcript_segments.jsonl
artifacts\transcription_coverage.json
progress.log
final\team_2.bilingual.srt
```

与 v0.1.2 对比：

- v0.1.2 Team 2 全量 transcript 参考值：约 424 条；
- v0.1.2 LLM smoke 里 Team 2 转录参考值：约 311 条；
- v0.1.3 默认关闭 VAD 后，转录数理论上可能上升，但也可能出现更多噪声/幻觉，需要结合 SRT 人工看质量。

## 3. tiny 开启 VAD 对照测试

运行：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v013_tiny_vad `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3 `
  --whisper-vad
```

对比：

```text
output_v013_tiny_no_vad\...\artifacts\transcription_coverage.json
output_v013_tiny_vad\...\artifacts\transcription_coverage.json
```

判断：

- 哪个 transcript 数量更高；
- 哪个字幕质量更可读；
- 是否出现明显幻觉。

## 4. small 模型质量测试

运行：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v013_small_no_vad `
  --whisper-model small `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

重点判断：

- small 是否识别出更多短报点；
- small 是否比 tiny 更慢但质量明显更好；
- 是否值得把向导默认推荐从 base 改成 small 或保持 base。

## 5. 未识别语音占位测试

运行：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v013_unrecognized `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3 `
  --include-unrecognized-voice `
  --unrecognized-min-duration 0.35
```

预期：

- `transcript_segments.jsonl` 中出现 `id` 以 `unrec_` 开头的片段；
- `final\team_2.bilingual.srt` 中可能出现 `[未识别语音]`；
- 这不是最终推荐字幕，而是用来检查 ASR 漏检位置的 debug 模式。

## 6. 小范围真实 LLM 回归测试

确认前面没问题后，再跑：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v013_llm_smoke `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 1
```

预期：

- 仍然只向 LLM 发送前 1 个含语音有效回合；
- `translated_segments.jsonl` 中有真实中文翻译；
- `[未识别语音]` 不会被发送给 LLM 做无意义翻译。

## 7. 反馈包请包含

如果有问题，请打包：

```text
manifest.json
progress.log
errors.log
artifacts\demo_info.json
artifacts\voice_activity.jsonl
artifacts\transcript_segments.jsonl
artifacts\transcription_coverage.json
artifacts\rounds_raw.json
artifacts\rounds.json
artifacts\round_contexts.jsonl
artifacts\translated_segments.jsonl
final\*.srt
review\*.srt
```

如果是 `.bat` 问题，请截图或复制终端里的完整报错。
