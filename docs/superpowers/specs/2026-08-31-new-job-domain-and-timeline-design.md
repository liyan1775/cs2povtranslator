# 新版 Job 领域模型、统一时间轴与持久化设计

- 状态：用户逐节确认；02A 实施计划与独立强模型复核均已通过，待实施
- 日期：2026-08-31
- 前置：统一工作区与 DemoAsset（Luna-01A 至 01E-B）已经完成
- 后续：阶段 2 领域内核；Web、理解翻译完整实现和 POV 录制仍按后续阶段交付

## 1. 本次范围纠正（最高优先级）

本设计覆盖的“历史 Job”是：**使用新版项目创建的 Job，在程序退出、电脑重启或隔天后，仍能被同一版本的新版程序列出、打开、检查和继续。**

以下两项明确不在当前范围：

1. 不新增旧版 v0.x Job 的扫描、复制或迁移器。已有旧 Job 的 inspect/resume 等兼容行为可以保留，但不继续投入新的迁移界面、批量导入和迁移测试。
2. 不实现不同软件版本之间的 Job Schema 迁移链。序列化文件保留 `schema_version`，但当前只读取当前版本；不匹配时返回稳定、可理解的错误，不尝试改写。

该纠正替代旧路线图中的“任务 1.3：旧 Job 只读导入器”以及“当前阶段提供向后读取测试”的安排。当前优先级是尽快建立正确的新版核心，不为旧版历史包袱或未来兼容框架提前付费。

## 2. 目标与非目标

### 2.1 目标

1. 新版 Job 是可持久化、自描述、同版本可重新打开的工作单元。
2. Demo、回合、语音、ASR、理解翻译、人工复核、字幕、绿幕和未来 POV 视频共用一条明确的 Demo 时间轴。
3. 原始 ASR、模型理解、翻译和人工修改分层保存，任何下游阶段都不覆盖上游事实。
4. 不同回合可以并行翻译、独立落盘、独立失败和独立重试。
5. 上游变更只失效必要的下游结果，避免无意义地重跑 Demo 解析、ASR 或模型请求。
6. 当前无 CS2、无 GPU 的电脑可以完成全部核心领域工作，并合法结束为字幕/覆盖层已完成或等待外部录制。
7. 文件结构和应用服务可直接供未来非程序员 Web 管理界面使用，并能通过真实进程和 Playwright E2E。

### 2.2 非目标

- 旧版 Job 批量迁移或导入；
- 跨版本 Schema 自动升级；
- 当前阶段完成 Web UI、知识审批、模型供应商管理或真实 POV 录制；
- 用数据库保存每个 Job；
- 自研 Demo 解析器、ASR、视频编码器；
- 因本次领域重构顺便重写现有算法。

## 3. 总体数据流

```text
DemoAsset
  -> DemoTimeline（玩家、回合、统一时间锚点）
  -> VoiceActivity / TranscriptCue（原始语音与 ASR）
  -> 按回合并行的 UnderstandingResult
  -> DraftCommsTimeline
  -> 人工复核
  -> ReviewedCommsTimeline
  -> 中英文对照字幕 + 绿幕/透明层 + RenderBundle
  -> 未来可选 POV 录制与成片合成
```

`ReviewedCommsTimeline` 是最终可信的交流内容来源，但不是项目的最终交付物。字幕、绿幕/透明层、RenderBundle 和未来 POV 成片都是从它与统一时间轴派生的最终产物。

## 4. 统一时间轴

### 4.1 规范时间

领域层使用非负整数 `demo_time_us`（微秒）表达 Demo 时间。禁止在新领域对象之间继续传递含义不清的浮点 `start_time` / `end_time`。

```text
DemoTimeUs = int
TimeRange = [start_us, end_us), end_us > start_us
```

采用半开区间可消除相邻 Cue/回合边界的双重归属。序列化和验证必须拒绝负数、布尔值伪装的整数、反向区间和超出合理范围的值。

当前版本把 Demo 时间上限固定为 30 天（`2_592_000_000_000us`），源时钟位置上限固定为有符号 64 位整数最大值。该上限远大于真实比赛，同时能阻止损坏文档构造无限大整数。

### 4.2 来源证据与 TimeAnchor

原始 tick、音频采样点、压缩音频偏移、视频帧号必须保留为来源证据，但不能形成各自独立的“真时间”。它们通过版本化 `TimeAnchor` 映射到 Demo 时间：

```json
{
  "schema_version": 1,
  "anchor_id": "anchor_...",
  "source_clock": "compact_audio_sample",
  "source_start": 240000,
  "source_end": 264000,
  "demo_start_us": 512340000,
  "demo_end_us": 513340000,
  "uncertainty_us": 16000,
  "provenance": "voice-extractor-v1"
}
```

规则：

- tick 映射保留原始 tick 与解析器提供的 tick interval/tick rate；
- 压缩玩家音频是不连续语音包的拼接，必须使用分段锚点，不能使用单一全局 offset；
- 未来视频至少返回实际首尾帧与 Demo 时间锚点；如果观测到漂移，允许使用多段映射；
- 每个锚点记录来源与可选误差，不能把估算值伪装成精确值；
- 同一 `(source_clock, source_stream_id)` 的锚点按源位置排序后，源范围不得重叠，映射到 Demo 的范围也必须严格单调且不得重叠或倒退；
- Round 保存规范时间和可用的原始起止 tick，回合局部时间只由 `demo_time_us - round.start_us` 派生。
- `EXACT` 回合若带 tick，tick 锚点必须精确映射到其 Demo 范围；估算回合必须显式保存边界误差，并在误差内通过映射校验。

### 4.3 导出舍入

内部计算不提前舍入。导出 SRT/ASS 时统一采用：

- `start_ms = floor(start_us / 1000)`；
- `end_ms = ceil(end_us / 1000)`；
- 导出策略负责最短显示时长、重叠和屏幕堆叠，但不能改写源时间对象；
- 视频帧映射使用显式帧率的有理数计算，不把 `29.97` 等帧率先转成低精度小数。

## 5. 领域对象边界

### 5.1 Demo 与回合

- `DemoAssetRef`：工作区资源 ID 和相对 manifest 引用，不含外部绝对路径。
- `DemoTimeline`：Demo 元数据、玩家快照、Round 引用和 TimeAnchor 引用。
- `Round`：稳定 `round_id`、显示序号、规范时间范围、可选 tick、来源、可靠性、边界误差和明确比赛阶段（热身、常规上下半场、加时上下半场或未知）。

`round_id` 不等同于可变的显示序号。人工校正边界时保留 ID；重新解析得到无法对应的新回合时才创建新 ID 并明确失效关联数据。

### 5.2 转录、理解与复核

- `VoiceActivityCue`：说话人、规范时间范围、语音包数量、锚点和误差。
- `TranscriptCue`：稳定 `cue_id`、说话人、可空回合引用、规范时间范围、源时钟范围、ASR 原文、语言、置信信息、VoiceActivity 引用和 ASR 调用引用。生成后不可被翻译阶段覆盖。
- `UnderstandingResult`：`asr_original`、`interpreted_source`、`translated_zh`、依据、置信度、警告和实际模型调用记录引用。
- `RoundTranslationTask`：回合级状态、输入/输出指纹、尝试记录、模型配置快照和结果引用。
- `DraftCommsTimeline`：模型结果的可复核聚合，必须标记为 draft。
- `ReviewDecision`：人工修改的字段、修改前后、理由、时间和原结果引用。
- `ReviewedCommsTimeline`：将 TranscriptCue、UnderstandingResult 与 ReviewDecision 合成的最终可信交流时间线。
- `KnowledgeProposal`：从人工修改产生的候选；本阶段只预留契约，不自动让候选进入全局词典。

未可靠归属回合的 TranscriptCue 使用 `round_id: null` 并进入 `unassigned.jsonl`。无目标队伍语音的正常回合允许产生成功的空 Understanding 文档，不得伪造模型调用。

一个 TranscriptCue 只能覆盖一个连续 Demo 时间范围。若源音频范围跨越不连续锚点，适配器必须拆分 Cue；领域工厂对非连续 `MappedTime` 返回稳定错误，不能只写警告后把静音间隙包入 Cue。

领域层提供可复用聚合校验，验证玩家、回合、VoiceActivity、锚点和 Cue 的引用与时间包含关系。夹具脚本与未来 Job 仓储必须调用同一校验函数，不能各自实现一套规则。

示例必须同时保留三层含义：

```json
{
  "cue_id": "cue_...",
  "asr_original": "be be be",
  "interpreted_source": "B, B, B",
  "translated_zh": "B点，B点，B点",
  "confidence": 0.86,
  "evidence": ["round context", "approved case reference"],
  "review_status": "pending"
}
```

### 5.3 模型配置快照与逐调用记录

`ModelConfigurationSnapshot` 是一个批次共享的非秘密配置：能力类型（ASR 或理解翻译）、服务商类型、endpoint profile ID、模型名、提示模板版本、参数、知识修订、适配器版本和由这些字段规范计算的配置指纹。API Key 只保存秘密引用或“已配置”状态，绝不进入 Job、日志、反馈包和测试夹具。

`ModelInvocationRecord` 表示一次真实调用：调用 ID、共享配置快照 ID、任务/回合 ID、请求内容指纹和响应内容指纹。不同回合共享配置快照，但每次请求拥有自己的 InvocationRecord；不得把不同回合的请求内容指纹错误地塞进同一个共享对象。ASR 调用也使用同一记录契约，TranscriptCue 的调用引用必须能在 Job 中解析。

并发过程中不能因为用户修改默认配置而静默切换服务商或模型。每个 UnderstandingResult 引用实际产生它的 InvocationRecord。

## 6. Job 文件布局

Job 使用按领域、按回合拆分的普通版本化文件，不在每个 Job 内引入数据库：

```text
jobs/<job_id>/
  repository.json
  job.json
  source/
    demo_ref.json
  timeline/
    demo.json
    rounds.json
    time_anchors.jsonl
  voice/
    activities.jsonl
  models/
    snapshots/
      snapshot_<snapshot_id>.json
    invocations/
      task_<task_id>.jsonl
  transcript/
    round_<round_id>.jsonl
    unassigned.jsonl
  understanding/
    round_<round_id>.json
  review/
    revisions/
      review_<review_id>/
        revision.json
        round_<round_id>.json
  tasks/
    round_<round_id>.json
  events/
    job_events.jsonl
    .write.lock
    .writer_claim/              # 仅存在于明确写会话期间
      claim.json
  final/
    timelines/
    subtitles/
    green_screen/
    video/
```

规则：

1. `job.json` 只保存身份、创建/更新时间、当前 Schema、配置快照引用、整体状态摘要、激活的复核版本和产物索引。
2. `job.json` 的状态是快速摘要；阶段、回合任务和文件可以重建摘要。
3. 每回合独立文件允许并行落盘、独立重试和局部诊断；未可靠归属回合的 Cue 进入 `unassigned.jsonl`，不能静默丢弃。
4. 单文件写入使用同目录 staging、完整校验和原子替换。临时文件不成为可见结果。
5. 总状态和事件序列只由 Job 协调器写；回合 worker 只能写自己的任务和结果分片。
6. Job 内不保存 Demo 副本、外部绝对路径、系统临时路径或 API Key。
7. Job 数据使用普通文件以便检查、打包和局部恢复；需要大量查询、审批和修订历史的全局知识库在后续阶段单独使用 SQLite。
8. 每个顶层 JSON 文档都带 `schema_version`；JSONL 的每条独立记录都带 `schema_version`，使单条损坏或不匹配可以精确定位。
9. 所有进入文件名的 Job/Round/Task/Snapshot/Review ID 使用更严格的小写 ASCII 路径 ID（字母、数字、`-`、`_`，最多 64 字符），拒绝尾随点/空格、Windows 设备名和大小写折叠碰撞；不能直接使用玩家名、地图名或其他用户文本。
10. `job_events.jsonl` 是单协调器追加日志；崩溃留下的不完整末行会被报告并隔离，不能让此前完整事件失效。
11. `voice/` 和 `models/` 保存 02A 领域图所引用的语音活动、模型配置快照和逐调用记录；否则重新打开后的 Transcript/Understanding 无法验证来源引用。快照文件名和调用分片文件名只使用领域安全 ID。
12. `.write.lock` 与 `.writer_claim/` 是协调器运行状态，不是业务结果。所有 claim 变更以及“验证 claim 后发布分片”必须位于同一个跨进程独占锁临界区，避免过期接管与旧 writer 写入交错。
13. `repository.json` 是新版仓储原子创建的版本化标记。Job 列表只发现带此标记的直接子目录；只有旧版 `manifest.json` 而没有标记的目录不进入新版列表，也不会被误报为损坏的新版 Job。
14. `job.json.active_review_id` 只引用 `review/revisions/review_<review_id>/revision.json`。每个复核版本保存自己的回合决定分片；完整闭合但未激活的版本是合法历史版本。激活新版本时先完整发布版本目录，并在 POSIX 持久化其父目录，最后才原子更新 Job manifest，不能产生指向缺失版本的 manifest。
15. `jobs/.repository.lock` 只供写操作初始化并锁定，用于串行化合作仓储进程的初始 Job 发布；列表、检查和只读打开在该文件缺失时也不得创建它。

### 6.1 规范内容指纹

所有内容指纹使用 UTF-8 的规范 JSON：键按 Unicode 码点排序、分隔符固定为 `,`/`:`、`ensure_ascii=false`、禁止 NaN/Infinity，再计算小写 SHA-256。指纹由生产代码从领域对象的规范 payload 计算，调用方不能提交一个未验证的任意 64 位字符串冒充内容哈希。

UnderstandingResult 和 DraftCommsTimeline 提供 `content_fingerprint()`。复核合成器必须重新计算并验证来源指纹、确保每个 Draft Cue 恰好一个决定、没有缺失或多余决定、EDIT 实际改变至少一个最终字段，并把排除决定保留在 ReviewedTimeline 中。

DraftCommsTimeline 的 `input_fingerprint` 也必须由生产合成器从按规范回合顺序排列的 RoundUnderstandingDocument 计算；反序列化得到的 Draft 在通过同一生产级聚合校验前不可信。夹具脚本不得单独复制这套逻辑。

## 7. 新版历史 Job 的打开语义

### 7.1 定义和发现

同版本程序启动后扫描当前工作区 `jobs/` 的直接子目录。Job 目录是事实来源；可选的列表索引只是可删除、可重建缓存。

首页/应用服务至少返回：

- Job ID 和显示名；
- 创建/更新时间；
- Demo 显示名、地图和目标 POV；
- 当前阶段和整体状态；
- 成功/失败/等待复核的回合数；
- 可用最终产物；
- 健康状态和可执行建议。

单个 Job 的 manifest 或分片损坏不能让整个列表失败。损坏 Job 仍显示为“需要处理”，并提供稳定错误码。

### 7.2 只读与写操作

- “查看”“检查”“下载已有产物”只读打开，不改文件。
- “继续运行”“重试某回合”“重新翻译”“确认复核”是明确写操作。
- 一个 Job 可以被多个只读客户端打开，但同时只允许一个写入协调器。跨进程 claim 保存随机运行 ID、进程信息和心跳租约；不能仅凭 PID 判断所有权。
- 程序退出后遗留的 `RUNNING` 在只读打开时根据 claim/租约**在内存中显示**为 `INTERRUPTED`，不改盘；只有用户明确继续或修复时，协调器才原子持久化状态转换。
- 当前只接受当前 `schema_version`。不匹配返回 `job_schema_unsupported`，不扫描旧目录、不迁移、不改写。

02A 领域对象内部对版本问题统一返回 `domain_schema_unsupported`。02B Job 仓储按每种文档已声明的 Schema 位置检查原始值：精确整数且不等于当前版本才翻译为 `job_schema_unsupported`；缺失、布尔、字符串、空值等畸形版本属于 `job_manifest_invalid` 或 `job_shard_invalid`。两类映射都保留原始 cause 供诊断，不能递归猜测普通业务字典是否应带 Schema。

### 7.3 工作区范围

程序不扫描整个 C 盘、用户目录或其他工作区来猜测 Job。用户切换工作区时只看到该工作区的 Job。未来若增加备份导入，必须由用户显式选择来源并另行设计；不属于本阶段。

## 8. 状态、并行和恢复

### 8.1 总体状态

```text
CREATED
  -> TIMELINE_READY
  -> VOICE_READY
  -> TRANSCRIBED
  -> CONTEXT_READY
  -> UNDERSTANDING_TRANSLATING
  -> UNDERSTOOD_TRANSLATED
  -> DRAFT_TIMELINE_READY
      -> COMPLETED_DRAFT
      -> REVIEW_PENDING -> REVIEWED
  -> FINAL_TIMELINE_READY
  -> SUBTITLES_EXPORTED
  -> GREEN_SCREEN_RENDERED
  -> COMPLETED_WITHOUT_VIDEO | READY_FOR_RENDER
  -> RENDERING -> VIDEO_READY -> COMPLETED_WITH_VIDEO
```

字幕与覆盖层完成但没有 POV 视频是合法终态。跳过人工复核只能产生带 draft 标识的产物，不能进入 final-reviewed 分支。

### 8.2 回合任务

```text
PENDING -> RUNNING -> SUCCEEDED
                  -> RETRY_WAIT -> RUNNING
                  -> FAILED
                  -> CANCELLED
RUNNING --process exit--> INTERRUPTED -> PENDING/RUNNING
```

调度器遵守模型配置中的并发上限和限流。成功回合立即原子落盘；聚合器按 Round 顺序和 `demo_time_us` 排序，绝不依赖 API 返回顺序。部分完成时可以复核成功回合，但完整正式时间线要求所有目标回合成功或由用户显式排除失败回合。

## 9. 输入指纹与最小失效

每阶段记录规范化输入指纹、输出指纹、开始/结束时间、适配器/工具版本和结构化错误。同样输入重复执行时复用已验证结果。

最小失效规则：

| 变化 | 失效范围 |
|---|---|
| 显示名称/字幕布局 | 字幕与覆盖层导出 |
| 某 Cue 的人工修改 | 该回合 ReviewedTimeline 与相关导出 |
| 翻译模型、提示或知识版本 | Understanding 及其下游 |
| ASR 模型/参数 | Transcript 及其下游 |
| 某回合边界修正 | 受影响 Cue 的回合归属、相关 Understanding/Review/导出 |
| DemoAsset 身份变化 | 全部 Demo 派生数据 |
| POV 录制适配器不可用 | 只阻塞视频分支，不阻塞字幕/覆盖层完成 |

失效操作保留旧产物供诊断，但不能继续把它们标记为当前有效结果。清理和删除是独立、可确认的存储操作。

最终导出同时提供整场和逐回合文件。两者必须来自同一份 ReviewedCommsTimeline 和同一舍入策略；逐回合文件的时间可选择 Demo 全局时间或从零开始的局部时间，但 manifest 必须明确标注 timebase，不能靠文件名猜测。

## 10. 错误与安全边界

至少提供以下稳定错误：

- `job_schema_unsupported`
- `job_manifest_invalid`
- `job_shard_missing`
- `job_shard_invalid`
- `job_write_busy`
- `job_write_interrupted`
- `domain_schema_unsupported`
- `domain_field_invalid`
- `domain_secret_forbidden`
- `domain_private_data_forbidden`
- `domain_fingerprint_mismatch`
- `time_range_invalid`
- `time_anchor_invalid`
- `player_reference_invalid`
- `round_reference_invalid`
- `cue_reference_invalid`
- `cue_time_discontinuous`
- `invocation_reference_invalid`
- `review_decision_invalid`
- `timeline_invalid`
- `round_task_output_mismatch`

所有错误包含中文说明、影响范围和下一步建议。结构化文件、日志和报告只保存工作区相对路径或资源 ID；测试必须扫描 API Key、用户目录和盘符泄露。

## 11. 测试与验收

### 11.1 固定夹具

完整新版端到端验收夹具最终至少包含：

- 三个回合和稳定 Round ID；
- 交叠说话；
- 不连续压缩音频锚点；
- `be be be -> B, B, B -> B点，B点，B点`；
- 回合任务乱序返回和一次可重试失败；
- 一个 Cue 的人工修改；
- 一个未分配回合的 Cue 和一个无语音的正常回合；
- 整场与逐回合字幕聚合；
- 无 CS2/GPU 合法结束。

02A 的匿名领域契约夹具只负责已进入本批次的对象边界：三个回合、交叠说话、理解翻译、人工修改、乱序完成声明、一个未分配 Cue 和一个无语音回合。它不实现任务尝试、可重试失败、调度状态、字幕聚合或视频产物；这些分别在后续状态/调度与导出批次进入真实进程夹具。02A 不得为了满足完整夹具清单而提前实现调度器。

### 11.2 四层门禁

1. 领域契约测试：时间换算、锚点、回合边界、引用完整性、状态转换、输入指纹和失效传播。
2. 真实进程 E2E：实际命令创建三回合 Job，退出，重新启动，列出、打开、继续并校验乱序完成后的聚合顺序。
3. 故障恢复 E2E：写入中止、一个回合失败、单分片损坏和写锁冲突；证明其他回合仍可读且只重跑必要部分。
4. 浏览器 E2E 契约：本阶段固定应用服务与夹具；Web 阶段用 Playwright 真实执行“打开历史 Job—查看回合—继续—检查产物”。

契约测试还必须篡改有效夹具，分别验证：秘密字段、Windows/Unix/UNC 绝对路径、坏引用、被改写的 ASR 原文、伪造指纹、不支持的 schema、倒序 Cue、倒退/重叠锚点都会稳定失败。

CI 至少覆盖 Windows 和 Ubuntu；测试工作区包含中文和空格。领域测试不依赖 CS2、GPU、FFmpeg、Whisper 或真实付费 API。外部工具和真实供应商测试在各自阶段增加，不替代确定性门禁。

## 12. 分阶段落地边界

本设计应拆成可审查的小批次，实施计划另行细化：

1. **领域 Schema 与时间内核**：当前版本的序列化/验证、整数 Demo 时间、TimeAnchor、Round/Transcript/Understanding/Review 契约。
2. **新版 Job 仓储与历史打开**：文件布局、原子写、Job 列表/检查/重新打开、损坏隔离和当前版本拒绝策略。
3. **状态、回合调度与最小失效**：回合分片、并发/重试/中断恢复、指纹和聚合。
4. **现有管线端口化接入**：包装现有解析/语音/ASR/翻译/导出能力，先对金标准证明等价，再替换具体适配器。

每个批次由 Luna 按测试驱动实现，强模型负责计划、架构难点和独立审查；门禁通过后提交 GitHub PR，并按既有授权自动合并。

## 13. 完成定义

本设计对应阶段完成时必须满足：

1. 新版 Job 在退出和重新启动后仍能被同版本程序列出、只读打开和继续。
2. 所有核心对象使用当前版本 Schema；不实现旧版 Job 导入和跨版本迁移。
3. 所有领域时间统一为整数 Demo 微秒，tick/音频/视频通过可审计锚点映射。
4. 原始 ASR、理解、翻译和人工复核不互相覆盖。
5. 回合可并行、乱序完成、局部失败、局部重试和中断恢复。
6. 聚合始终按回合和 Demo 时间排序。
7. 最小失效测试证明修改下游配置不会重跑无关上游。
8. 无 CS2/GPU 可以生成并保存统一时间线、字幕/覆盖层所需契约，并达到合法非视频终态。
9. 真实进程 E2E 和跨平台 CI 通过，且没有秘密、绝对路径或系统盘缓存泄露。
