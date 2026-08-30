# CS2 POV Translator“理解翻译”与模块化重构设计

- 状态：已确认
- 日期：2026-08-30
- 适用范围：下一代 CS2 POV Translator 核心、管理界面、测试体系与可选 POV 录制模块

## 1. 背景与问题

项目最终目标不是单纯翻译若干 ASR 文本，而是从 CS2 POV Demo 生成按回合和 Demo 时间校准、可人工复核的中英文交流时间线，并导出字幕、绿幕素材及可选的带字幕 POV 成片。

现状已具备 Demo 解析、语音解码、ASR、按回合翻译和 SRT 导出，但存在以下结构性问题：

1. ASR 文本被直接当作事实。诸如 `be be be` 可能实际表达 `B B B`，传统逐句翻译会丢失交流意图。
2. 人工复核产生的高价值修正不能系统沉淀为可审批、可追踪的知识。
3. 词典以代码常量为主，缺少非程序员可用的管理和版本生命周期。
4. 模型、Demo、缓存和 Job 产物分别管理，部分模型会默认下载到 C 盘。
5. Demo 在不同 Job 中重复复制或解压，源码目录又混入大量发布包、反馈包和输出。
6. 现有测试以 Python 测试为主，缺少浏览器真实主流程和外部工具实机测试。
7. 项目内部已经实现了一部分外部生态已有的语音和媒体能力，维护边界不清晰。

## 2. 已确认的核心决策

### 2.1 产品输出

产品的核心真相是 `ReviewedCommsTimeline`，而不是某个 SRT 文件。它可以派生：

- 中英双语字幕；
- 中文字幕；
- 原文字幕；
- 调试字幕；
- 每回合可编辑复核文件；
- 每回合绿幕/Comms Overlay；
- 剪辑工具交流时间线；
- 可选的带字幕 POV 视频。

### 2.2 “理解翻译”输出

每条交流必须保留：

- 原始 ASR 文本；
- 解释后的源语言/交流意图；
- 中文翻译；
- 置信度；
- 解释依据和使用的知识；
- 人工复核状态。

系统不能静默覆盖原始 ASR。

### 2.3 重构方式

采用方案 B：模块化核心与端口/适配器架构，渐进迁移，不进行一次性重写。

### 2.4 默认用户界面

- 非程序员：本地 Web 管理界面；
- 自动化、AI、CI 和高级用户：完整 CLI，支持结构化 JSON 输出；
- 稳定的应用 API 位于二者之下；
- 桌面壳可在以后增加，但不拥有业务逻辑。

### 2.5 POV 录制定位

真实 POV 录制是可选能力，不是核心管线的强依赖。无 CS2、无 GPU 的电脑仍然可以完整生成字幕、复核产物、绿幕和 `RenderBundle`。

### 2.6 GitHub 同步与发布

GitHub 仓库是源码、文档、测试和发布历史的远程基准。每个通过验收的实施批次必须形成可追溯提交并同步到已确认的远程仓库；对外发布的新版本还必须创建版本标签。

- 日常实现使用分支和可审查提交，不直接覆盖远程历史；
- 禁止未经明确授权的 force push、历史重写或远程分支删除；
- GitHub Actions 运行不依赖 CS2/GPU 的单元、契约、集成和 Playwright E2E；
- 发布包放入 GitHub Releases，不继续堆放在源码根目录；
- Demo、模型、工作区、API Key、音视频、缓存和其他大型用户资产不得提交；
- 真实 CS2/GPU E2E 的结构化报告可以回传，原始 Demo 和大型视频默认不上载；
- 推送前必须核对远程仓库地址、目标分支、凭据和待提交文件；
- “远程已同步、CI 通过、版本标签可追溯”是发布版本的完成条件。

### 2.7 正式字幕的语音范围

用户选择一个 POV 玩家后，正式字幕默认包含该玩家所属队伍的全部队内交流，以保留完整战术上下文。只导出 POV 玩家本人会丢失队友回应；导出双方所有语音会混淆正式成片。

- 如果玩家或队伍无法可靠识别，必须让用户明确选择；
- 其他检测到的语音可以保留在 debug/review 产物中；
- 高级导出可以选择其他范围，但不能改变默认正式产物的含义。

### 2.8 草稿与正式结果

未经人工复核的结果可以预览和导出，但只能标记为 `draft`，不能出现在 `final` 目录或冒充正式结果。

- 用户可以逐 Cue、整回合或整项确认，不强迫逐条点击；
- 低置信度、发生理解纠错、多人重叠等高风险 Cue 必须突出；
- 完成人工确认后才能生成正式 `final` 字幕、绿幕和成片；
- 跳过复核可以结束为草稿任务，但不能产生影响未来任务的知识；
- 自动化流程只能显式请求 `allow_unreviewed_draft`。

### 2.9 云端模型数据边界

云端模型 API 只接收当前回合理解翻译所需的最小文本和结构化上下文。

允许发送：

- 所选队伍的 ASR 文本；
- `P1 / P2` 等匿名化说话人标签；
- 地图、回合编号和回合阶段；
- 与理解有关的游戏事件；
- 已审批的术语和案例片段。

默认禁止发送：

- 原始 Demo、WAV、视频或绿幕；
- SteamID、真实本地路径和 API Key；
- 对方队伍或与当前翻译无关的文本；
- 未经审批的私人知识和其他 Job 内容。

界面提供请求数据预览。玩家显示名默认匿名化，只有用户主动允许才发送。模型 API 配置档案必须明确数据接收方。

### 2.10 按回合受控并行翻译

回合上下文构建完成后，各回合可以并行调用理解翻译模型。采用有上限、自适应且可断点恢复的并发调度，不使用无上限并发。

- 普通用户选择“稳定 / 平衡 / 快速”，高级用户才设置具体并发值；
- 限流时遵守 `Retry-After`，自动降速并重试；
- 每回合独立保存状态和结果，恢复时只补跑失败或未完成回合；
- 返回可以乱序，最终时间线必须按回合号和 Demo 时间排序；
- 同一 Job 所有回合固定相同的模型、参数、提示词、知识和 schema 版本；
- 某回合失败不抹掉其他成功结果，也不静默切换服务商；
- 已完成回合可以提前进入人工复核；
- 界面显示完成、运行、等待、重试和失败数量。

## 3. 领域数据流

```text
DemoAsset + SelectedPOVPlayer
  → 解析比赛时间线
      - 回合
      - Demo 绝对时间
      - round clock 映射
      - 玩家/队伍
      - 游戏事件
  → 分玩家语音抽取
  → 确定所选 POV 玩家所属队伍
  → ASR
  → TranscriptCue
  → 按回合构建上下文
  → 按回合受控并行理解翻译
      - interpreted_source
      - translated_zh
      - confidence
      - evidence
  → DraftCommsTimeline
      - 可预览/导出明确标记的 draft
  → 人工逐回合或整项复核
  → ReviewedCommsTimeline
  → 时间线组合与冲突处理
  → ExportBundle
      - bilingual / zh / original / debug SRT
      - ASS
      - 每回合复核 JSON/YAML
      - 绿幕/Comms Overlay
      - 剪辑时间线
      - RenderRequest
      - 可选的带字幕 POV MP4
```

人工复核对当前 Job 立即生效，但只有明确审批的知识候选才能影响未来 Job。

## 4. 时间语义

### 4.1 唯一时间真相

Demo 绝对时间或等价的 Demo tick 是内部唯一时间真相。以下时间都必须可由它推导：

- 回合内经过时间；
- round clock；
- 音频局部时间；
- POV 视频局部时间；
- 字幕显示时间。

不允许以某个剪辑视频的局部时间反向覆盖 Demo 时间。

### 4.2 时间锚点

外部音频和视频适配器必须返回时间锚点，例如：

```json
{
  "demo_start_tick": 184320,
  "demo_start_seconds": 2880.0,
  "media_start_seconds": 0.0,
  "tick_rate": 64.0,
  "measured_offset_ms": 42
}
```

所有导出器只消费规范化时间线和锚点，不自行猜测回合起点。

## 5. 分层架构

```text
Web / CLI / API
       │
       ▼
Application Services
       │
       ▼
Domain Core
       │
       ▼
Ports
       │
       ▼
Adapters
```

### 5.1 Domain Core

领域层负责：

- Demo、回合、玩家和交流片段模型；
- 时间换算和时间线组合；
- 理解翻译结果及复核状态；
- 模型 API 配置档案、能力要求和调用快照；
- 知识候选和审批规则；
- 字幕重叠、可读时长和显示策略；
- Job 状态转换规则。

领域层不直接导入 demoparser2、Whisper、数据库、Web 框架、FFmpeg 或 HLAE。

### 5.2 Application Services

应用层负责编排用例：

- 导入或复用 Demo；
- 创建、恢复和取消 Job；
- 运行单个阶段；
- 打开逐回合复核；
- 创建、测试、切换和删除模型 API 配置档案；
- 提交知识候选和审批；
- 导出字幕、绿幕、RenderBundle 和成片；
- 失效并重跑受影响的下游阶段。

### 5.3 核心端口

- `DemoParserPort`
- `VoiceExtractorPort`
- `ASRPort`
- `UnderstandingTranslationPort`
- `ModelProviderProfileRepositoryPort`
- `ModelCapabilityProbePort`
- `SecretStorePort`
- `KnowledgeRepositoryPort`
- `WorkspaceRepositoryPort`
- `SubtitleExporterPort`
- `OverlayRendererPort`
- `POVVideoRendererPort`
- `VideoComposerPort`

端口输入输出必须是版本化领域对象或 manifest，不暴露第三方库的数据结构。

### 5.4 初始适配器选择

| 能力 | 初始选择 | 策略 |
|---|---|---|
| Demo 解析 | demoparser2 | 继续使用，保留端口以应对格式变化 |
| 语音抽取 | 现有 PyOgg + csgo-voice-extractor 候选 | 真实双跑后决定默认值 |
| ASR | faster-whisper | 当前电脑允许 CPU 运行 |
| 理解翻译 | OpenAI-compatible LLM adapter | 供应商配置化，输出结构化结果 |
| 字幕 | 内部时间线策略 + SRT/ASS exporter | SRT 是交换格式，ASS 用于样式和烧录 |
| 视频合成 | FFmpeg | 与游戏录制解耦 |
| POV 录制 | 暂时 disabled | 后续在有 CS2/GPU 的电脑添加适配器 |

### 5.5 模型 API 配置档案

理解翻译使用独立的模型服务配置层。非程序员不需要直接管理散落的 `base_url / api_key / model` 字段，而是管理带友好名称的 `ModelProviderProfile`。

```json
{
  "profile_id": "profile_daily",
  "display_name": "日常翻译",
  "provider_preset": "openai-compatible-preset-id",
  "base_url": "https://api.example.com",
  "model_id": "model-name",
  "secret_ref": "secret://model-api/profile_daily",
  "capabilities": {
    "structured_json": true,
    "model_listing": true
  },
  "enabled": true
}
```

规则：

1. Web 提供常见服务商预设和“自定义 OpenAI-compatible”高级选项；预设注册表可维护，不把易变化的模型 ID 写死在领域逻辑中。
2. 用户粘贴 API Key 后只可测试、替换或删除，界面不再明文回显。
3. API Key 由 `SecretStorePort` 保存。Windows 首选系统凭据存储；工作区、Job、日志、反馈包、配置导出和 GitHub 中只保存 `secret_ref` 或“已配置”状态。
4. 连接测试分别检查鉴权、模型存在性、结构化 JSON 能力和基本响应延迟，并把错误翻译为非程序员可理解的诊断。
5. 服务商支持模型列表接口时生成下拉框；不支持时显示维护的推荐列表，并允许高级用户手动输入模型 ID。
6. 可以保存多个配置档案并选择默认项。新建 Job 可临时选择另一个档案。
7. 切换默认档案只影响新 Job。已有 Job 保存 `ModelInvocationSnapshot`，至少包括 profile ID、服务商类型、模型 ID、参数、提示词版本、输出 schema 版本和知识修订。
8. 重翻译旧 Job 时必须明确选择“原调用快照”或“当前配置档案”，不能静默改变模型。
9. API 故障不能静默切换到其他服务商，避免未经同意改变费用、隐私边界或输出风格。
10. 配置档案可以不带秘密导入/导出；导入后由用户重新绑定 API Key。

## 6. 统一工作区

用户首次运行时选择一个数据根目录。所有大文件和可持久资产跟随该目录，不能静默回落到系统盘。

```text
D:\CS2POV-Workspace\
  workspace.json
  models\
  library\
    demos\
      <asset_hash>\
        source.dem.zst
        metadata.json
  jobs\
    <job_id>\
      job.json
      artifacts\
      review\rounds\
      final\subtitles\
      final\comms_timeline\
      final\green_screen\
      final\video\
  knowledge\
    knowledge.db
    inbox\
    exports\
  cache\
    decompressed_demos\
    audio\
    render\
  render_bundles\
```

规则：

1. Demo 按内容哈希去重。
2. 压缩源文件长期保存；解压后的 `.dem` 属于可清理缓存。
3. Job 引用 DemoAsset，不重复持久复制原始 Demo。
4. Job 的最终输出自包含，便于移动和交付。
5. 路径在 manifest 中尽量保存为工作区相对路径或资源 ID。
6. 模型进入 `models/`，并显式配置 Hugging Face/Whisper 缓存路径。
7. 缓存允许安全清理；Demo、Job、知识和用户复核不能自动删除。
8. API Key 等秘密与工作区资产分离，不能进入反馈包或源码。

## 7. 理解翻译与知识生命周期

### 7.1 结构化结果

建议的逻辑模型：

```json
{
  "cue_id": "cue_...",
  "speaker_id": "7656...",
  "demo_start_seconds": 512.34,
  "demo_end_seconds": 513.08,
  "asr_original": "be be be",
  "interpreted_source": "B, B, B",
  "translated_zh": "B 点，B 点，B 点",
  "confidence": 0.86,
  "evidence": [
    "本回合队友刚报告包点方向",
    "CS2 中重复单字母通常是点位呼叫",
    "知识案例 case_..."
  ],
  "review_status": "pending"
}
```

置信度是复核排序信号，不是隐藏原文或自动审批的理由。

### 7.2 上下文

理解翻译可使用：

- 同回合前后交流；
- 说话人和队伍；
- 地图、回合阶段、存活状态、击杀/下包等事件；
- 已审批的术语和案例；
- ASR 备选结果或词级置信度（若提供）。

它不能把没有依据的推断伪装为原始转录。

### 7.3 知识类型

- `GlossaryEntry`：地图点位、武器、战术短语、玩家习惯叫法；
- `UnderstandingCase`：错误 ASR、解释、翻译及适用条件；
- `KnowledgeProposal`：从人工修改中生成、尚未生效的候选；
- `KnowledgeRevision`：审批、撤销、合并和来源记录；
- `EvalCase`：固定输入和预期结果，用于回归评测。

### 7.4 生命周期

```text
人工修改当前 Cue
  → 立即更新当前 ReviewedCommsTimeline
  → 生成 KnowledgeProposal
  → 非程序员在知识收件箱中查看
  → approve / reject / merge / edit
  → 新 KnowledgeRevision
  → 只影响以后运行或显式重跑的阶段
```

### 7.5 云端请求最小化

`UnderstandingTranslationPort` 接收完整的本地域对象，但云端适配器必须先经过 payload builder，只构造已批准的数据子集。payload 可以在 Web 中预览，并通过测试证明不会包含 Demo 路径、SteamID、音视频引用、秘密或无关队伍文本。

### 7.6 回合级并行调度

每个回合对应一个版本化 `RoundTranslationTask`：

```text
PENDING → RUNNING → SUCCEEDED
                  ↘ RETRYING → RUNNING
                  ↘ FAILED
                  ↘ CANCELLED
```

调度器使用模型配置档案中的并发策略和限流信息。成功结果立即落盘；聚合器只按领域顺序组合，不依赖 API 返回顺序。部分完成时 Web 可以开始复核已成功回合，但正式完整时间线必须满足所有目标回合成功或由用户明确排除失败回合。

## 8. 非程序员管理界面

本地 Web 管理界面至少包含：

1. 首页：新建任务、最近任务、磁盘与依赖状态；
2. Demo 库：导入、去重信息、地图、玩家、时长和引用 Job；
3. Job 详情：阶段进度、可恢复错误、产物和日志；
4. 回合复核：音频试听、原始 ASR、解释、翻译、置信度和依据；
5. 知识收件箱：审批、拒绝、合并和查看影响范围；
6. 本地模型管理：位置、大小、下载状态、删除确认；
7. 模型 API：添加服务商配置、隐藏密钥、测试连接、选择模型、设置默认项和查看 Job 调用快照；
8. 存储管理：耐久资产与可清理缓存分开显示；
9. 导出：字幕、绿幕、时间线、RenderBundle 和可选成片；
10. 系统诊断：依赖、路径、空间、模型 API、外部工具版本和修复建议。

所有重要操作必须有可访问的文本状态，不能只靠颜色或动画表达。

## 9. 外部生态与“避免重复造轮子”

技术审计结论：没有发现成熟工具完整覆盖理解翻译和复核知识链路，但已有工具覆盖大量底层能力。

- [demoparser2](https://github.com/LaihoE/demoparser)：当前解析基础选择合理；
- [csgo-voice-extractor](https://github.com/akiver/csgo-voice-extractor)：提供保留原始时间的分玩家音频，应与现有实现真实对比；
- [CS Demo Manager CLI](https://cs-demo-manager.com/docs/cli)：支持 tick、玩家 POV、HLAE 和 FFmpeg 录制；
- [CS Demo Manager 视频文档](https://cs-demo-manager.com/docs/guides/video)：证明真实 CS2 画面录制可自动化，但受游戏更新和本机环境影响；
- [cs2-dem-renderer](https://github.com/reka-ai/cs2-dem-renderer)：证明按玩家、按回合批量生成同步视频是可行的；
- [DemoTracer](https://github.com/unicbm/demotracer)：适合作为架构和实验参考，但其本地服务器栈与 AGPL 约束不适合作为当前核心依赖。

采用外部工具前必须验证正确性、自动化程度、路径控制、许可、更新风险和非程序员体验。

## 10. 可选 POV 录制与双机工作流

### 10.1 无录制模块时

核心任务可以结束为：

- `COMPLETED_WITHOUT_VIDEO`；或
- `READY_FOR_RENDER`。

它仍然是合法完成状态。

### 10.2 RenderRequest

`RenderRequest` 至少包含：

- schema 版本；
- Demo 内容哈希及文件信息；
- 玩家 SteamID；
- 回合和 tick 范围；
- Demo 时间锚点；
- 分辨率、帧率、声音和摄像机设置；
- 字幕时间线版本；
- 期望输出和校验和。

### 10.3 RenderManifest

录制结果必须返回：

- 实际首尾 tick；
- 视频时长、分辨率、帧率和音轨；
- 实际时间偏移；
- CS2、HLAE、录制适配器和编码器版本；
- 日志、警告和结果校验和。

### 10.4 第一阶段双机方式

```text
当前电脑
  → 导出 render-bundle.zip
  → 手动复制到有 CS2/GPU 的电脑
  → 录制 POV
  → 返回 render-result.zip
  → 当前电脑导入并合成字幕
```

协议稳定后可以增加局域网渲染工作节点，但核心领域模型不改变。

## 11. Job 状态机

```text
CREATED
  → TIMELINE_READY
  → VOICE_READY
  → TRANSCRIBED
  → CONTEXT_READY
  → UNDERSTANDING_TRANSLATING
      - round tasks: PENDING/RUNNING/RETRYING/SUCCEEDED/FAILED
  → UNDERSTOOD_TRANSLATED
  → DRAFT_TIMELINE_READY
      ├→ DRAFT_EXPORTED → COMPLETED_DRAFT
      └→ REVIEW_PENDING → REVIEWED
  → FINAL_TIMELINE_READY
  → SUBTITLES_EXPORTED
  → GREEN_SCREEN_RENDERED
  → COMPLETED_WITHOUT_VIDEO | READY_FOR_RENDER
  → RENDERING
  → VIDEO_READY
  → COMPLETED_WITH_VIDEO
```

规则：

- 阶段幂等；
- 输入、配置、模型和知识修订共同形成内容指纹；
- 上游变化只失效相关下游；
- 失败记录结构化 `JobEvent`；
- 跳过人工复核需要显式记录，且只能结束为 `COMPLETED_DRAFT`；
- `final` 产物必须来自 `REVIEWED`；
- 录制不可用不能让字幕任务失败。

## 12. 验收与测试体系

### 12.1 测试层次

1. 领域单元测试：时间换算、状态机、字幕冲突和知识规则；
2. Schema/契约测试：所有端口、manifest 和版本迁移；
3. 组件集成测试：真实 demoparser2、语音抽取、Whisper、FFmpeg；
4. 浏览器 E2E：Playwright 从导入 Demo 到人工复核和导出；
5. 发布级硬件 E2E：在有 CS2/GPU 的 Windows 机器运行真实录制。

Codex 浏览器工具用于探索性和视觉检查；Playwright 是可重复的主 E2E 框架；Windows 原生边缘流程才使用 Computer Use。

### 12.2 语音抽取门禁

- 玩家与 SteamID 对应正确；
- 分玩家音频保持 Demo 时间；
- 目标时间误差约不超过 100ms；
- 金标准有效交流覆盖不低于旧实现；
- 重叠说话不串人；
- 路径、缓存和错误受工作区控制；
- 失败可回退旧适配器。

### 12.3 POV 录制门禁

- 可非交互录制指定玩家和 tick 范围；
- 画面、声音、分辨率和帧率正确；
- 局部视频时间可稳定映射到 Demo 时间；
- 字幕与语音目标误差约 100–150ms；
- 外部依赖版本不兼容时有明确诊断；
- 修改字幕不重新录制游戏画面。

### 12.4 字幕合成门禁

- 同一 ReviewedCommsTimeline 驱动所有格式；
- 支持 SRT、ASS、绿幕、硬字幕和可编辑字幕；
- 双语布局和最多两层等策略正确；
- 视频音轨、分辨率和帧率满足配置；
- 失败保留原视频和字幕中间产物；
- 通过媒体信息、抽帧和人工视觉检查。

### 12.5 模型 API 配置门禁

- 非程序员可通过预设、粘贴密钥、连接测试和模型下拉框完成配置；
- 支持多个友好名称的档案、默认项和单 Job 选择；
- API Key 不进入工作区、Job、日志、导出、反馈包或 GitHub；
- 连接测试能区分鉴权失败、模型不存在、协议不兼容和网络错误；
- 切换默认项不改变已有 Job；
- 旧 Job 重翻译必须显式选择原快照或新配置；
- 服务商失败时不静默跨服务商回退；
- Playwright 覆盖创建、测试、切换、隐藏密钥和 Job 固定配置。

### 12.6 产品语义、隐私与并行门禁

- 正式字幕默认只包含所选 POV 玩家所属队伍的全部交流；
- 未复核结果只能进入 draft，不能生成 final；
- 整回合和整项确认可用，高风险 Cue 会被单独突出；
- 云端请求 payload 不含 Demo、音视频、SteamID、本地路径、秘密和无关队伍文本；
- 用户可以在发送前查看 payload 摘要；
- 多回合以有上限的并发运行，并正确处理乱序、限流、部分失败、取消和恢复；
- 成功回合不因其他回合失败而重跑；
- 聚合结果始终按回合和 Demo 时间排序；
- 并行任务使用同一个模型调用快照，不静默切换服务商。

## 13. 迁移与回滚

1. 先确定唯一可信源码基线，建立 Git 和基线标签；
2. 确认 GitHub 远程仓库和默认分支，将基线安全推送并验证远程可检出；
3. 旧 Job、Demo 和字幕只读导入，不原地改写；
4. 新领域对象和 manifest 全部带 schema 版本；
5. 先让新核心调用旧适配器达到功能等价，再逐个替换；
6. 新旧管线对金标准 Demo 双跑；
7. 每个新适配器至少保留一个稳定周期的旧实现回退；
8. 数据库迁移前备份，失败后继续读取旧版本；
9. 每个 Job 记录代码、模型、知识和工具版本；
10. 历史上存放在源码目录中的 API Key 不迁移，并应更换；
11. 每个可交付批次推送到 GitHub 后再视为完成，本地回滚与远程标签保持一致。

## 14. 非目标

本轮重构不以以下事项为必要条件：

- 自研新的 CS2 Demo 二进制解析器；
- 自研完整视频编码器；
- 在无 GPU 电脑运行真实 CS2 录制；
- 第一版就实现局域网渲染服务；
- 自动把未经审批的人工修改推广到所有任务；
- 一次性迁移或删除所有旧发布包和输出。

## 15. 完成定义

架构迁移完成需满足：

- 非程序员可以通过 Web 完成核心字幕工作流；
- Demo、模型、缓存和产物由统一工作区管理；
- 旧 Job 可导入或查看；
- 代表性 Demo 的输出质量不低于旧版本；
- 理解翻译可解释、可复核、可沉淀；
- 非程序员可在 Web 中安全添加、测试和切换模型 API，已有 Job 保持可复现；
- Playwright 覆盖真实浏览器主流程；
- 无 CS2 机器可完成字幕、绿幕和 RenderBundle；
- 真实录制以后能以适配器形式加入；
- 新实现失败时有明确回退路径；
- 已验收批次同步到 GitHub，CI 结果可查；
- 发布版本具有不可混淆的 Git 标签和 GitHub Release 记录。

## 16. 尚未冻结的实现选择

以下选择必须在实施阶段通过小型验证后确定：

- 本地 Web 前端的具体框架；
- API/Web 服务框架及打包方式；
- csgo-voice-extractor 是否替代现有语音解码；
- CS Demo Manager CLI、独立 HLAE 适配器或其他 POV 录制后端；
- 局域网渲染节点是否值得实现；
- 不同机器上的 ASR 模型和性能档位。

这些未决项由端口隔离，不阻塞领域模型、工作区和复核知识链路建设。
