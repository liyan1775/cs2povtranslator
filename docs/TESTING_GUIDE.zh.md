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

## 新版领域契约重放（02A）

使用固定的匿名三回合 JSON，在全新 Python 子进程中重建对象图并验证时间、引用、
指纹、draft 与 review 的确定性聚合：

```powershell
py -3.12 scripts/check_new_domain_contract.py
```

该命令只使用仓库内匿名 JSON，不需要 CS2、GPU、模型或 API。

## 新版 Job 仓储历史重放（02B）

下面的命令不是几个同进程单元测试的包装。它会用生产仓储 API 在“第一天”创建
完整三回合 Job，再启动全新的 Python 进程，在“第二天”列出并严格打开该 Job，
读取模型/转录/理解翻译/复核/事件与最终字幕，同时对比读取前后的所有文件字节、
mtime 和目录，证明查看没有写入：

```powershell
py -3.12 scripts/check_new_job_repository.py
```

它还用屏障同步的真实子进程验证并发创建只有一个赢家、writer claim 只有一个
owner、过期旧 owner 不能发布、manifest 校验与原子发布处于同一把 OS 锁内；并
验证损坏/不支持 schema 的同级 Job 被隔离、无 `repository.json` 的 v0.x 目录被
忽略、Demo 持久源暂时不可用时已有最终字幕仍可读取。成功时只打印：

```text
new job repository replay passed
```

这里的“历史 Job”只指同一个新版程序族在更早会话或更早日期创建的 Job。当前
明确不验收 v0.x 或跨 schema 版本加载。运行本重放不需要 CS2、GPU、模型、网络
或 API，也尚未声称已经实现按回合翻译调度。

## 回合编排与进程恢复回放（02C-B）

运行下面的检查可以验证任务落盘、writer claim、崩溃后接管、可复用成功结果、
反序 worker 完成、规范回合排序和最终 Draft 组合：

```powershell
py -3.12 scripts/check_round_orchestration.py
```

检查器会启动独立的 producer、恢复 consumer 和最终验证 consumer。producer 以
固定退出码模拟进程崩溃并留下活动 claim；恢复前的列表、查看、检查和抢占尝试
必须保持只读且拒绝写入；租约过期后才允许新会话接管。成功结果不会因为另一个
回合恢复而重新调用 worker，同级损坏 Job 也不会阻断健康 Job。通过时标准输出
只有：

```text
round orchestration replay passed
```

对应测试为 `tests/test_round_orchestration_replay.py`。调度器的并行、重试、取消
和心跳边界由 `test_round_scheduler_parallel_v1.py` 与
`test_round_scheduler_recovery_v1.py` 覆盖；这些测试使用注入时钟和异步 worker，
不依赖真实 provider 或墙上时间等待。

## 现有管线 Demo/回合端口测试（02D-1）

运行下面的测试可以验证旧版 Demo 解析输出到当前版本 `DemoTimeline` 的转换，以及
新版 Job 的 claim 保护和时间线持久化：

```powershell
py -3.12 -m pytest -o addopts= tests/test_pipeline_ports_v1.py -q
```

测试使用 fake parser，不需要 demoparser2 或真实 Demo。它覆盖 tick 回合、fallback
回合、warmup/短回合边界、浮点秒到整数微秒的确定性转换、玩家和地图元数据校验、
解析失败不创建半成品 Job，以及新 Job 的 `timeline/` 文件发布。旧版管线回归仍由
原有测试套件覆盖。

## 语音活动与 ASR 端口测试（02D-2）

运行下面的测试可以验证旧版语音提取结果、压缩音频样本锚点、语音活动、ASR cue、调用
指纹和新版 Job 语言图之间的引用闭包：

```powershell
py -3.12 -m pytest -o addopts= tests/test_voice_asr_ports_v1.py -q
```

测试使用合成语音包和 fake ASR，不需要 demoparser2、faster-whisper、模型下载或真实
Demo。它覆盖重叠玩家活动、无回合归属、跨静音来源拒绝、单回合失败隔离、Job 重开后
语言图读取，以及旧版 WAV/包清单到当前版本样本范围的转换。真实模型 smoke 仍属于
后续验收阶段，不作为本阶段门禁。

## 理解翻译与回合调度测试（02D-3）

运行下面的测试可以验证旧版 LLM 返回到当前版本理解翻译文档的转换，以及从 Job 配置
快照启动回合调度：

```powershell
py -3.12 -m pytest -o addopts= tests/test_translation_ports_v1.py -q
```

测试覆盖 dry-run、跳过翻译、旧版 `translations` 返回形状、模型快照传递、provider
错误的稳定映射、原始错误细节隔离、调用指纹、理解文档闭合、Job 重开和完成阶段推进。
测试使用 fake provider，不访问真实 API；并发、逆序完成、取消、重试和心跳的调度边界
由既有 `test_round_scheduler_parallel_v1.py` 与 `test_round_scheduler_recovery_v1.py`
继续覆盖。真实 provider、限流行为和金标准双跑留在 02D-5。

## 字幕导出与当前 Job 产物测试（02D-4）

运行下面的测试可以验证当前 Draft/Reviewed 时间线到字幕文件的适配，以及字幕文件与
Job manifest 的发布边界：

```powershell
py -3.12 -m pytest -o addopts= tests/test_subtitle_ports_v1.py tests/test_subtitle_job_export_v1.py -q
```

定向测试覆盖整数微秒到 SRT 毫秒的舍入、既有字幕策略、整场和逐回合 timebase、
Draft/Reviewed 文本选择、玩家/队伍范围、内容哈希登记、Job 重开、重复产物保护和
文件写入失败清理。旧版字幕行为继续由 `test_subtitle.py` 与
`test_subtitle_policy_v050.py` 覆盖。测试使用合成新版 Job，不访问真实 Demo、ASR、
LLM 或视频工具；真实 provider、真实 Demo 和金标准双跑留在 02D-5。

## 本地 Web 复核与音频媒体测试（02E-1、02E-2）

运行下面的定向测试可以验证本地查询 API、复核投影、只读页面、当前 Job 音频清单和
受控媒体响应：

```powershell
py -3.12 -m pytest -o addopts= -q `
  tests/test_domain_media_v1.py `
  tests/test_web_query_v1.py `
  tests/test_web_http_v1.py `
  tests/test_voice_asr_ports_v1.py
```

测试覆盖媒体引用的工作区相对路径、WAV 内容哈希和元数据、清单与文件集合一致性、
Job 重开后的媒体读取、Cue 时间范围、未知媒体 ID 拒绝、完整音频响应、单字节范围
响应和无效范围处理。测试使用合成音频，不需要真实 Demo、ASR、LLM 或浏览器；浏览器
级复核流程仍属于 02E-4 的验收范围。

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
# 本地管理界面查询测试（02E-1）

运行下面的定向测试可以验证当前版本 Job 查询投影和本地 WSGI API：

```powershell
py -3.12 -m pytest -o addopts= tests/test_web_query_v1.py tests/test_web_http_v1.py -q
```

测试覆盖工作区诊断、DemoAsset 列表、健康与损坏 Job 隔离、Job 事件、回合数据按
Demo 时间排序、稳定错误结构、无绝对路径和可访问页面骨架。测试直接调用 WSGI
应用，并额外使用真实文件系统仓储创建一个当前版本 Job；不需要启动端口、CS2、GPU、
真实 Demo、ASR、LLM 或 API。

# 02C-A 回合任务状态回放

`py -3.12 scripts/check_new_job_state.py` 在独立进程中重放三回合状态序列：
乱序完成、重试等待、取消后恢复、草稿/正式阶段分支，以及仅一个回合输入变化时的失效。
回放使用生产状态函数，比较静态期望与每次转换的规范化指纹；未知字段、重复 JSON 键和被篡改结果均使检查失败。

产物清理在合法 `COMPLETED_WITH_VIDEO` 分支上使用四类合成索引进行验证：翻译配置
失效撤销 timeline/subtitle/green_screen/video 与 active review；render-only 失效
仅撤销 video，保留复核及其余三类产物。mutation 回归确认生产 rewind 若保留旧产物，
回放会拒绝该行为。此检查不创建实际媒体文件。

2026-09-06 已确认验证及 commit/CI 待办集中记录于
[A 交付清单](superpowers/plans/2026-09-03-round-task-state-core.md#delivery-record--2026-09-06)；
Sagan 最终全量为 2233 passed、28 skipped，95.87 秒，exit 0；全部 16 个
changed/untracked Python 文件 Ruff、compileall、diffcheck 通过，计划扫描无匹配。
主协调器确认 A 已经 PR #22 合并为 `373d556`，PR 全部 8 checks 通过，
post-merge CI `34019305517` completed/success。B 的测试与集成证据单独登记。

相关测试位于 `test_domain_job_tasks_v1.py`、`test_domain_job_task_state_v1.py`、
`test_domain_job_state_v1.py`、`test_domain_invalidation_v1.py` 和
`test_new_job_state_replay.py`。这些测试证明当前状态契约，不作为真实并发性能、持久化崩溃恢复或翻译质量的验收证据。
