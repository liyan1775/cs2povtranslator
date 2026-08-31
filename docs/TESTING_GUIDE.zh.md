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

先初始化/选择工作区；默认 Job 写入工作区 `jobs/`，模型缓存和临时音频也跟随工作区。建议先只跑前 3 个含语音回合：

```powershell
cs2pov workspace init "D:\cs2pov-workspace"
cs2pov run "D:\demos\match.dem.zst" `
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
cs2pov export --preset editing
cs2pov export --preset review
cs2pov export --format compact
cs2pov export --format zh_clean
```

## 反馈包

```powershell
cs2pov feedback
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

# 工作区 Job runtime E2E

使用真实 Python 子进程和合成 `.dem`（只运行到 `prepare_input`），验证默认
Job 落在工作区 `jobs/`、Demo 自动进入工作区素材库且 Job/input 保持为空、显式
`--output` 的兼容警告与 manifest 标志，以及损坏工作区时在创建 Job/导入素材前稳定失败且
旁路目录和已有文件不变：

```powershell
python scripts/check_workspace_job_runtime_e2e.py
```

# 工作区 DemoAsset 素材库 E2E

使用真实 Python 子进程、匿名合成 `.dem/.dem.zst` 和隔离 HOME，验证跨格式内容
去重、首源保持、只读 inspect、缓存重建、6 进程并发、损坏持久源拒绝覆盖，以及
源码树/用户目录无旁路写入：

```powershell
python scripts/check_workspace_demo_asset_e2e.py
```

这个 E2E 不读取真实 Demo、GPU、CS2、模型或 API。它验收显式素材库本身。

# 工作区 Pipeline DemoAsset E2E

使用真实 Python 子进程调用安装后的 CLI，验证新 Job 自动导入/复用、manifest 只保留
引用、Job `input/` 不复制 Demo、缓存重建、工作区切换、legacy resume、损坏资产前置
失败和 HOME/cwd/源码树隔离：

```powershell
python scripts/check_workspace_pipeline_demo_asset_e2e.py
```

成功时必须打印唯一成功行：

```text
workspace Pipeline DemoAsset E2E passed: auto-import, reference-only jobs, resume, legacy compatibility, and isolation
```

该 E2E 只运行到 `prepare_input`，不需要 CS2、GPU、真实 Demo、ASR、LLM 或 API。
CI 在 Ubuntu Python 3.11/3.12/3.13 和 Windows Python 3.12 的同一测试矩阵中运行它。
