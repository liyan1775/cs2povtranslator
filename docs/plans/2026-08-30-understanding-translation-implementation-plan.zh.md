# CS2 POV Translator 模块化重构实施计划

- 状态：待执行
- 日期：2026-08-30
- 依据：[架构设计](2026-08-30-understanding-translation-architecture-design.zh.md)
- 执行原则：测试先行、渐进迁移、每阶段可回滚、不以真实 POV 录制阻塞核心系统

## 1. 执行约束

1. 实施前必须先确定唯一源码基线。当前外层源码为 v0.8.8，嵌套目录为 v0.9.2，同时存在直至 v0.9.8 的发布压缩包，不能直接假设任一目录就是最终真相。
2. 不删除、覆盖或批量移动旧源码、Demo、反馈包、发布包和 Job。目录整理需单独确认目标并保留清单。
3. 不读取或复制 `apikey.txt` 内容。正式实施时先迁移秘密管理并提示更换历史密钥。
4. 每个阶段都必须先写失败测试或验收脚本，再实现最小变更。
5. 每个阶段结束前运行相关单元、集成和 E2E 验证，并记录证据。
6. 真实 CS2/HLAE 录制属于最后的独立模块；前置阶段只能定义并验证其契约。

## 2. 阶段总览

| 阶段 | 目标 | 是否需要 CS2/GPU |
|---|---|---|
| 0 | 确定基线、建立版本控制、GitHub 同步和金标准 | 否 |
| 1 | 统一工作区与资产管理 | 否 |
| 2 | 版本化领域模型和统一时间轴 | 否 |
| 3 | 端口/适配器与旧管线兼容迁移 | 否 |
| 4 | 语音抽取技术验证与选择 | 否 |
| 5 | 理解翻译、人工复核和知识库 | 否 |
| 6 | 本地 API/Web 管理界面 | 否 |
| 7 | Playwright 真实浏览器 E2E | 否 |
| 8 | 字幕、绿幕、RenderBundle 与视频合成 | 否 |
| 9 | 真实 POV 录制适配器与硬件 E2E | 是 |

## 3. 阶段 0：可信基线与安全边界

### 任务 0.1：源码基线审计

检查：

- 外层与嵌套源码的版本、文件差异、测试和文档；
- v0.9.3–v0.9.8 发布包中的版本元数据；
- 哪一份包含用户认可的最新功能和修复；
- 工作目录是否存在未保存的用户修改。

产物：

- `docs/baseline/BASELINE_AUDIT.zh.md`
- 候选源码清单和文件哈希；
- 明确的 canonical source 选择建议。

门禁：用户确认唯一基线后才能进入任务 0.2。

### 任务 0.2：建立 Git 与目录边界

在已确认的 canonical source 上：

- 初始化或恢复 Git；
- 创建基线提交和版本标签；
- 更新 `.gitignore`，排除秘密、工作区、大模型、Demo、音视频、输出和缓存；
- 不自动提交任何 API Key、Demo 或用户产物。

验证：

- `git status` 只显示预期源码和文档；
- 秘密扫描不发现 API Key；
- 基线标签可检出并运行。

回滚：保留原目录只读副本或原压缩包，不修改它们。

### 任务 0.3：建立 GitHub 远程基准与 CI

在任何远程写入前先确认：

- GitHub 仓库的准确 URL 和所有者；
- 默认分支和目标分支；
- 当前凭据具备的最小权限；
- 远程是否已有不可覆盖的提交、标签或 Release；
- 本地待提交文件中不含 Demo、模型、工作区、密钥、音视频和缓存。

确认后：

- 配置并核验 `origin`；
- 安全推送 canonical baseline，不 force push；
- 建立适合批次开发的分支/审查流程；
- 增加 GitHub Actions，运行无需 CS2/GPU 的测试与 Playwright E2E；
- 为发布包建立 GitHub Releases 流程；
- 约定语义清晰的版本标签和变更说明；
- 将硬件 E2E 的小型结构化报告作为发布证据，默认不上传原始 Demo 和大型视频。

验证：

- 远程提交与本地预期 commit 一致；
- 新环境可以从 GitHub 检出并运行基础验证；
- CI 对故意构造的失败测试会失败，对基线测试会通过；
- `.gitignore` 和秘密扫描能阻止敏感或大型资产误提交；
- 发布标签能够唯一定位源码，Release 资产与标签一致。

回滚：删除错误的本地 remote 配置不影响源码；若远程已有冲突，停止推送并先人工决定合并方式，不改写远程历史。

### 任务 0.4：建立金标准与测试清单

建立最少三类测试素材：

1. 小型、可公开或用户明确授权的 Demo 夹具；
2. 真实但不入库的本地代表性 Demo；
3. 合成音频、合成视频和结构化时间线夹具。

建立 `tests/golden/` manifest，记录：

- 输入哈希；
- 预期回合和玩家；
- 关键语音起止；
- 典型理解翻译案例，如 `be be be → B, B, B`；
- 旧版本字幕结果和已知缺陷。

门禁：必须能稳定重放旧版本基线测试。

## 4. 阶段 1：统一工作区

### 任务 1.1：Workspace 配置与路径策略

建议新增：

```text
src/cs2pov/workspace/
  models.py
  paths.py
  service.py
  errors.py
```

先写测试覆盖：

- 用户选择任意工作区根目录；
- 路径全部规范化为资源 ID 或相对路径；
- 中文路径；
- 工作区不可写、空间不足和目录丢失；
- 禁止未配置时静默写入系统盘。

实现：

- `workspace.json`；
- 模型、Demo、Job、知识、缓存和 RenderBundle 目录；
- 对 Hugging Face、Whisper 和临时目录设置显式缓存路径；
- CLI/API 的 workspace 初始化与诊断用例。

### 任务 1.2：DemoAsset 导入与哈希去重

先写测试覆盖：

- 同一 Demo 重复导入只产生一个资产；
- `.dem.zst` 保存压缩源，解压文件进入缓存；
- Job 引用资产而不是复制原始 Demo；
- 中断后可恢复；
- 哈希不一致时拒绝复用。

建议新增：

```text
src/cs2pov/domain/assets.py
src/cs2pov/application/import_demo.py
src/cs2pov/workspace/demo_repository.py
```

### 任务 1.3：旧 Job 只读导入器

实现旧目录扫描、manifest 解析和迁移报告，但不改写旧目录。

产物包含：

- 可导入项；
- 缺失或不一致文件；
- 旧绝对路径到新资源 ID 的映射；
- 冲突和人工处理建议。

门禁：对同一旧 Job 重复导入必须幂等。

## 5. 阶段 2：领域模型与统一时间轴

### 任务 2.1：版本化 Schema

建议拆分：

```text
src/cs2pov/domain/demo.py
src/cs2pov/domain/timeline.py
src/cs2pov/domain/comms.py
src/cs2pov/domain/knowledge.py
src/cs2pov/domain/rendering.py
src/cs2pov/domain/jobs.py
```

核心对象：

- `DemoAsset`
- `Round`
- `TimeAnchor`
- `TranscriptCue`
- `UnderstandingResult`
- `ModelProviderProfile`
- `SecretRef`
- `ModelInvocationSnapshot`
- `RoundTranslationTask`
- `ReviewGate`
- `DraftCommsTimeline`
- `ReviewedCommsTimeline`
- `KnowledgeProposal`
- `RenderRequest`
- `RenderManifest`

每个序列化格式包含 `schema_version`，并有向后读取测试。

### 任务 2.2：时间换算

测试先覆盖：

- tick ↔ Demo seconds；
- Demo seconds ↔ 回合局部时间；
- 音频局部时间 ↔ Demo 时间；
- 视频局部时间 ↔ Demo 时间；
- freeze time、伪回合、回合重启和越界 Cue；
- 毫秒舍入与 SRT/ASS 输出。

门禁：领域层时间测试不依赖 FFmpeg、Whisper 或 Web。

### 任务 2.3：Job 状态机和失效传播

实现：

- 允许的状态转换；
- 阶段输入指纹；
- 上游变化后的最小下游失效范围；
- `COMPLETED_WITHOUT_VIDEO` 与 `READY_FOR_RENDER` 合法终态；
- 未复核分支只能进入 `DRAFT_EXPORTED / COMPLETED_DRAFT`；
- 只有 `REVIEWED` 可以进入 `FINAL_TIMELINE_READY`；
- 回合翻译任务具有独立状态和检查点；
- 结构化 `JobEvent` 和失败恢复信息。

## 6. 阶段 3：端口/适配器与兼容迁移

### 任务 3.1：定义端口契约

建议新增：

```text
src/cs2pov/ports/
  demo_parser.py
  voice_extractor.py
  asr.py
  understanding_translation.py
  model_provider_profiles.py
  model_capability_probe.py
  secret_store.py
  knowledge_repository.py
  subtitle_exporter.py
  overlay_renderer.py
  pov_video_renderer.py
  video_composer.py
```

契约测试必须验证：

- 输入输出类型；
- 可取消和超时；
- 进度事件；
- 错误分类；
- 工作区路径约束；
- 工具和模型版本记录。

### 任务 3.2：包装旧实现

先将当前实现包装为：

- `LegacyDemoparserAdapter`
- `LegacyPyOggVoiceExtractor`
- `FasterWhisperAdapter`
- `LegacyTranslationAdapter`
- `LegacySubtitleExporter`

禁止此阶段顺便重写算法。目标是新应用层能生成与旧管线等价的产物。

### 任务 3.3：新旧双跑比较

为金标准 Demo 生成结构化比较报告：

- 回合边界；
- 玩家身份；
- 语音活动；
- ASR 片段；
- 翻译；
- SRT Cue 数量和时间；
- 已知差异与是否接受。

门禁：关键功能无未解释回归后，才允许 UI 和知识功能建立在新核心上。

## 7. 阶段 4：语音抽取技术验证

### 任务 4.1：csgo-voice-extractor 适配器

实现候选适配器，使用 `split-full`，并输出规范化玩家音频和时间锚点。

必须覆盖：

- 多玩家；
- 重叠语音；
- 中文工作区路径到 ASCII 暂存路径；
- 工具缺失和版本不兼容；
- 输出不完整；
- 取消与清理。

### 任务 4.2：真实对照评测

至少三个代表性 Demo 双跑现有 PyOgg 与候选适配器。

报告：

- 玩家映射；
- 非静音区间；
- 关键交流覆盖；
- 时间误差；
- 运行时间和磁盘使用；
- 失败诊断；
- 许可和分发方式。

决策：

- 通过：候选成为默认，旧实现保留回退；
- 部分通过：按 Demo 类型选择；
- 不通过：保留端口和评测，不替换旧实现。

## 8. 阶段 5：理解翻译、复核与知识库

### 任务 5.1：模型 API 配置档案与秘密存储

建议新增：

```text
src/cs2pov/model_providers/
  profiles.py
  presets.py
  capability_probe.py
  service.py
src/cs2pov/security/
  secret_store.py
  windows_credential_store.py
```

先写测试覆盖：

- 创建、更新、禁用和删除多个友好名称的配置档案；
- 服务商预设和自定义 OpenAI-compatible 配置；
- API Key 只进入 `SecretStorePort`，序列化结果只有 `secret_ref`；
- 配置、Job、日志、反馈包和导出中不能出现密钥；
- 连接测试区分鉴权、模型、协议和网络错误；
- 支持时自动列出模型，不支持时安全使用推荐列表或手动输入；
- 默认配置只影响新 Job；
- Job 创建时生成不可变 `ModelInvocationSnapshot`；
- 普通用户可选择“稳定 / 平衡 / 快速”并发策略，高级用户可设置上限；
- 重翻译显式选择原快照或新档案；
- 服务商失败时不静默使用另一档案；
- 不带秘密的配置导入/导出及重新绑定。

实现非程序员流程：选择预设、粘贴一次密钥、测试连接、选择模型、命名并设为默认。Windows 第一版接入系统凭据存储，保留跨平台 `SecretStorePort`。

门禁：秘密扫描、profile 契约测试和连接测试全部通过后，理解翻译服务才允许改为消费 profile ID。

### 任务 5.2：理解翻译结构化契约

先写测试：

- 原始 ASR 永不丢失；
- 结构化输出缺字段时拒绝或安全降级；
- `be be be` 类案例可借助上下文解释为字母/点位；
- 低置信度进入优先复核；
- 没有足够依据时保留不确定性；
- 知识版本进入输入指纹；
- 正式处理范围默认是所选 POV 玩家所属队伍；
- 云端 payload 只包含匿名化的同回合必要文本、必要事件和已审批知识；
- payload 不包含 Demo、音视频、SteamID、本地路径、秘密、无关队伍文本和未经审批知识；
- 用户可在首次使用和高级诊断中预览 payload 摘要。

实现 `UnderstandingTranslationPort` 和 LLM adapter，要求严格结构化结果。

### 任务 5.3：回合级并行调度与断点恢复

先写测试覆盖：

- 多回合在配置上限内并发运行；
- 响应乱序时按回合号和 Demo 时间稳定聚合；
- `Retry-After`、速率限制、指数退避和自动降速；
- 单回合失败不丢失其他成功结果；
- 成功回合立即保存，恢复时只补跑失败或未完成回合；
- 取消后保留已成功检查点；
- 同一 Job 所有回合使用同一 `ModelInvocationSnapshot`；
- 失败时不静默切换模型或服务商；
- 已完成回合可提前复核；
- UI 进度可区分完成、运行、等待、重试和失败。

实现有上限的 worker pool、服务商级限流器、回合任务仓储和确定性聚合器。普通用户使用“稳定 / 平衡 / 快速”，具体默认值通过真实 API 验证确定。

门禁：模拟服务商必须验证乱序、429、超时、部分失败、取消和恢复；真实 API 小规模验证确认不会违反服务商限制。

### 任务 5.4：SQLite 知识存储

建议新增：

```text
src/cs2pov/knowledge/
  repository.py
  migrations/
  proposal_service.py
  retrieval.py
  export_import.py
```

表的逻辑范围：

- glossary entries；
- understanding cases；
- proposals；
- revisions；
- approvals/audit events；
- eval cases。

测试审批、撤销、合并、重复候选、来源追踪和备份恢复。

### 任务 5.5：复核写回、草稿/正式门禁与候选生成

人工修改必须：

1. 立即更新当前 Job；
2. 保存修改前后差异；
3. 可选生成候选；
4. 不经审批不影响未来 Job；
5. 审批后只影响新任务或显式重跑。

同时实现：

- 未复核任务只能导出明确标记的 draft；
- 用户可逐 Cue、整回合或整项确认；
- 低置信度、理解纠错和多人重叠 Cue 突出显示；
- 只有 `REVIEWED` 可以生成 `final`；
- 跳过复核不生成可影响未来任务的知识。

### 任务 5.6：评测集

把金标准和已审批案例转换为可重复 eval，分别衡量：

- 意图解释正确率；
- 术语翻译；
- 原文保真；
- 无依据臆测；
- 人工复核修改率。

## 9. 阶段 6：本地 API 和 Web 管理界面

### 任务 6.1：框架小型验证

在冻结框架前实现两个最小原型：

- Demo/Job 列表和实时状态；
- 单回合复核表单及音频播放。

评价：

- Playwright 可测试性；
- Windows 打包和启动；
- Python 核心集成；
- 非程序员交互；
- 可访问性；
- 前端构建复杂度。

候选框架选择必须记录 ADR，不以个人偏好直接冻结。

### 任务 6.2：稳定应用 API

API 覆盖：

- workspace 初始化和诊断；
- 模型 API 配置档案、连接测试、模型列表和默认项；
- 云端 payload 预览和匿名化设置；
- Demo 导入和查询；
- Job 创建、恢复、取消和事件流；
- 回合复核；
- 草稿导出、整回合/整项确认和正式结果门禁；
- 知识候选审批；
- 模型和缓存管理；
- 导出与 RenderBundle。

CLI 调用相同应用服务，并提供 `--json`，不能另建一套业务流程。

### 任务 6.3：非程序员主界面

依次交付：

1. 初始化向导；
2. Demo 库；
3. Job 创建和进度；
4. 回合复核；
5. 模型 API 配置与切换；
6. 知识收件箱；
7. 本地模型与存储；
8. 导出和错误恢复。

每个页面完成时同步增加 Playwright 页面对象和可访问选择器。

## 10. 阶段 7：Playwright 端到端体系

### 任务 7.1：项目固定的 Playwright

不要依赖机器上已有的浏览器缓存作为正式依赖。项目固定 Node/Playwright 版本，并提供：

- 配置；
- 浏览器安装/检测脚本；
- 测试数据目录；
- trace、截图、视频和失败产物；
- Windows 本地运行入口。

### 任务 7.2：日常真实 E2E

至少覆盖：

```text
首次选择工作区
→ 添加模型 API 配置并测试连接
→ 选择默认模型
→ 导入 Demo
→ 选择 POV 玩家并确认所属队伍
→ 创建 Job
→ 真实解析和语音抽取
→ CPU ASR
→ 理解翻译
→ 观察多回合并行、乱序完成和进度计数
→ 确认 Job 记录的模型调用快照
→ 检查云端 payload 不含受禁止数据
→ 回合复核
→ 验证未确认时只能导出 draft
→ 整项确认后生成 final
→ 产生并审批一个知识候选
→ 导出字幕/绿幕/RenderBundle
→ 下载并检查产物
```

外部 LLM 可以分为稳定的契约 E2E 和有预算控制的真实供应商 E2E，但二者都需要浏览器主流程，不得只测 API。

### 任务 7.3：失败恢复 E2E

覆盖：

- 磁盘空间不足；
- 外部工具缺失；
- ASR 中断后恢复；
- LLM 超时；
- API Key 无效、模型不存在和服务商不可用；
- 回合翻译部分失败、429 限流、取消和断点恢复；
- 切换默认模型后旧 Job 的调用快照保持不变；
- 浏览器刷新；
- Job 取消；
- 旧 Job 导入；
- 清理缓存不删除耐久资产。

## 11. 阶段 8：字幕、绿幕、RenderBundle 与合成

### 任务 8.1：统一导出器

所有格式只消费同一 `ReviewedCommsTimeline`：

- SRT；
- ASS；
- 原文/中文/双语/debug；
- Comms Overlay；
- 剪辑时间线。

加入布局快照、时间线 golden 和字体缺失测试。

### 任务 8.2：FFmpeg 合成

使用合成或预录测试视频验证：

- 软字幕封装；
- 硬字幕烧录；
- 音轨保留；
- 分辨率/帧率策略；
- 失败恢复；
- 修改字幕后只重新合成。

验收使用 ffprobe、关键帧抽图和视觉检查。

### 任务 8.3：RenderBundle

实现：

- `render-request.json`；
- Demo 或 Demo 引用；
- ASS/SRT；
- checksums；
- 导出 ZIP；
- `render-result.zip` 导入；
- RenderManifest 校验；
- 时间偏移应用和最终合成。

此阶段使用模拟/预录的 RenderResult 完成全流程，不需要 CS2。

## 12. 阶段 9：真实 POV 录制模块

此阶段在安装 CS2 且有 RX 7650 GRE 的 Windows 机器执行。

### 任务 9.1：环境 doctor

检测：

- Steam 和 CS2；
- HLAE/CS Demo Manager/FFmpeg；
- GPU 和编码器；
- 磁盘空间；
- Basic Latin 暂存路径；
- 工具版本兼容；
- `-insecure` 安全启动条件。

### 任务 9.2：录制后端技术验证

优先验证 CS Demo Manager CLI；若其数据库或自动化依赖不适合产品，再验证独立 HLAE 适配器。

使用一个完整回合验证：

- 指定玩家；
- 起止 tick；
- 画面与音频；
- 首帧时间锚点；
- 进度和取消；
- CS2 更新导致的不兼容错误；
- 输出完全位于工作区。

### 任务 9.3：发布级硬件 E2E

```text
Playwright 在 Web 发起任务
→ 导出或发送 RenderRequest
→ 真实启动 CS2/HLAE
→ 录制指定玩家回合
→ 返回 RenderManifest
→ 合成双语字幕
→ ffprobe + 抽帧 + 人工视觉验收
```

硬件 E2E 作为定期和发布门禁，不要求每次代码提交运行。

### 任务 9.4：是否建设局域网渲染节点

收集手动 RenderBundle 的实际使用数据后再决定。只有满足以下任一条件才实施：

- 传输频率高且手动操作明显成为主要成本；
- 需要任务队列或无人值守批量录制；
- 两台机器网络和安全边界稳定。

## 13. 每阶段通用完成门禁

每个阶段必须同时满足：

1. 新增行为有自动化测试；
2. 相关测试从失败变为通过；
3. 既有基线无未解释回归；
4. 路径和秘密检查通过；
5. 错误可诊断；
6. 文档和非程序员提示同步更新；
7. 有明确回滚方式；
8. 代码审查完成；
9. 完成前执行独立验证命令并保存结果；
10. 已验收批次形成可读提交并推送到已确认的 GitHub 分支；
11. GitHub CI 通过；对外发布时版本标签和 GitHub Release 已创建并核验。

## 14. 推荐的实施批次

为控制风险，建议按以下批次交付，而不是以一个超大版本完成：

- 批次 A：阶段 0–2，建立可信基线、GitHub 远程基准、工作区和领域时间轴；
- 批次 B：阶段 3–4，兼容旧管线并完成语音抽取验证；
- 批次 C：阶段 5，交付非程序员模型 API 配置、最小化云端 payload、回合并行理解翻译、草稿/正式复核门禁与知识闭环；
- 批次 D：阶段 6–7，交付非程序员 Web 与浏览器 E2E；
- 批次 E：阶段 8，交付绿幕、RenderBundle 和通用合成；
- 批次 F：阶段 9，在 GPU 机器交付真实 POV 录制。

每个批次都应是用户可运行、可回滚的版本。

## 15. 第一批执行前的明确决策

真正开始实施前需要先解决两个阻塞项：确定 canonical source，并确认要同步的 GitHub 仓库准确 URL、默认分支和访问权限。推荐通过审计比较外层 v0.8.8、嵌套 v0.9.2 和 v0.9.8 发布包，而不是根据版本号直接猜测；也不能仅凭网上搜索结果假定远程仓库目标。

基线和远程目标确认后，从阶段 0 开始执行；不得先跳到 Web UI、理解翻译或视频录制。每个已验收批次只有在本地验证、GitHub 同步和 CI 全部完成后才算交付。
