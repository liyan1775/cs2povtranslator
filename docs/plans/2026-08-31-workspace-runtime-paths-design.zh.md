# Luna-01D：工作区运行时与旧管线路径接入设计

- 日期：2026-08-31
- 状态：已批准；Luna-01D-A 已实施并完成本地审查，Luna-01D-B 待实施
- 所属阶段：阶段 1.1「Workspace 配置与路径策略」收尾
- 前置实现：Luna-01A `WorkspacePaths`、Luna-01B `WorkspaceService`、Luna-01C 工作区选择与用户入口
- 实施模型：Luna
- 审查模型：主任务强模型
- 交付拆分：Luna-01D-A、Luna-01D-B 两个独立 PR

## 1. 背景与目标

Luna-01A 至 01C 已经建立工作区目录模型、初始化/诊断服务和“当前工作区”路径指针，但旧 v0.9.8 管线仍没有消费这些能力。当前实现仍存在多套互不一致的路径决定机制：

- `PipelineConfig.output_root` 和 `cs2pov run --output` 默认写到当前目录下的 `output/`；
- 文本向导再次询问输出根目录；
- Whisper 缓存路径来自旧 `~/.cs2pov/config.json`、命令行参数、环境变量或 Hugging Face 系统默认值；
- `FasterWhisperAdapter` 会用 `os.environ.setdefault()` 修改进程全局环境；
- 模型管理器会扫描用户主目录下的 Hugging Face 默认缓存；
- Demo 会被复制或解压到旧 Job 输入目录；
- 转录临时音频位于 Job 的耐久 artifacts 目录中；
- 旧 Job 工具依赖用户手工输入任意目录。

因此，“界面显示已选择工作区”还不等于真实数据跟随工作区。本设计的目标是让所有新写入位置由一次解析出的工作区运行时统一决定，并保留边界明确、可观察、限时的旧输出兼容能力。

本设计贯彻以下硬约束：

1. 没有健康的当前工作区时，不得处理 Demo、创建/恢复 Job、下载或加载新模型；
2. 不得静默退回当前目录、源码目录、用户主目录或系统盘默认缓存；
3. 模型缓存和通用临时文件永远跟随当前工作区，不能被旧 `--output` 改写；
4. 外部 Demo 源只读，本次任务的副本、解压文件和产物全部进入允许的目标；
5. 运行时路径不可变，启动后的任务不受后来切换工作区影响；
6. 当前阶段不提前实现 DemoAsset 哈希库、旧 Job 导入器或新版 Job 状态机。

## 2. 方案选择与交付拆分

### 2.1 采用方案：统一 `WorkspaceRuntime`

由应用入口解析当前工作区并生成不可变 `WorkspaceRuntime`。CLI、文本向导和未来 Web/API 都消费同一运行时；Pipeline、模型管理和适配器只接收已经解析好的显式路径，不再自行猜测默认目录。

```text
CLI / 文本向导 / 未来 Web API
                │
                ▼
      WorkspaceRuntimeResolver
                │
       读取当前工作区路径指针
                │
       校验配置、布局、可写性、空间
                │
                ▼
      immutable WorkspaceRuntime
          │                 │
          ▼                 ▼
  Pipeline / Job       模型管理 / Adapters
```

优点：

- 路径策略只有一个真相源；
- Web/API 不需要重新实现路径规则；
- 可在创建任何大文件前执行一致门禁；
- 适合未来同一工作区内的多 Job 和回合级并行；
- 旧兼容只停留在应用入口，不污染领域与适配器。

### 2.2 不采用：在各旧命令内分别替换默认路径

这种方式改动较小，但 CLI、向导、模型管理器、Pipeline 和适配器会继续分别拥有路径政策。未来接入 Web 时需要再次迁移，并且很难证明没有遗漏 C 盘写入点。

### 2.3 不采用：立即重写完整 DemoAsset、JobRepository 与新版 Pipeline

这会提前吞并阶段 1.2、1.3 和阶段 2 的领域状态机，单个任务改动过大，无法用小批次审查，也会让临时兼容结构变成新架构的一部分。

### 2.4 两个 PR

Luna-01D-A 负责：

- 统一运行时解析器和工作区硬门禁；
- Whisper、Hugging Face 与模型管理路径；
- 移除适配器对全局环境的修改；
- 旧模型缓存的只读检测和弃用提示；
- 模型路径真实子进程 E2E。

Luna-01D-B 负责：

- `run`、文本向导、Pipeline、Job 恢复和输出工具接入运行时；
- 默认 Job、Demo 准备、临时音频和最终产物路径；
- 显式外部 `--output` 与旧 Job 的过渡兼容；
- Job 路径安全与冲突处理；
- 处理流程真实子进程文件系统 E2E。

两个 PR 分别由 Luna 实现、主任务强模型审查，并在用户明确确认后合并。

## 3. 运行时组件

### 3.1 `WorkspaceRuntimeResolver`

建议位于应用层。它依赖 01C 已有的 `WorkspaceSelectionPort` 和 01B 的 `WorkspaceService`，负责：

1. 读取当前选择；
2. 没有选择时返回稳定错误；
3. 对选中根目录执行只读诊断；
4. 要写入时要求诊断健康；
5. 生成不可变运行时快照。

解析器不解析 CLI、不打印、不下载模型、不创建 Job。只读帮助、`doctor` 和工作区管理命令不需要取得可写运行时；所有资产写操作都必须取得。

建议公开两类意图，避免调用方自行决定检查强度：

```python
resolve_for_read() -> WorkspaceRuntime
resolve_for_write() -> WorkspaceRuntime
```

若实际实现证明只需一个严格入口，可以只保留 `resolve_for_write()`；不得通过布尔参数堆叠模糊语义。

### 3.2 `WorkspaceRuntime`

运行时是冻结的数据对象，至少持有：

- 已规范化的 `WorkspacePaths`；
- 本次启动时的选择快照；
- Job 根目录；
- Whisper、Hugging Face、音频、渲染和通用临时目录；
- 供外部子进程复制使用的环境覆盖映射；
- 路径政策版本，便于写入 Job manifest。

`WorkspaceRuntime` 不持有 API Key，不写文件，不读取旧全局配置。所有返回路径都必须来自 `WorkspacePaths`。

任务开始后，即使用户在另一个进程切换当前工作区，已启动任务也继续使用原快照；新任务才解析新选择。

### 3.3 环境变量与并行安全

`WorkspacePaths.environment_overrides()` 只返回建议映射，继续保持无副作用。

- faster-whisper 使用显式 `download_root`；
- 能接收 `cache_dir`、`temp_dir` 或输出路径的库必须显式传参；
- 外部子进程通过 `subprocess` 的独立 `env` 参数得到运行时映射；
- 禁止在请求/任务执行中调用 `os.environ.update()` 或 `setdefault()`；
- 没有显式路径参数且依赖全局环境的第三方库，必须放入带独立环境的 worker 子进程，不能用线程内临时修改全局环境。

这保证未来同一进程中的多任务、同一 Job 的回合级并行和测试进程不会互相污染路径。

### 3.4 与 `PipelineConfig` 的关系

本阶段保留 `output_root` 和 `whisper_cache_dir` 字段，以便读取旧 manifest 和旧 Job；但它们不再是新任务的路径真相源。

- 新任务在应用边界将运行时解析结果显式注入 Pipeline/Store/Adapter；
- 旧 manifest 中的缓存路径只作为历史信息读取，不得驱动新下载；
- 运行时路径不得序列化成可分享 manifest 中的本机绝对路径；
- 若兼容旧代码必须暂时回填字段，应在单一兼容适配函数内完成，并有删除标记，不能在多个命令中各自赋值。

## 4. 文件落点与生命周期

| 数据 | 新位置 | 生命周期与规则 |
|---|---|---|
| 用户选择的原始 Demo | 工作区外也可 | 只读，不在源目录生成旁路文件 |
| 本次任务准备的 Demo | `jobs/<job-id>/input/` | 阶段 1.2 前的兼容副本；`.zst` 处理文件也只能在本 Job 内 |
| Job 清单、解析结果 | `jobs/<job-id>/` | 耐久数据 |
| 最终字幕、绿幕等 | `jobs/<job-id>/final/` | 耐久数据 |
| 人工复核文件 | `jobs/<job-id>/review/` | 耐久数据 |
| 默认临时音频 | `cache/audio/<job-id>/` | 可清理；阶段完成后默认删除 |
| 明确保留的调试音频 | `jobs/<job-id>/debug/temp_audio/` | 耐久调试数据 |
| 通用临时文件 | `cache/tmp/<task-id>/` | 任务隔离、可清理 |
| faster-whisper 下载 | `cache/whisper/` | 可重新下载缓存 |
| Hugging Face 缓存 | `cache/huggingface/`、`cache/huggingface/hub/` | 可重新下载缓存 |
| 渲染缓存 | `cache/render/` | 可清理 |
| RenderBundle | `render_bundles/` | 耐久、可传到另一台机器 |
| 人工导入的持久模型 | `models/` | 本阶段保留目录和边界，不实现导入 |

缓存清理只能触及 `WorkspacePaths.cache_directories()` 明确列出的目录。它不得删除 `jobs/`、`knowledge/`、`models/`、`demos/` 或 `render_bundles/`。

正常向导不再询问“输出根目录”，只显示当前工作区和即将创建的 Job 位置。

### 4.1 Demo 的阶段性语义

01D 允许直接选择外部 `.dem` 或 `.dem.zst`，但外部文件只读。旧 Pipeline 所需的任务级副本或解压结果进入 Job 的 `input/`。

01D 不建立 Demo 数据库、不承诺跨 Job 去重，也不把外部绝对路径变成长期资产标识。阶段 1.2 再实现：

- 压缩源保存；
- 内容哈希和重复导入去重；
- 解压缓存；
- Job 通过资源 ID 引用 DemoAsset；
- 中断恢复与哈希校验。

因此，01D 后暂时存在每个 Job 的输入副本是已知过渡成本，不得为消除它而提前发明简化版资产仓储。

### 4.2 Job ID 与路径安全

自动 Job ID 继续保留便于人阅读的时间/地图信息，但必须：

- 同一秒并发创建不复用目录；
- 显式 Job ID 不能是绝对路径；
- 拒绝 `..`、斜杠、反斜杠、盘符和空名称；
- 最终解析路径必须位于选定 Job 根目录内，显式外部输出模式除外；
- 目录冲突时生成稳定可观察的新名称，不得合并旧 Job 内容。

## 5. 工作区硬门禁

以下操作必须先取得健康、可写的当前工作区：

- `cs2pov run`；
- 文本向导新建工程；
- 模型下载或模型加载测试；
- 新 Job 创建；
- 旧 Job 恢复、重转录或任何会产生临时文件的操作。

以下操作可在没有当前工作区时运行：

- 帮助和版本；
- 工作区初始化、选择、查看、诊断和忘记；
- 不产生资产的环境说明命令。

门禁必须在创建 Job、下载模型或复制 Demo 之前完成。失败后不得留下半成品目录。

## 6. 旧行为兼容

### 6.1 新 Job 默认行为

```text
cs2pov run demo.dem
  → 解析当前 WorkspaceRuntime
  → workspace/jobs/<new-job-id>/
```

CLI 的 `--output` 默认值改为“未显式提供”，不能继续使用字符串 `output` 来区分默认和用户意图。

### 6.2 显式外部 `--output`

在一个过渡版本内允许：

```text
cs2pov run demo.dem --output D:\legacy-output
```

规则：

- 仍要求健康的当前工作区；
- Job 本身可以写入显式外部目录；
- 模型缓存、Hugging Face 缓存和通用临时文件仍来自当前工作区；
- 启动前和完成摘要都显示醒目的“旧版外部输出”警告；
- manifest 记录路径政策版本和 `legacy_external_output=true`，但可分享内容不得泄露外部绝对路径；
- 未显式提供 `--output` 时绝不进入兼容模式。

兼容期结束时间由后续发布决策确定，不在 01D 静默删除。

### 6.3 旧 Job 操作

用户明确给出旧 Job 路径时，查看、重导出、重翻译和恢复继续可用。会写入的操作必须要求当前工作区，并提示“正在原位置修改外部旧 Job”。运行所需模型和临时缓存仍来自当前工作区。

01D 不自动移动或改写旧 Job。原计划由阶段 1.3 提供只读扫描、迁移报告和幂等导入；该后续已于 2026-08-31 经用户确认取消，已有兼容行为保留但不扩展。

### 6.4 旧模型路径参数与配置

- `--whisper-cache-dir` 不再允许改变运行位置；
- `models set-cache` 保留入口但不再写新路径，返回明确的工作区迁移说明；
- 旧 `~/.cs2pov/config.json` 的 `whisper_cache_dir` 只读识别并显示“已弃用”；
- 运行时不采用旧配置，也不自动改写用户文件；
- 不能静默忽略显式旧参数，必须返回稳定错误或迁移说明。

## 7. 旧模型缓存的非破坏性策略

01D 可以只读检测常见 Hugging Face/Whisper 旧缓存，并报告位置与占用空间，但必须与“当前工作区可用模型”分栏显示。

- 新下载只进入当前工作区；
- 不自动移动、复制或删除旧缓存；
- 不把检测到的旧缓存重新加入当前下载候选；
- 不承诺旧缓存完整或可加载；
- 后续独立任务可设计显式“导入旧模型缓存”，先验证再复制，源目录由用户自行确认处理。

这样避免破坏共享缓存、Windows 链接、残缺下载或数 GB 数据，同时立即阻止继续向 C 盘写入。

## 8. 错误模型与用户提示

所有路径门禁错误至少提供：

- 稳定错误代码；
- 简明中文说明；
- 可直接执行的建议命令；
- 适合 CLI/未来 API 的结构化字段。

建议错误代码包括：

```text
workspace_selection_required
workspace_unhealthy
workspace_not_writable
workspace_space_low
workspace_runtime_path_invalid
legacy_model_cache_override_rejected
job_id_invalid
job_path_escape
legacy_external_output_active
```

普通用户入口不得显示 Python traceback。JSON 模式的 stdout 必须保持可解析；诊断信息不得夹杂在 JSON 前后。日志和反馈包继续执行秘密与本机路径脱敏规则。

## 9. 测试与真实端到端验收

### 9.1 Luna-01D-A 单元与集成测试

至少覆盖：

- 未选择工作区时写运行时失败；
- 工作区损坏、不可写或空间不足时失败；
- 运行时所有目录都来自同一 `WorkspacePaths`；
- 运行时冻结，随后切换选择不影响旧实例；
- Whisper 得到显式 `download_root`；
- 适配器不修改 `os.environ`；
- 模型扫描区分当前缓存与旧缓存；
- 旧 `whisper_cache_dir` 不驱动下载；
- 旧缓存检测只读且不创建目录；
- 弃用命令和参数产生稳定、无 traceback 的提示。

### 9.2 Luna-01D-A 真实子进程 E2E

新增独立脚本，由 CI 启动真实解释器/CLI 进程：

```text
建立隔离的临时 HOME、cwd、状态目录和工作区
→ 通过 CLI 初始化工作区
→ 启动真实 models 命令
→ 使用测试用 faster_whisper 模块记录 WhisperModel 实际收到的参数
→ 断言 download_root 位于 workspace/cache/whisper
→ 断言伪造 HOME、cwd 和默认 Hugging Face 目录没有新资产
→ 写入旧 whisper_cache_dir 后重跑
→ 断言旧目录仍未写入，并得到弃用提示
→ 损坏工作区后重跑
→ 断言模型构造函数没有被调用
```

测试替身只替代不可在 CI 下载的大模型，CLI 进程、状态文件、运行时解析、参数传递和文件系统断言都必须是真实的。不得直接调用 handler 冒充 E2E。

### 9.3 Luna-01D-B 单元与集成测试

至少覆盖：

- 默认 Job 根目录；
- 显式外部输出的唯一兼容分支；
- 外部 Demo 源只读；
- `.dem`/`.dem.zst` 准备文件位于 Job；
- 临时音频位于 `cache/audio/<job-id>` 并默认清理；
- `keep_temp_audio` 转存到 `debug/temp_audio`；
- Job ID 冲突、绝对路径、`..` 和目录分隔符；
- 旧 Job 恢复使用工作区模型/临时缓存；
- manifest 只记录兼容标志，不泄露不必要的本机绝对路径；
- 门禁失败不创建半成品。

### 9.4 Luna-01D-B 真实子进程文件系统 E2E

```text
初始化临时工作区
→ 从工作区外选择合成 Demo
→ 真实启动 cs2pov run 并运行到 prepare_input
→ 验证 Job 和 Demo 副本位于 workspace/jobs
→ 验证 cwd/output、隔离 HOME 和伪系统缓存没有新资产
→ 用显式 --output 再运行一次
→ 验证兼容警告和 manifest 标志
→ 损坏工作区后再次运行
→ 验证启动被拒绝且没有 Job 半成品
```

E2E 必须在 Windows 与 Ubuntu GitHub CI 运行，并与现有 `check_workspace_cli_e2e.py`、golden baseline 和完整 pytest 一起作为门禁。

### 9.5 不需要的硬件

01D 不需要 CS2、GPU 或真实下载大型模型。真实 Demo/GPU 机器验证仍留在总计划的录制和发布级硬件 E2E 阶段。

## 10. 文档与用户界面更新

两个 PR 合计需要同步更新：

- CLI `--help` 与文本启动器说明；
- 工作区首页状态，去掉“模型和任务尚未接入”的旧提示；
- 模型管理菜单，去掉“设置任意缓存目录”的推荐；
- 新任务默认输出说明；
- 旧外部输出、旧缓存与旧 Job 的迁移说明；
- 测试指南和发布检查清单中的默认 `output/` 示例。

示例不得继续教普通用户把模型放到项目源码目录或手工选择零散产物目录。

## 11. 明确不在本设计内

- DemoAsset 导入、哈希去重和跨 Job 复用（阶段 1.2）；
- 旧 Job 正式导入器（原阶段 1.3，已于 2026-08-31 取消）；
- 新版领域 Job 状态机和资源 ID schema（阶段 2）；
- 理解翻译、知识库和回合级并行调度（阶段 5）；
- Web 管理界面与 Playwright 浏览器 E2E（阶段 6–7）；
- POV 录制、CS2/HLAE、GPU 编码与最终视频合成（阶段 8–9）；
- 自动移动或删除旧 C 盘模型缓存。

## 12. 验收标准

Luna-01D 全部完成时必须满足：

1. 没有当前健康工作区时，资产写操作在产生文件前失败；
2. 默认新 Job 和全部产物位于 `workspace/jobs/`；
3. Whisper/Hugging Face 新下载与通用临时文件只能写当前工作区；
4. 外部 Demo 源保持只读，本次处理文件不散落到源目录；
5. 正常向导不再要求非程序员管理输出根目录；
6. 显式外部 `--output` 是可见、可审计的限时兼容例外；
7. 旧 Job 可显式操作，但模型和临时缓存仍服从当前工作区；
8. 旧 C 盘模型缓存只读提示，不自动搬迁或删除；
9. 不存在进程级环境变量污染和路径逃逸；
10. Windows/Ubuntu 的真实子进程 E2E 能证明实际落盘位置；
11. 完整 pytest、现有 golden baseline、仓库卫生与编译检查通过；
12. PR 和 GitHub CI 经强模型核验，只有用户明确确认后合并。

完成 01D-A 与 01D-B 后，阶段 1.1 的文件管理问题才算闭环，下一步进入 DemoAsset 导入与哈希去重。
