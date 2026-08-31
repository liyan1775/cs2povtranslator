# Luna-01E：DemoAsset 素材库、内容寻址与 Job 引用设计

- 状态：已确认，待编写 Luna 实施任务书
- 日期：2026-08-31
- 前置阶段：Luna-01A 至 Luna-01D-B 已完成并合并
- 交付拆分：Luna-01E-A、Luna-01E-B 两个独立 PR

## 1. 背景与目标

Luna-01D 已让模型、Job、输入副本、临时音频和输出跟随当前工作区，解决了文件散落和默认写入系统盘的问题。它仍保留一个明确的过渡成本：每个新 Job 都会在自己的 `input/` 下保存或解压一份 Demo。重复处理同一场比赛时，用户会得到多份长期副本，也无法在未来 Web 中把 Demo 当作可管理素材。

Luna-01E 建立工作区级 `DemoAsset` 素材库。它按解压后的 Demo 内容哈希识别同一素材，让 `.dem` 与 `.dem.zst` 可以指向同一个逻辑资产，并让新 Job 通过稳定资源 ID 引用资产，而不是持久复制原始 Demo。

本阶段必须同时满足：

1. 普通用户在 `run` 或向导中选择外部 Demo 后自动导入，无需理解额外的技术步骤；
2. 导入行为明确显示“新导入”或“已复用”，不静默占用磁盘；
3. 相同逻辑 Demo 只长期保存一份资产；
4. 压缩源长期保存，解压结果属于可清理缓存；
5. Job 不依赖最初选择的外部路径；
6. 并发、中断和文件损坏不会产生半个可见资产或错误复用；
7. 旧 Job 不被隐式迁移，继续按旧语义工作；
8. 应用服务可被 CLI、自动化和未来 Web/API 共同调用；
9. 全过程不需要 CS2、GPU、真实模型或私人 Demo。

## 2. 范围与交付拆分

### 2.1 Luna-01E-A：素材库内核和管理入口

01E-A 交付：

- 版本化 `DemoAsset` 领域对象；
- 以解压后 `.dem` 内容 SHA-256 为资源 ID 的目录布局；
- `.dem` 与 `.dem.zst` 的流式、原子、可恢复导入；
- 内容去重、完整性验证和解压缓存解析；
- 与界面无关的导入、列表、检查应用服务；
- `cs2pov demos import/list/inspect` 文本和 JSON 命令；
- 多线程、多进程、Windows junction 与真实子进程 E2E；
- 用户文档和 CI 门禁。

因为 `.dem.zst` 导入属于素材库核心能力，`zstandard>=0.23` 从 `cs2` 可选组提升为基础运行依赖；`demoparser2`、语音解码、Whisper、GPU 和渲染依赖仍保持可选。

01E-A 不改变 `run`、向导或 Pipeline。用户可以显式管理素材库，但现有任务仍按 01D 方式创建输入副本。

### 2.2 Luna-01E-B：自动导入和 Job 引用

01E-B 交付：

- `run` 和向导选择外部 Demo 后自动导入或复用；
- Pipeline 在创建 Job 前取得不可变 `DemoAssetRef`；
- 新 Job manifest 保存 `demo_asset_id` 和工作区相对引用；
- 新 Job 不再持久复制 `.dem` 或 `.dem.zst`；
- `.dem.zst` 解压缓存缺失时从持久源重建；
- Job 恢复、显式 `--output` 和工作区切换的清晰兼容语义；
- 两个 Job 复用一个资产的真实子进程 E2E；
- 当前文档和发布清单更新。

### 2.3 不在 01E 中实现

- 旧 Job 扫描、导入和批量迁移；该能力属于阶段 1.3；
- Demo 删除、回收站、引用计数和自动清理；
- Demo 数据库、全文搜索、标签、缩略图和比赛元数据目录；
- 跨工作区全局去重或联网素材同步；
- Web UI、HTTP API 或 Playwright；
- 新领域时间轴、理解翻译、知识库、回合并行和模型 API 档案；
- POV 录制、视频渲染或硬件 E2E；
- 用硬链接、符号链接或 junction 作为 Job 与资产之间的持久关系。

## 3. 已评估方案

### 3.1 采用：内容寻址资产库，分两个 PR 接入

先建立可独立验证的资产库，再让 Pipeline 消费资产引用。这样可以分别审查存储正确性和任务行为变化，也能在 01E-A 出现问题时完全不影响现有主流程。

### 3.2 不采用：一个 PR 同时重写导入和 Pipeline

该方案表面更快，但存储原子性、旧 Job 兼容、Pipeline 回归和用户入口会混在一个审查单元中。失败时很难判断问题来自资产库还是任务接入，也无法给 Luna 设置可靠检查点。

### 3.3 不采用：硬链接或目录链接实现去重

硬链接不能稳定跨盘，删除和权限语义容易误导用户；符号链接与 Windows junction 还会扩大路径逃逸风险。Job 需要逻辑资源引用，不需要文件系统链接伪装成副本。

### 3.4 不采用：按压缩文件字节哈希

同一 `.dem` 可以被不同参数压缩成不同 `.dem.zst` 字节。若按源文件字节生成 ID，同一逻辑 Demo 会产生多个资产，不能满足素材去重目标。因此资源 ID 必须来自解压后 `.dem` 字节。

## 4. 目录布局与资源身份

工作区使用以下布局：

```text
library/
  demos/
    <64 位小写 SHA-256>/
      asset.json
      source.dem
      # 或 source.dem.zst，二者只存在一个

cache/
  decompressed_demos/
    <asset_id>.dem
  tmp/
    demo_imports/
      <随机 staging id>/
        asset/
          asset.json
          source.dem 或 source.dem.zst
        logical.dem  # 仅 `.dem.zst` 导入时存在，属于缓存候选
```

`asset_id` 等于解压后 `.dem` 完整字节的 SHA-256，固定为 64 位小写十六进制。01E 不使用短哈希作为目录名，也不根据文件名生成身份。

首个成功提交的源格式成为该资产的持久源：

- 首次导入 `.dem`：保存 `source.dem`；
- 首次导入 `.dem.zst`：保存 `source.dem.zst`；
- 后续以另一种格式导入相同逻辑内容：复用既有资产，不再保存第二份源文件。

这项规则保证每个资产只有一个明确的持久恢复源。01E 不为了节省首个未压缩源的空间而自动重新压缩，也不在复用时替换现有源。

## 5. 领域对象与持久契约

### 5.1 DemoAsset

领域对象至少包含：

```text
DemoAsset
  schema_version: 1
  asset_id: str
  logical_sha256: str
  logical_size_bytes: int
  source_sha256: str
  source_size_bytes: int
  source_format: "dem" | "dem.zst"
  source_relative_path: str
  display_name: str
  imported_at: str
```

约束：

- `asset_id == logical_sha256`；
- 哈希只接受 64 位小写十六进制；
- 大小必须为非负整数；
- `source_relative_path` 必须经过 `WorkspacePaths.resolve_relative()`，且必须落在该资产目录；
- `display_name` 只保存外部文件的 basename，经控制字符、空白和长度规范化后用于普通用户识别；
- 不保存外部绝对路径、用户目录、SteamID、API Key、模型配置或任意自由扩展字段；
- `asset.json` v1 拒绝未知键，避免未经设计的数据进入长期资产。

### 5.2 DemoAssetRef

Job 和 Pipeline 消费轻量不可变引用：

```text
DemoAssetRef
  asset_id: str
  asset_manifest_relative_path: str
```

引用不携带外部源路径，也不缓存可变的解压路径。运行时必须通过当前 `WorkspaceRuntime` 和仓储解析真实文件。

### 5.3 导入结果

应用服务返回结构化结果：

```text
DemoImportResult
  asset: DemoAsset
  disposition: "imported" | "reused"
  persistent_bytes_added: int
```

CLI 文本模式据此显示“新导入”或“已复用”；JSON 模式直接序列化稳定字段。JSON stdout 不混入进度、警告或路径日志。

## 6. 导入数据流

### 6.1 写前门禁

所有写入口先通过 `WorkspaceRuntimeResolver.resolve_for_write()` 取得不可变运行时。然后检查：

- 源路径显式提供、存在、是普通文件且不是目录；
- 后缀严格为 `.dem` 或 `.dem.zst`，大小写可规范化；
- 源路径解析后不位于受管资产目标或 staging 内，避免自导入递归；
- 工作区目录健康、可写且路径未通过符号链接或 junction 逃逸；
- 根据源大小和可获得的空间信息执行保守预检；空间未知时允许继续，但写盘错误必须稳定映射。

在这些门禁通过前，不创建资产目录、Job 或持久 manifest。

### 6.2 `.dem` 导入

1. 记录源文件大小、修改时间和文件标识的前置快照；
2. 在 `cache/tmp/demo_imports/<随机 id>/asset/` 中流式复制为 `source.dem`，复制时计算 SHA-256；
3. 复制后重新读取源文件状态；大小、修改时间或可用文件标识改变时拒绝提交；
4. 将流式哈希作为 `asset_id` 和 `logical_sha256`；
5. 在 staging 的 `asset/` 子目录内写完整 `asset.json`，其中持久相对路径预先指向最终资产位置；
6. 执行第 7 节的原子提交；
7. 成功后返回 `imported`，或在相同资产已存在且验证通过时返回 `reused`。

### 6.3 `.dem.zst` 导入

1. 流式复制压缩源到 staging 的 `asset/source.dem.zst`，同时计算 `source_sha256`；
2. 使用现有 zstandard 适配能力流式解压到 staging 根部的 `logical.dem`，同时计算解压内容 SHA-256 和大小；
3. 解压失败、尾部数据非法或没有得到合法输出时拒绝提交；
4. 重新检查外部源状态，发现导入期间变化时拒绝提交；
5. 用解压内容哈希生成 `asset_id`，在 staging 的 `asset/` 子目录写完整 manifest；
6. 把只包含压缩源和 manifest 的 `asset/` 子目录原子提交到持久资产目录；
7. 将 `logical.dem` 以同根原子重命名提交到 `cache/decompressed_demos/<asset_id>.dem`；
8. 缓存提交失败不回滚已经完整提交的持久资产。后续解析可以从压缩源重建缓存；本次命令返回明确的可恢复缓存错误或完成重建后再成功。

## 7. 原子性、并发与中断恢复

每次导入使用工作区内部的唯一 staging 目录。该目录与最终资产目录位于同一文件系统，所有最终提交使用同根重命名，不使用跨盘复制冒充原子操作。

当 staging 的 `asset/` 子目录已包含源文件和完整 manifest 后，仓储尝试把该非空子目录重命名为 `library/demos/<asset_id>`；staging 根部的 `logical.dem` 只用于提交解压缓存，绝不进入持久资产目录：

- 目标不存在：当前导入胜出，完整目录一次可见；
- 目标已存在：当前导入不覆盖目标，转为验证已存在资产；
- 已存在资产自检完整，且候选的逻辑内容哈希等于其 `asset_id`：删除自己的 staging，返回 `reused`；候选和既有资产的源格式或压缩源哈希可以不同；
- 已存在资产不完整、manifest 非法或哈希不一致：返回完整性错误，保留现有资产供诊断，不覆盖、不合并；
- 无论哪个进程胜出，最终只能有一个持久资产目录。

进程在提交前中断只会留下 `cache/tmp/demo_imports/` 下的 staging。后续导入忽略其他随机 staging，并可以清理超过安全时限且没有活跃所有者的遗留目录。01E-A 不把 staging 目录列为资产，也不让列表命令显示它。

进程在资产目录重命名成功后中断，最终目录已经是完整提交。`.dem.zst` 的解压缓存可能缺失，但它是可重建缓存，不影响资产完整性。

线程级测试和真实多进程 E2E 都必须证明上述语义。实现不得仅依赖进程内锁。

## 8. 完整性验证与缓存解析

### 8.1 持久源验证

仓储在导入碰到已有资产、显式 `inspect`、Job 首次解析资产时验证持久源：

- manifest schema 和字段；
- manifest 路径 containment；
- 源文件存在、格式和大小；
- 源文件 SHA-256 等于 `source_sha256`；
- `.dem` 源还必须满足 `source_sha256 == logical_sha256 == asset_id`；
- `.dem.zst` 在需要生成或严格检查缓存时，解压内容哈希必须等于 `logical_sha256`。

完整性失败不自动覆盖。错误结果不得把完整用户路径或哈希打印到普通反馈输出；本地 `inspect` 可以显示资产 ID 和工作区相对位置。

### 8.2 解压缓存

`.dem` 资产直接返回持久 `source.dem` 作为可读 Demo。

`.dem.zst` 资产解析顺序：

1. 若 `cache/decompressed_demos/<asset_id>.dem` 存在，流式验证大小和 SHA-256；
2. 验证通过则复用；
3. 验证失败则不把它交给 Pipeline，先移入工作区临时诊断位置或使用安全替换流程；
4. 从持久 `source.dem.zst` 解压到同目录 staging；
5. 验证逻辑大小和哈希后原子提交为正式缓存；
6. 多进程同时重建时只接受一个完整胜出文件，其他进程验证后复用。

`demos list` 和 `demos inspect` 是只读命令：它们可以验证并报告缓存缺失或损坏，但不得创建、替换或重建缓存。再次执行 `demos import`，或由未来 Pipeline 调用 `ResolveDemoAsset` 时，才允许按上述流程重建。

缓存清理可以删除解压文件，但不得删除 `library/demos/` 内的源或 manifest。

## 9. 应用服务与 CLI

### 9.1 应用服务

建议的稳定用例边界：

```text
ImportDemoAsset.execute(source: Path, runtime: WorkspaceRuntime) -> DemoImportResult
ListDemoAssets.execute(runtime: WorkspaceRuntime) -> tuple[DemoAssetSummary, ...]
InspectDemoAsset.execute(asset_id: str, runtime: WorkspaceRuntime) -> DemoAssetInspection
ResolveDemoAsset.execute(ref: DemoAssetRef, runtime: WorkspaceRuntime) -> ResolvedDemoAsset
```

领域层不导入 zstandard、文件系统仓储、CLI 或 Pipeline。压缩与持久化通过端口/适配器完成。应用服务只编排写前门禁、仓储和错误映射。

### 9.2 CLI 管理入口

01E-A 新增：

```text
cs2pov demos import <path> [--json]
cs2pov demos list [--json]
cs2pov demos inspect <asset-id> [--json]
```

文本模式面向非程序员：

- import 显示文件名、结果是“新导入”还是“已复用”、长期新增字节和下一步命令；
- list 按导入时间和资产 ID 确定性排序，显示名称、格式、大小和健康摘要；
- inspect 只读显示源是否完整、缓存是否存在及可执行建议，不暗中重建缓存；
- 不要求用户输入或复制完整工作区路径；
- 不提供 delete、repair 或隐式覆盖选项。

JSON 模式：

- stdout 只有一个 JSON 文档；
- 人类进度和兼容警告写 stderr；
- 已知错误使用现有 CLI 错误 envelope、稳定 code 和非零退出码；
- 不序列化外部绝对路径、临时 staging 路径或 traceback。

## 10. 01E-B 自动导入与 Pipeline 数据流

新任务入口必须在创建 Job 前完成资产导入：

```text
用户选择外部 Demo
→ 解析健康 WorkspaceRuntime
→ ImportDemoAsset
→ 显示 imported / reused
→ 创建 JobRuntime 和 Job
→ PipelineEngine 消费 DemoAssetRef
→ ResolveDemoAsset 得到受管 .dem 读取路径
→ 后续 inspect/voice/round 阶段读取该路径
```

`PipelineEngine` 不自行读取全局选择状态，也不从外部路径猜测资产。入口显式注入同一份 `WorkspaceRuntime`、`JobRuntime` 和 `DemoAssetRef`。

新 Job 的 `input/` 只允许保存小型引用或诊断元数据，不允许出现持久 `.dem`、`.dem.zst` 或链接。manifest 至少记录：

```json
{
  "demo": {
    "asset_id": "<64 位哈希>",
    "asset_manifest": "library/demos/<asset_id>/asset.json",
    "display_name": "match.dem.zst"
  }
}
```

manifest 不保存解析后的绝对资产路径或最初外部路径。Pipeline 内部的运行时绝对路径不得进入可分享的 manifest、JSON 报告或反馈包。

## 11. 兼容策略

### 11.1 旧 Job

任何已有 `input/*.dem` 的 Job 都保持原位：

- inspect、export、retranslate、feedback 和 resume 继续识别旧结构；
- 不在读取、恢复或修改时自动导入 DemoAsset；
- 不删除旧输入副本；
- manifest 明确保留 legacy 输入语义；
- 阶段 1.3 再提供只读扫描、迁移报告和幂等导入。

### 11.2 新 Job 与工作区切换

新 Job 只在创建它的工作区中解析 `demo_asset_id`。如果用户切换工作区后对外部 Job 执行需要 Demo 的写操作，而当前工作区没有该资产，必须返回 `demo_asset_not_found`，说明切回原工作区或显式重新导入。不得扫描其他磁盘、用户目录或旧缓存猜测来源。

### 11.3 显式外部 `--output`

`--output` 继续作为 01D 定义的旧版外部 Job 目录兼容选项。它仍要求健康当前工作区，并在任务前后警告。DemoAsset 始终进入当前工作区，外部 Job 只保存资源 ID，不恢复每 Job 原始 Demo 副本。

### 11.4 命令与内部 API 过渡

01E-B 可以在一个发布兼容期内保留内部 `Path` 输入适配，但所有正式 CLI/向导入口必须先导入为 `DemoAssetRef`。兼容适配器不得绕过工作区或在 Pipeline 内静默复制。下一阶段任务书必须列出剩余旧调用点，避免形成永久双轨。

## 12. 稳定错误

至少定义以下稳定错误码，并提供中文消息与可执行建议：

| code | 含义 | 写盘要求 |
|---|---|---|
| `demo_source_required` | 未提供源路径 | 不写盘 |
| `demo_source_not_found` | 源不存在 | 不写盘 |
| `demo_source_not_file` | 源不是普通文件 | 不写盘 |
| `demo_source_format_unsupported` | 不是 `.dem`/`.dem.zst` | 不写盘 |
| `demo_source_empty` | 源或解压后的 Demo 为空 | 不提交资产 |
| `demo_source_unreadable` | 无法读取源文件 | 不提交资产 |
| `demo_source_changed` | 导入期间源发生变化 | 不提交资产 |
| `demo_decompression_failed` | zstd 源损坏或解压失败 | 不提交资产 |
| `demo_import_space_insufficient` | 工作区空间不足 | 不提交资产 |
| `demo_asset_id_invalid` | 资源 ID 格式非法 | 不写盘 |
| `demo_asset_not_found` | 当前工作区没有引用资产 | 不创建新副本 |
| `demo_asset_manifest_invalid` | manifest schema/字段非法 | 不复用、不覆盖 |
| `demo_asset_path_escape` | 资产路径越界或经过恶意链接 | 不复用、不覆盖 |
| `demo_asset_integrity_failed` | 源、缓存或逻辑哈希不一致 | 不复用、不覆盖 |
| `demo_asset_commit_failed` | 原子提交失败 | 保留可诊断 staging 或安全清理 |
| `demo_cache_rebuild_failed` | 解压缓存无法重建 | 持久资产保持不变 |

底层 `OSError`、zstandard 异常和并发冲突必须映射到稳定应用错误。未知程序错误可以保留 traceback 给开发日志，但普通 JSON 错误不能泄漏本机路径。

## 13. 安全与隐私

- 外部 Demo 只读；导入器不移动、重命名或修改用户原文件；
- 所有持久和临时目标必须经 `WorkspacePaths` containment 校验；
- Windows symlink、junction、尾点、保留名和大小写等价路径必须纳入测试；
- staging、资产目录和缓存不得通过链接逃出工作区；
- manifest、Job、日志和反馈包不保存外部绝对路径；
- Demo 原始文件、资产库、缓存和真实哈希不得提交 GitHub；
- 反馈包继续排除 Demo、WAV、大缓存和秘密；
- `demos list/inspect --json` 可以返回当前工作区内的资产 ID，但不返回用户 HOME 或外部源位置；
- CLI 不显示完整内容哈希之外的敏感本机信息，错误消息不回显临时路径；
- 不把 Demo 或解压内容发送给 LLM、网络服务或遥测。

## 14. 测试设计

### 14.1 01E-A 单元与集成测试

必须覆盖：

- `.dem` 导入、manifest 精确 schema 和相对路径；
- `.dem.zst` 导入、压缩源保存和缓存生成；
- 同一逻辑内容以不同名称重复导入只产生一个资产；
- 同一逻辑内容以 `.dem` 与不同压缩字节的 `.dem.zst` 导入仍复用；
- 不同内容产生不同资产；
- 源在导入期间变化时失败；
- 无效 zstd、空文件、目录、未知扩展和不可读源；
- manifest 未知字段、非法哈希、非法相对路径和路径逃逸；
- symlink 与 Windows junction 指向工作区外时拒绝；
- 多线程与多进程同时导入同一内容；
- 提交前异常只留下 staging，不显示为资产；
- 已有完整资产复用，已有半成品或哈希冲突拒绝；
- 解压缓存删除后重建，篡改后不复用；
- list/inspect 的确定性顺序、健康状态和 JSON 脱敏；
- 默认命令在未初始化或损坏工作区时写前失败。

### 14.2 01E-A 真实子进程 E2E

新增独立脚本，在临时 HOME、USERPROFILE、LOCALAPPDATA、APPDATA、XDG 状态、cwd 和工作区中运行真实 `python -m cs2pov` 命令，不直接调用 handler，不 monkeypatch 仓储：

1. 初始化临时工作区；
2. 生成匿名合成 `.dem` 字节和对应 `.dem.zst`；
3. 分别导入不同文件名和两种格式；
4. 断言输出均指向同一 `asset_id`，持久资产目录只有一个；
5. 断言压缩首源保存；删除缓存后 inspect 只报告缺失，再次 import 同一 `.dem.zst` 时重建；
6. 并发启动多个真实子进程导入同一内容，最终仍只有一个完整资产；
7. 预置遗留 staging，断言 list 不显示且新导入可成功；
8. 篡改源或 manifest，断言稳定失败且没有覆盖；
9. 对 stdout 执行真实 JSON 解析；
10. 快照断言源码树、cwd、隔离 HOME 和工作区外目录无旁路写入。

### 14.3 01E-B Pipeline E2E

在不需要真实 CS2/GPU/模型的 `prepare_input` 边界验证：

- 两次运行同一 Demo 创建两个 Job，但只有一个 DemoAsset；
- 两个 Job manifest 引用相同 `asset_id`；
- 两个 Job `input/` 都没有 `.dem`、`.dem.zst` 或文件系统链接；
- `.dem.zst` 缓存删除后第二个 Job 自动重建；
- 移动或删除最初外部源后仍能运行；
- 外部 `--output` Job 仍引用当前工作区资产并出现前后警告；
- 切换到不含资产的工作区后稳定失败，不扫描其他位置；
- 旧 Job fixture 仍能 inspect/resume，不被自动改写；
- 损坏 workspace 或资产在 Job 创建前失败；
- manifest、JSON、反馈包和日志不出现外部绝对路径。

### 14.4 CI 与发布门禁

01E 的真实 E2E 接入当前全部矩阵：

- Ubuntu：Python 3.11、3.12、3.13；
- Windows：Python 3.12。

每个 PR 合并前必须：

1. 针对测试通过；
2. 完整 pytest 通过；
3. 既有三个 workspace E2E 和新增 DemoAsset E2E 通过；
4. golden baseline、repository hygiene、compileall、launch sanity 和 `git diff --check` 通过；
5. 独立强模型只读审查无 Critical/Important；
6. GitHub CI 全绿；
7. PR 合并后同步本地 `master`。

## 15. 文档与非程序员体验

01E-A 更新：

- README 中的工作区目录和显式素材管理命令；
- 输出文件说明中的 `library/demos`、持久源与可清理缓存边界；
- FAQ 中的重复导入、磁盘占用、缓存删除和损坏处理；
- 测试指南和发布检查清单；
- 架构文档明确 01E-A 已建立素材库但 Pipeline 尚未接入。

01E-B 更新：

- 快速开始与向导说明改为自动导入/复用；
- Job 输出说明明确不再包含原始 Demo 副本；
- 兼容说明区分旧 Job 与新资产引用 Job；
- 架构文档明确 01E 完成，不宣称旧 Job 迁移、Web 或录制已实现。

面向普通用户的关键文案必须直白：

- “已导入到当前工作区素材库，之后可重复使用。”
- “工作区已有相同 Demo，本次直接复用，不再占用一份长期空间。”
- “这里只删除了解压缓存，原始素材仍安全保存，需要时会自动重建。”
- “当前工作区找不到这个 Job 引用的 Demo，请切回创建该 Job 的工作区。”

## 16. 完成定义

Luna-01E 只有同时满足以下条件才算完成：

1. 普通用户选择外部 Demo 后可以自动导入并看到明确结果；
2. 相同解压内容无论文件名或压缩字节如何都只产生一个资产；
3. 每个资产只有一个完整、版本化、无外部绝对路径的 manifest；
4. 并发和中断不会产生可见半资产；
5. 压缩源长期保存，解压缓存可安全删除和重建；
6. 新 Job 只引用 `asset_id`，不持久复制 Demo；
7. 旧 Job 保持兼容且不被隐式迁移；
8. 损坏、越界和工作区错误全部写前失败或安全失败；
9. CLI 文本适合非程序员，JSON 可供自动化稳定解析；
10. 全量本地测试、真实子进程 E2E、独立审查和 GitHub CI 全部通过；
11. GitHub `master` 与本地 `master` 同步；
12. 文档没有宣称旧 Job 正式迁移、Web、理解翻译或录制已经完成。

完成后的下一步是阶段 1.3：旧 Job 只读扫描、迁移报告和幂等导入。只有 1.3 完成后，旧资产迁移闭环才成立。
