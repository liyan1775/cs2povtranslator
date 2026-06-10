# v0.1.7 测试计划

v0.1.7 是维护版，不需要大规模重跑所有 ASR 模式。重点验证：

1. v0.1.6 的安全修复没有退化；
2. 旧模型名会被提示迁移；
3. 新向导默认模型不再推荐 `deepseek-chat`；
4. 默认字幕 smoke test 没有退化。

## 0. 安装与单元测试

```powershell
cd D:\个人项目\cs2pov_arch_project
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
pytest -q
```

预期：

```text
23 passed
```

## 1. 检查默认配置隐藏 key

```powershell
cs2pov config show
```

预期：

- 不显示真实 API key；
- 如果本机仍配置 `deepseek-chat`，会显示：

```json
"llm_model_deprecated": true,
"recommended_llm_model": "deepseek-v4-flash"
```

并打印迁移提示。

## 2. 检查 doctor 模型提示

```powershell
cs2pov doctor
```

预期：

- 依赖检查正常；
- API key 只显示 `[已配置]`；
- 如果当前模型仍是 `deepseek-chat` 或 `deepseek-reasoner`，出现迁移提示。

## 3. 手动迁移 DeepSeek 模型配置

```powershell
cs2pov config set --model deepseek-v4-flash
cs2pov config show
```

预期：

```json
"llm_model": "deepseek-v4-flash",
"llm_model_deprecated": false
```

并且不再打印旧模型提示。

## 4. 默认 smoke test

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v017_default `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

重点检查：

```text
manifest.json
artifacts\transcription_coverage.json
final\team_2.bilingual.srt
progress.log
```

预期：

- `manifest.json` 仍然不能出现 `sk-`；
- `coverage` 仍有 before/after 字段；
- `long_transcript_segments_gt_30s = 0`；
- `longest_transcript_segment_seconds` 接近 v0.1.6，不应明显退化；
- SRT 没有重新出现 30s+ 长 cue 或纯标点幻觉。

## 5. 可选：验证向导默认模型

运行：

```powershell
cs2pov-wizard
```

在“配置 LLM”步骤，如果没有默认模型，预期默认值为：

```text
deepseek-v4-flash
```

## 反馈包建议包含

如果有问题，请打包：

```text
manifest.json
progress.log
errors.log
artifacts\transcription_coverage.json
final\team_2.bilingual.srt
cs2pov config show 的输出截图或文本，注意不要使用 --show-secrets
cs2pov doctor 的输出截图或文本
```
