# v0.1.6 测试计划

本版主要测试安全修复和 coverage 诊断增强，不要求重新完整评估所有 ASR 模式。

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
20 passed
Doctor 中 LLM api_key 只显示 [已配置] / [未配置]，不显示真实 key
```

## 1. 检查 config show 是否默认隐藏 key

先确认你已经配置过 key：

```powershell
cs2pov config show
```

预期：

```json
"llm_api_key": "[已配置-已隐藏]",
"llm_api_key_configured": true
```

并且终端输出里不能出现 `sk-...` 明文。

只有你主动执行下面命令时，才允许显示真实 key：

```powershell
cs2pov config show --show-secrets
```

## 2. 跑默认 smoke test

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v016_default `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

## 3. 核查 manifest 是否隐藏 key

打开：

```text
output_v016_default\<job>\manifest.json
```

预期：

```json
"llm_api_key": "[已配置-已隐藏]",
"llm_api_key_configured": true
```

并且整个 `manifest.json` 中不能出现 `sk-`。

## 4. 核查 coverage before/after 字段

打开：

```text
output_v016_default\<job>\artifacts\transcription_coverage.json
```

预期新增字段存在：

```json
"raw_transcript_segments_before_postprocess": ...,
"postprocessed_transcript_segments": ...,
"coverage_ratio_before_postprocess": ...,
"coverage_ratio_after_postprocess": ...,
"coverage_note_after_postprocess": "..."
```

如果 after coverage 比 before 低，但 SRT cue 更短且无长时间挂屏，这是可接受的。

## 5. 反馈包建议

如果 v0.1.6 仍有问题，请打包：

```text
manifest.json
progress.log
errors.log
artifacts\transcription_coverage.json
artifacts\transcript_segments.jsonl
final\team_2.bilingual.srt
review\team_2.original.srt
```

请不要额外打包 `~/.cs2pov/config.json`；如果必须打包，请先手动删除 `llm_api_key`。
