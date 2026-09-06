# 金标准夹具

`manifest.json` 固定 v0.9.8 可信基线的输入、聚合预期、理解翻译案例、旧字幕输出和已知缺陷。

素材分为两层：

1. `checked-in`：只包含很小的确定性 JSON 合成配方、结构化时间线和期望字幕，可在 GitHub CI 稳定重放；
2. `local-only`：真实 Demo 和旧字幕不进入 Git，只登记匿名夹具 ID、字节数、SHA-256 和不含身份信息的聚合预期。

本目录不得加入 Demo、音视频、模型、SteamID、API Key 或本机绝对路径。真实素材由后续统一工作区按哈希定位。

校验清单：

```powershell
python scripts/check_golden_baseline.py
```

同时重放选定的旧版本行为测试：

```powershell
python scripts/check_golden_baseline.py --replay
```

在本机确认一份真实 Demo 是否匹配已登记夹具（可以重复传入）：

```powershell
python scripts/check_golden_baseline.py --local-fixture "authorized-demo-anubis-local-v1=D:\你的目录\demo.dem"
```

校验器只输出匿名夹具 ID，不回显文件路径或哈希；它也不会复制、移动或修改 Demo。

在冻结 v0.9.8 基线中，`be be be → B, B, B` 仍只是候选，不能改写旧 ASR；在
`new_domain_contract_v1.json` 中，它已作为新契约的三层文本示例。

`structured_timeline_v1.json` 仍是冻结的 v0.9.8 基线；`new_domain_contract_v1.json`
校验当前版本的新领域契约。后者不是旧版输出等价性的证明，不得作为 legacy
输出等价来介绍。

`new_job_repository_v1.json` 在 02A 三回合契约之上固定新版 Job 仓储的 marker、
manifest、Demo 引用、模型/语言/复核 shard、事件和最终字幕哈希。它由以下命令在
真实的“第一天生产者进程 → 第二天消费者进程”中重放：

```powershell
py -3.12 scripts/check_new_job_repository.py
```

该夹具只证明同一新版程序族创建的较早 Job 可以只读打开；不承诺 v0.x 或跨版本
兼容。夹具只含匿名 ID、相对逻辑路径和合成文本，不含真实 Demo、绝对路径、用户
标识、SteamID、URL、API Key 或需要联网的模型。

`new_job_state_v1.json` 固定三个合成回合的输入、结果摘要和预期任务历史，
由 `scripts/check_new_job_state.py` 通过生产状态函数进行重放。修改夹具预期必须说明
契约变更依据，不得仅为消除失败重新生成。该夹具验证状态策略，实际并行与跨进程任务恢复由 02C-B 的独立回放验收。

2026-09-06 审查修正补足了失效清理覆盖：回放通过合法生产 phase 转换到
`COMPLETED_WITH_VIDEO`，附加 timeline、subtitle、green_screen、video 四类合成
`FinalArtifactEntry`，不创建媒体文件。翻译配置失效清空四类当前引用和 active review；
独立 render-only 失效保留 review、timeline、subtitle、green_screen，仅撤销 video。
保留旧产物的 rewind mutation 已先复现遗漏、再被修正后的回放拒绝。

本次夹具预期仅增加完成分支及两种失效结果字段；三回合任务历史与原转换指纹保持不变。
修改依据是原空 artifact index 无法验证生产清理行为，具体期望由独立语义断言固定，
不从运行结果批量生成。主协调器已独立确认该回放测试 8 passed、旧 golden 15 passed；
A 最终全量已由 Sagan 确认 2233 passed、28 skipped；Task 5 脚本/fixture/CI 已提交于
`3c8d25c`，文档提交及远程集成待完成，GitHub 尚未推送，详见 [A 交付记录](../../docs/superpowers/plans/2026-09-03-round-task-state-core.md#delivery-record--2026-09-06)。
