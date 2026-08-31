# 测试与反馈流程

本项目采用版本化闭环测试流程：每个版本都有测试计划，真实 Windows 环境跑完后用 feedback 包回传。

## 基础测试

```powershell
pip install -e ".[all]"
pytest -q
cs2pov setup-check
cs2pov doctor
cs2pov config show
```

预期：

- pytest 全部通过。
- `config show` 不显示 API key 明文。
- `doctor/setup-check` 中文不乱码。

## 真实 demo smoke

建议先只跑前 3 个含语音回合：

```powershell
cs2pov run "D:\demos\match.dem.zst" `
  --output output_smoke `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 3 `
  --dry-run-translation
```

检查：

- `final/*.bilingual.srt` 是否生成。
- `progress.log` 是否完整。
- `manifest.json` 是否无 `sk-`。
- `artifacts/transcription_coverage.json` 是否存在。

## 重新导出测试

不需要重新跑 Whisper/LLM：

```powershell
cs2pov export output_smoke --preset editing
cs2pov export output_smoke --preset review
cs2pov export output_smoke --format compact
cs2pov export output_smoke --format zh_clean
```

## 反馈包

```powershell
cs2pov feedback output_smoke
```

反馈包应包含：

- manifest.json
- progress.log
- errors.log
- demo_info.json
- transcription_coverage.json
- glossary_used / glossary_warnings（如果有）
- final/review/debug 下的 SRT

反馈包不应包含：

- 原始 demo
- `artifacts/voice/`
- `artifacts/temp_audio/`
- API key
- 本地绝对路径

## 本地 agent 报告如何处理

本地 agent 报告只能作为线索。审阅反馈包时必须直接检查真实产物，尤其是：

- SRT 是否真的可用。
- coverage 是否被误读。
- manifest 是否脱敏。
- feedback zip 是否误打包大文件。
- 失败日志是否与报告结论一致。
# 工作区模型 runtime E2E

使用真实 Python 子进程验证选中工作区的模型缓存隔离、旧缓存只读检测和 override 拒绝：

```powershell
python scripts/check_workspace_model_runtime_e2e.py
```
