# 架构说明

本文说明 CS2 POV Translator 的核心设计。项目目标不是做一个炫技 demo，而是做一个能长期演进的本地字幕工程工具。

## 一句话架构

```text
Demo 输入
  → PipelineEngine
  → Job 目录
  → 中间产物 artifacts
  → 可复跑/可检查/可导出的 SRT 字幕工程
```

CLI、`.bat`、未来 UI 都只是入口。核心是 PipelineEngine 与 Job artifacts。

## 分层结构

```text
src/cs2pov/
  cli/          # 命令行、向导、菜单式启动器
  application/  # 工作区 runtime、Job 与 DemoAsset 用例边界
  pipeline/     # PipelineEngine、Manifest、Progress
  domain/       # Player/Round/Segment/Subtitle 等核心模型
  services/     # 业务服务：demo、voice、transcription、translation、subtitle、dictionary
  adapters/     # 外部依赖适配：demoparser2、PyOgg、faster-whisper、LLM
  storage/      # ArtifactStore、DemoAsset 仓储、ConfigStore、JSONL 工具
```

## DemoAsset 素材库（01E-A）

```text
外部 .dem / .dem.zst（只读）
  → 流式计算解压后 SHA-256
  → library/demos/<asset_id>/asset.json + 首次持久源
  → cache/decompressed_demos/<asset_id>.dem（仅压缩源、可重建）
```

`.dem` 与不同压缩参数的 `.dem.zst` 只要解压内容相同，就共享一个逻辑
`asset_id`；第一个成功提交的持久源格式和字节不会被后续导入替换。导入采用
工作区内 staging 和同文件系统原子提交，多进程竞争只接受完整赢家。`demos
list/inspect` 是只读操作；缓存只能由 import 或内部 resolve 重建。

新建 Pipeline Job 会在入口处把外部 Demo 导入当前工作区并预检一次，然后把
`DemoAssetRef`、安全显示名和绑定的素材服务交给 `PipelineEngine`。Engine 只解析
这份绑定引用，不重新查找全局工作区；受管 Job 的 `input/` 不再放 Demo 副本或链接。
旧 Job 仍走原来的 `input/` 路径，不自动迁移。外部 `--output` 只改变 Job 位置，
不改变素材所属工作区。

删除解压 cache 是安全的：需要 Demo 的阶段会从工作区持久源重建。切换到没有该
素材的工作区时，需要 Demo 的 resume 会在写 Job 前稳定失败；不需要 Demo 的后段
resume 不会被无关的素材缺失阻塞。这样素材管理与按回合解析、翻译、字幕和 overlay
数据流保持分离，主产物仍是按回合对齐的双语字幕及校对/overlay 文件。

## 核心原则

1. **本地优先**：demo、WAV、输出字幕默认留在本地。
2. **阶段明确**：每个阶段都有输入、输出、日志和状态。
3. **中间产物可审计**：JSON / JSONL 是项目内部 API。
4. **入口不拥有业务逻辑**：CLI/Wizard/Launcher 只负责交互，PipelineEngine 负责流程。
5. **外部依赖适配化**：demoparser2、PyOgg、Whisper、LLM 都通过 adapter/service 接入。
6. **失败可反馈**：feedback 包排除大文件和敏感信息，保留诊断产物。

## Pipeline 阶段

| 阶段 | 作用 | 主要产物 |
|---|---|---|
| prepare_input | 解析受管 DemoAsset（legacy Job 才复制或解压） | 受管 Job 不写 Demo 到 `input/` |
| inspect_demo | 读取地图、玩家、demo 信息 | `artifacts/demo_info.json` |
| extract_voice | 解析语音包并解码 Opus | `artifacts/voice/` |
| build_voice_activity | 构建语音活动时间轴 | `artifacts/voice_activity.jsonl` |
| parse_rounds | 解析并清洗回合边界 | `artifacts/rounds_raw.json`, `artifacts/rounds.json` |
| transcribe | Whisper 转录并映射回 demo 时间轴 | `artifacts/transcript_segments.jsonl` |
| build_round_contexts | 以回合为单位聚合队伍语音 | `artifacts/round_contexts.jsonl` |
| translate | 按回合调用 LLM 翻译 | `artifacts/translated_segments.jsonl` |
| export_subtitles | 导出多种 SRT | `final/`, `review/`, `debug/` |

## Job 目录

一个 Job 目录就是一个字幕工程。

```text
jobs/20260610_161929_de_mirage/
  input/                  # legacy Job 的 demo；受管 Job 通常为空
  artifacts/              # 可复跑的中间产物
  final/                  # 最推荐给剪辑软件使用的字幕
  review/                 # 校对用字幕
  debug/                  # 排查用字幕
  manifest.json           # 阶段状态和配置快照
  progress.log            # 进度日志
  errors.log              # 错误日志
```

## Manifest

`manifest.json` 保存 Job 的配置、阶段状态、关键 artifact 路径和（受管 Job 的）
`DemoAssetRef`。公开/反馈场景中不能包含：

- API key
- 原始本地绝对路径
- 原始 demo 文件
- 大音频路径

v0.6.1 起，artifact 路径统一尽量使用 Job 内相对路径。

## 为什么按回合翻译

CS2 队内语音很短、碎、上下文强。逐句翻译容易误译；按回合聚合后，LLM 能看到同一回合的战术沟通，再把翻译回填到原时间轴。

## 为什么先 CLI

项目真正难点是 demo 解析、语音解码、ASR、LLM、时间轴回填、恢复与反馈，不是窗口。强引导 CLI 可以先把主链路打磨稳定，再考虑 UI。

## 为什么词典不硬替换

词典用于 prompt 约束和 warning 报告，不做强制字符串替换。原因是 ASR 可能误识别，如果翻译后硬替换，会把错误放大。当前 `de_mirage` / `de_dust2` 词典试点只验证机制，不追求全地图覆盖。

# 工作区 runtime 与模型边界

`WorkspaceRuntime` 已由 01D-A/01D-B 接入模型扫描、加载、run、Job、Demo、向导、输出和临时音频路径；01E 又加入受管 DemoAsset 素材管理。默认 Job 使用当前工作区 `jobs/`，模型缓存与临时音频跟随工作区；旧配置与环境缓存仅作为只读迁移候选。显式 `--output` 是带警告的旧版兼容选项，旧 Job 可原地读取和修改，但写操作需要健康工作区。理解翻译、Web UI、录制、素材删除和旧 Job 正式迁移不属于当前实现范围。

## 新版领域与统一时间内核（02A）

02A 的新版领域模块是隔离的契约层，当前只验证对象图、引用和确定性重放，尚未
接入 `Pipeline`。统一时间内核以 Demo 微秒为唯一真相；Demo tick、紧凑音频采样
等来源时钟只能通过分段 `TimeAnchor` 映射到这条微秒时间线，不能把来源时钟当作
持久化的相互替代品。

对象图明确分成三层文本：`asr_original`（原始转录）、`interpreted_source`（结合
语境理解后的来源语义）、`translated_zh`（中文翻译）。三者始终独立保存，不能
互相覆盖。`ReviewDecision` 与最终复核值属于额外的复核层，也不能覆盖这三层
文本；回合文档只承载有回合归属的 cue。

回合 worker 可以并行完成，持久化聚合仍按权威回合顺序、Demo 时间和 cue ID
确定性排序，因此完成顺序不会改变 cue 顺序或 fingerprints。成功但无语音的
speechless 回合用空 results 且无 invocation 表示；尚未归属回合的 activity/cue
仍需通过时间线与引用校验，但不进入任何回合文档或 draft。

同版本历史 Job 重开时必须重新校验当前契约、配置快照、invocation 和指纹；旧
Job 自动迁移以及旧版与新版之间的跨版本兼容尚未实现。

## 新版 Job 仓储与历史打开（02B）

这里的“历史 Job”有一个很窄、也很现实的含义：用户昨天用同一个新版程序创建
了 Job，今天再次打开查看。它不是 v0.x 旧 Job，也不是不同新版 schema 之间的
自动迁移。本阶段有意不支持旧版与跨版本加载，精力先集中在把新版仓储做完整。

新版 Job 以 `repository.json` 作为边界标记，以 `job.json` 保存身份、阶段、运行
状态、回合进度、模型配置快照、活动复核版本和最终产物哈希。时间线、语音活动、
模型调用、逐回合转录、理解翻译、人工复核、最终双语时间线及事件日志分别落在
类型明确的 shard 中。打开 Job 时会重新验证文件名与内容身份、引用闭包、内容
指纹和最终产物哈希；一个损坏 Job 不会阻止健康的同级 Job 出现在列表中。

列表、查看、检查和历史重开都是严格只读操作，不会顺手创建锁、修复 claim、更新
时间戳或改写 manifest。只有用户明确执行继续、重试或编辑时才取得唯一 writer
claim。若持久状态仍是 `running`，但 claim 已丢失或过期，界面只在内存中显示为
`interrupted`；直到未来明确继续前，磁盘保持原样。事件日志只隔离最后一条未完成
记录，前面完整事件仍可查看。

02B 已把 02A 的三层文本与三回合对象图持久化，并能重新打开活动复核及最终双语
时间线；它还没有把各回合提交给翻译调度器。因此“不同回合并行翻译”仍是后续
调度层能力，不应从当前仓储测试推断已经完成。整批仓储与历史打开验收只使用匿名
合成数据，不需要 CS2、GPU、真实 Demo、模型下载或 API。POV 录制仍可在另一台有
CS2/GPU 的机器上作为独立模块后加。

## 回合任务状态核心（02C-A）

`domain/job_tasks.py` 定义当前版本回合任务、尝试历史、结构化错误及重试策略；
`job_task_state.py` 实现不可变状态转换。每次重试保留实际输入、配置和调用记录，
输入发生变化时只撤销当前结果，不删除历史尝试。等待重试期间取消不会改写已结束的尝试。

`job_state.py` 提供显式 Job 阶段图及回合统计。只有活动复核引用存在时才允许进入
`REVIEWED` 与 `FINAL_TIMELINE_READY`；引用指向的完整对象图仍由仓储与协调器校验。
`COMPLETED_DRAFT` 是独立草稿终态，不能视为已复核；`COMPLETED_WITHOUT_VIDEO`
允许无视频完成，`READY_FOR_RENDER` 仅表示等待录制适配器接续。

`invalidation.py` 以不可变依赖矩阵生成最小失效计划，保留原始证据及历史文件，
仅撤销相关的当前复核/产物引用。回退只能到已到达的同一阶段分支检查点，
不能借失效操作跳过未完成阶段。当前摘要在后续协调器中按任务分片重新计算。

本批交付纯领域策略及确定性回放，不启动 worker，不持久化回合任务，不调用真实
模型 API。受限并行、任务落盘、取消和进程恢复由 02C-B 接续；Web 和视频运行时仍属后续交付。

## 回合编排运行时（02C-B）

02C-B 将回合翻译拆成独立任务。任务分片保存每个回合的输入指纹、配置快照、
当前状态、尝试历史和结构化错误；每次状态替换都经过同一个 Job writer claim
校验。任务初始化允许从部分落盘状态继续，但新一代任务必须覆盖当前时间线的
完整回合集合。

worker 只接收当前回合的最小语音投影和安全配置快照，不接触 Job 路径、写入权、
完整仓储对象或秘密。协调器在保存成功结果前重新读取完整持久化证据，校验理解
文档、模型调用和时间线的引用闭包，再按调用记录、理解文档、任务状态、manifest
摘要和事件的顺序提交。成功结果一旦提交，后续回合失败或取消不会撤销它。

调度器使用有上限的并行执行；回合完成先后只用于诊断，任务和 Draft 始终按 Demo
时间线与 cue ID 的规范顺序生成。重试等待由指数退避和服务端建议等待时间共同
决定，任务耗尽后进入失败终态。用户取消时，已排队的 pending 任务保持待运行，
实际运行中的任务进入 cancelled；等待重试的任务取消时保留已经结束的失败尝试。
调度器在后台刷新 writer claim，心跳失效会停止本批次并保留已成功的同级回合。

同一新版 Job 的进程重启通过显式恢复完成：过期 claim 被归档，遗留的 running
任务先标记为 interrupted 再回到 pending，已经 succeeded 的回合及其结果直接复用。
列表、查看和检查仍是只读操作；继续、重试和取消才会取得新的 writer claim。
02C-B 的进程回放只使用匿名合成数据，不接入真实模型、API、CS2、GPU、Web UI 或
视频录制。

## 现有管线端口化接入（02D-1）

02D-1 新增 `application.pipeline_ports` 作为旧版 Demo 解析器与当前版本领域时间线之间的适配边界。`LegacyDemoParserPort` 只调用既有解析器的描述和回合解析能力，再将结果转换为 `DemoDescriptor`、`RoundCollection`、`TimeAnchor` 和 `DemoTimeline`；它不写入 `ArtifactStore` 或旧版 `PipelineManifest`。

旧解析器返回的浮点秒只在适配层存在。当前版本对象使用整数 Demo 微秒；有完整 tick 边界的回合生成 `demo_tick` 锚点并保留规范回合 ID，没有可靠 tick 边界的回合使用明确的 estimated/fallback 置信度，不伪造锚点。`CurrentJobTimelineApplicationService` 先完成解析和领域校验，再创建新版 Job，并通过 `FileSystemJobRepository` 的 claim 原子保存时间线和推进阶段。

这一阶段只接入 Demo 描述和回合时间线。语音活动、ASR、理解翻译、字幕导出以及真实 provider 仍按 02D-2 至 02D-5 逐步接入；旧版 `PipelineEngine` 继续使用原有文件格式和入口。

## 语音活动与 ASR 端口化接入（02D-2）

02D-2 新增 `application.voice_asr_ports`，把旧版 Opus 语音提取结果转换为当前版本的压缩音频样本锚点和 `VoiceActivityCue`。WAV、包清单和 ASR 临时切片只存在于工作区缓存；新版 Job 只保存 `timeline/time_anchors.jsonl`、`voice/activities.jsonl` 以及逐回合转录文件，不把旧版 `ArtifactStore` 当作持久权威。

每个语音活动使用一个独立的 ASR 窗口。来源样本、Demo 微秒、回合引用、语音活动引用和 ASR 调用指纹在写入前完成闭合校验；跨静音的来源范围、未知玩家、越界样本和不连续映射会被拒绝。无回合归属的 cue 进入 `transcript/unassigned.jsonl`，无语音回合使用空转录文件表示。单个活动失败时，所属回合不发布转录检查点，已经完成的其他回合继续保留；只有所有活动结果闭合时 Job 才从 `VOICE_READY` 推进到 `TRANSCRIBED`。

`LegacyVoiceExtractorPort` 复用现有 Demo 语音解码器，`LegacyFasterWhisperPort` 复用现有 faster-whisper 适配器。模型配置快照和调用记录由 `FileSystemJobRepository` 写入，应用层负责 claim、配置注册、逐回合发布和语言图重开校验。

## 理解翻译与回合调度接入（02D-3）

02D-3 新增 `application.translation_ports`，将 02C-B 的隐私最小化 `RoundWorkRequest` 交给现有 OpenAI-compatible LLM 适配器，并把结构化返回转换成 `RoundUnderstandingDocument`、`UnderstandingResult` 和 `ModelInvocationRecord`。模型名称、超时和翻译模式来自当前 Job 已登记的 `ModelConfigurationSnapshot`；访问令牌由 provider 边界持有，不进入 Job、任务请求或领域错误。

`LegacyRoundTranslationWorker` 支持旧接口常用的 `translations` 返回形状，同时补齐理解来源、置信度、证据和 warning 字段。`dry_run` 与跳过翻译会生成可审计的占位结果；缺少 provider、服务配置错误、服务繁忙、网络故障和返回格式错误分别映射为稳定的 `RoundTaskError`，原始异常只保留在内存因果链中。重试由既有 `RoundScheduler` 根据任务历史和固定的配置快照执行，不在重试之间静默更换模型或 provider。

`CurrentJobTranslationApplicationService` 只允许从 `CONTEXT_READY` 或 `UNDERSTANDING_TRANSLATING` 启动，先读取已登记配置，再使用 claim-fenced coordinator 和有界并发 scheduler。回合结果按完成顺序立即保存，但最终任务、理解文档、调用记录和 Job 阶段仍按 Demo 回合规范顺序与完整数据图校验；取消、进程恢复、显式重试和逆序完成继续沿用 02C-B 的状态契约。字幕导出、Draft timeline 和真实 Demo/模型双跑仍属于 02D-4 至 02D-5。

## 字幕导出与当前版本产物登记（02D-4）

02D-4 新增 `application.subtitle_ports`，把当前 Job 的 `DraftCommsTimeline` 和
`ReviewedCommsTimeline` 适配为旧字幕策略所需的内存对象。Draft 使用模型翻译，
Reviewed 使用复核后的最终翻译；`asr_original`、翻译文本、玩家名称和队伍信息仍保持
独立。适配过程中可以短暂使用浮点秒调用既有策略，持久化时间始终保留为整数 Demo
微秒。

SRT 时间格式在当前适配层统一使用整数微秒到毫秒的半毫秒向上取整。整场文件使用
`demo_global` timebase；逐回合文件按回合起点归零并登记为 `round_local`。既有
`editing`、`review`、`compact` 和 `debug` 预设，以及 bilingual、compact、zh、
`zh_clean`、original、debug 和 voice activity 格式继续可用。

`CurrentJobSubtitleApplicationService` 负责读取语言图、生成整场和逐回合内容，并通过
`FileSystemJobRepository.publish_final_artifacts` 发布。仓储先校验 manifest CAS、路径和
内容哈希，再写入新文件，最后登记 `FinalArtifactEntry`；已存在的同路径不同内容不会被
覆盖。导出准备或文件写入失败时，既有有效时间线和已登记产物保持可重新打开，新增的
未登记文件会被清理。成功的 Reviewed 导出可将 `FINAL_TIMELINE_READY` 推进到
`SUBTITLES_EXPORTED`；当前阶段不负责视频成片或旧 Job 自动迁移。
