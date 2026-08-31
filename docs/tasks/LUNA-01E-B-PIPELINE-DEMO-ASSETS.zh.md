# Luna-01E-B：Pipeline 自动使用 DemoAsset 实施计划

**Goal：** 让所有正式新任务入口在创建 Job 前自动导入或复用工作区 DemoAsset，让新 Job 与 Pipeline 只保存并消费稳定素材引用，不再把 `.dem` / `.dem.zst` 复制、解压或链接到每个 Job 的 `input/`；同时完整保留旧 Job 的原地兼容行为。

**Architecture：** 外部路径只停留在入口与 `ImportDemoAsset` 用例。入口解析一次健康的 `WorkspaceRuntime`，用绑定到该不可变 runtime 的 `DemoAssetApplicationService` 导入素材，再把 `DemoAssetRef`、安全显示名和同一服务显式注入 `PipelineEngine`。Engine 需要 Demo 时通过服务解析工作区内受管 `.dem` 路径，但绝不把绝对素材路径写进 Job。新 Job manifest 记录版本化输入模式和相对素材引用；旧 Job 继续使用自己的 `input/`，不自动迁移。

**Spec：** `docs/plans/2026-08-31-demo-asset-library-design.zh.md` 第 10–16 节。

**Base：** `master` merge commit `9059638`（PR #15，Luna-01E-A）。

---

## 1. 不可协商约束

- 只实施 01E-B；不实现旧 Job 扫描/迁移、素材 delete、Web/API、理解翻译、模型配置、录制或 POV 视频合成。
- 最终产品目标仍是按回合时间校准的中英文字幕、Comms Feed、绿幕/透明 overlay；本批只改变 Demo 输入生命周期，不改变回合、语音、转录、翻译、字幕或渲染算法。
- 正式入口 `run`、文本向导和 `benchmark-asr` 必须在创建任何 Job 前完成 import/reuse；不得让 `PipelineEngine` 从外部路径静默导入。
- `PipelineEngine` 不读取工作区选择文件、环境变量或 cwd；它只消费显式注入的同一份 `WorkspaceRuntime`、`JobRuntime`、runtime-bound DemoAsset 服务和引用。
- 新 Job 的 `input/` 可以存在为空目录，但其中不得出现 `.dem`、`.dem.zst`、硬链接、symlink、junction 或指向素材库的路径文件。
- 新 Job manifest、`demo_info.json`、CLI JSON、benchmark 报告、日志与反馈包不得保存外部源绝对路径、素材解析后的绝对路径、staging 路径或用户 HOME。
- 新 Job 只在创建它的工作区解析素材。切换工作区后，不得扫描其他工作区、旧 Job、C 盘缓存、用户目录或最初外部位置猜测源。
- 旧 Job 继续原地识别 `input/*.dem[.zst]`；inspect/export/retranslate/feedback 不改写，resume 不自动导入、不删除旧输入、不创建素材引用。
- 显式 `--output` 保持旧版外部 Job 兼容警告，但 DemoAsset 仍属于当前工作区，外部 Job 只保存引用。
- 可以保留一个发布兼容期的内部 `Path` Pipeline API，供旧 Job与既有单元测试使用；所有正式新任务入口必须走 DemoAsset，且兼容分支必须被清楚标记为 `legacy_job_copy`。
- `demos list` / `demos inspect` 继续严格只读；01E-B 不改变 01E-A 内容身份、原子导入、缓存与完整性规则。
- 外部 Demo 始终只读；删除或移动外部源后，已创建的新 Job 仍可从持久素材恢复需要 Demo 的阶段。
- 任何 import、resolve、工作区或引用错误都必须在创建新 Job 前稳定失败；未知程序错误不能伪装成用户错误。
- 开发采用 TDD：每一任务先看到新增测试按预期失败，再写最小实现转绿，再跑相关回归。
- 每个批次独立 commit；不要混入版本号、发布 tag、真实 Demo、真实素材哈希或无关格式化。

---

## 2. 已审计调用点与剩余双轨

生产代码中 `PipelineEngine` 的正式创建点只有：

1. `src/cs2pov/cli/commands.py::run_pipeline`：专家 `cs2pov run`；
2. `src/cs2pov/cli/wizard.py::run_wizard`：普通用户向导，分两段运行同一 Engine；
3. `src/cs2pov/cli/commands.py::run_asr_benchmark`：每个模型创建一个 Job；
4. `src/cs2pov/cli/job_ops.py::resume_job`：新引用 Job 与旧副本 Job 的兼容恢复。

其余直接 `PipelineEngine(...).run(Path(...))` 调用位于测试或内部兼容层。01E-B 完成时必须再次运行：

```powershell
rg -n "PipelineEngine\(|\.run\(.*demo|engine\.run" src tests -g "*.py"
```

并在审查报告中列出仍使用 `Path` 的调用点及其“测试 / 旧 Job 兼容”理由。不得留下新的正式 CLI 绕过入口。

当前泄漏/复制点：

- `DemoService.prepare_input()` 会复制或解压到 `Job/input/`；只允许 legacy 分支继续调用；
- `PipelineManifest.artifacts["demo_path"]` 会持久化 Job 内 Demo 路径；新引用 Job不得设置这个 artifact；
- `DemoInfo.input_path/demo_path` 当前可能保存绝对路径；新引用 Job必须改为安全显示名与逻辑素材标识；
- `_rename_auto_job_dir()` 当前假设 Demo 在 Job/input 内；新引用 Job重命名时必须保留工作区素材路径，不得改写到新 Job/input；
- `_require_demo_path()` 当前从 artifact 和 input 猜测路径；新引用 Job必须优先且只通过当前 runtime 解析引用，失败时不得降级到 Job 文件或其他位置。

---

## 3. 新 Job manifest 契约

新引用 Job 的 `demo` 至少包含：

```json
{
  "input_mode": "demo_asset",
  "asset_id": "<64 位小写 SHA-256>",
  "asset_manifest": "library/demos/<asset_id>/asset.json",
  "display_name": "match.dem.zst",
  "map_name": "de_mirage",
  "server_name": "...",
  "players": 10
}
```

前三个身份字段和 `display_name` 在 Job 创建时写入；地图等检查结果后续更新。不得出现外部源路径、cache 路径、`artifacts.demo_path` 或文件系统链接。

内部兼容 Job 使用 `{"demo": {"input_mode": "legacy_job_copy"}}`。已存在且没有 `input_mode` 的旧 manifest 在只读操作中保持原样；只有执行本来就会保存 manifest 的旧 Job resume 时，才补上 `legacy_job_copy`，不得新增 asset 字段。

`PipelineManifest` 增加小而明确的方法，不允许入口手写散乱 dict：

```python
def bind_demo_asset(self, ref: DemoAssetRef, display_name: str) -> None: ...
def mark_legacy_demo_input(self) -> None: ...
def demo_asset_ref(self) -> DemoAssetRef | None: ...
def demo_asset_display_name(self) -> str | None: ...
```

读取 `demo_asset` 模式时，缺键、非法 hash、非法相对 manifest、控制字符/路径式 display name 都必须拒绝。旧 `demo` 中已有的 `map_name/server_name/players` 是检查结果，必须保留。

---

## 4. Pipeline 显式依赖与运行语义

`PipelineEngine` 增加仅用于受管输入的显式构造参数：

```python
demo_asset_ref: DemoAssetRef | None = None
demo_asset_display_name: str | None = None
demo_assets: DemoAssetApplicationService | None = None
```

规则：

- 三者要么全部存在，要么全部不存在；不完整组合在创建 Job 前失败；
- `demo_assets` 必须由 `DemoAssetApplicationService.for_runtime(runtime)` 创建并绑定相同 runtime；全局选择型服务不得注入 Engine；
- 新 manifest 时 Engine 调用 `bind_demo_asset()`；恢复 manifest 时，构造参数必须与 manifest 引用一致；
- legacy 分支调用 `mark_legacy_demo_input()`，但不制造素材引用；
- `run()` 的 `input_path` 改为可选。受管模式必须传 `None`，legacy 模式必须传 `Path`；同时提供两种输入属于内部契约错误；
- `PREPARE_INPUT` 在受管模式调用 bound service `resolve_asset(ref)`，把返回路径只保存在内存 `self.demo_path`，不调用 `DemoService.prepare_input()`，不设置 `artifacts.demo_path`；
- 受管 `_require_demo_path()` 在内存路径缺失时重新 resolve；失败直接传播稳定 DemoAsset 错误，不查看 Job/input；
- legacy `_require_demo_path()` 保持 artifact/input 查找；
- `INSPECT_DEMO` 对受管输入写 `input_path=display_name`、`demo_path=demo-asset:<asset_id>`；不得写解析后的真实路径；
- 自动重命名 Job 时，受管 `self.demo_path` 保持工作区素材路径，只有 legacy 才按新 Job/input 重算；
- 受管 `.dem.zst` cache 缺失时由 `resolve_asset` 在当前工作区重建；Job 目录保持无 Demo。

Engine 不负责 import。所有新任务入口在构造 Engine 前执行 import，并执行 resolve preflight，保证损坏或当前工作区缺失时不创建 Job。Engine 的 lazy resolve 是恢复、缓存删除和长运行竞态的第二道门禁。

---

## 5. Task 1：runtime-bound 服务与 manifest 引用契约

**Files：**

- Modify: `src/cs2pov/domain/assets.py`
- Modify: `src/cs2pov/application/demo_assets.py`
- Modify: `src/cs2pov/pipeline/manifest.py`
- Modify: `tests/test_demo_asset_models.py`
- Modify: `tests/test_demo_asset_application.py`
- Create: `tests/test_pipeline_demo_assets.py`

### 5.1 先写失败测试

领域契约：

- `DemoAssetRef.from_dict()` 只接受精确两个键，拒绝额外键、缺键、非法 hash/路径；
- 暴露一个领域级安全 display-name 校验入口供 `DemoAsset` 与 manifest 共用，不复制两套规则；
- 正常 round-trip 保持不变。

runtime-bound service：

- `DemoAssetApplicationService.for_runtime(runtime)` 返回绑定服务；
- 绑定后即使全局 workspace selection 改变，import/inspect/resolve 仍只使用原 runtime.paths；
- resolver 模式（现有 `demos` CLI）行为不变；
- 构造时同时缺少或同时提供 resolver/runtime 返回明确 `TypeError`；
- 暴露只读 `bound_runtime`。

manifest：

- `bind_demo_asset()` 产生固定身份字段与 `input_mode=demo_asset`；
- save/load 后 ref/display round-trip，`to_public_dict()` 无绝对路径；
- `map_name/server_name/players` 更新不破坏引用；
- 缺失/非法引用、路径式 display name、未知 input mode 拒绝；
- `mark_legacy_demo_input()` 只设置 legacy mode；
- 旧 manifest 无 input mode 时仍可 load，且 load 不改文件。

确认 RED：

```powershell
py -3.12 -m pytest -q tests/test_demo_asset_models.py tests/test_demo_asset_application.py tests/test_pipeline_demo_assets.py
```

### 5.2 最小实现与 GREEN

- 保持 01E-A CLI 构造兼容；bound service 不重新读取 selection store；
- manifest 方法只操作 `demo` 子结构，不把领域对象塞进 `PipelineConfig`；
- manifest 解析异常由后续应用边界映射，底层不打印路径或 traceback。

```powershell
py -3.12 -m pytest -q tests/test_demo_asset_models.py tests/test_demo_asset_application.py tests/test_pipeline_demo_assets.py tests/test_demo_asset_cli.py tests/test_job_runtime.py tests/test_manifest_paths_v061.py tests/test_secret_redaction.py
git diff --check
```

```powershell
git add src/cs2pov/domain/assets.py src/cs2pov/application/demo_assets.py src/cs2pov/pipeline/manifest.py tests/test_demo_asset_models.py tests/test_demo_asset_application.py tests/test_pipeline_demo_assets.py
git commit -m "feat: bind DemoAsset references to job manifests"
```

Review checkpoint：domain 不依赖 workspace/storage/CLI；bound service 不读取第二次 runtime；manifest 不保存 source/cache/绝对路径。

---

## 6. Task 2：Pipeline 受管输入与 legacy 双轨

**Files：**

- Modify: `src/cs2pov/pipeline/engine.py`
- Modify: `src/cs2pov/services/demo_service.py`
- Modify: `tests/test_pipeline_demo_assets.py`
- Modify: `tests/test_workspace_job_pipeline_batch_b.py`
- Modify as required: existing engine/service tests that intentionally cover legacy behavior

### 6.1 先写受管 Pipeline RED 测试

使用匿名合成 Demo 与真实仓储，后续 demoparser 阶段使用 fake adapter。覆盖：

1. import 后创建受管 Engine，运行到 `PREPARE_INPUT`；
2. `DemoService.prepare_input()` 未调用；
3. `engine.demo_path` 是 library source 或 workspace cache，Job/input 为空；
4. manifest 引用正确、`artifacts` 没有 `demo_path`；
5. `.dem.zst` 删除 cache 后 prepare 自动重建，Job/input 仍空；
6. 外部源在 import 后删除，prepare 仍成功；
7. runtime 不同、参数不完整、ref 与恢复 manifest 不同均安全失败；
8. 当前 workspace 缺素材时不查看 Job/input 中伪造 `.dem`；
9. 受管模式传 Path、legacy 模式不传 Path 都被拒。

### 6.2 inspect / rename / metadata RED 测试

- 受管 inspect 只把安全显示名和 `demo-asset:<id>` 写到 `demo_info.json`；
- manifest、demo_info、progress/error 不出现外部源、workspace root、cache path；
- 自动 Job rename 后 `engine.demo_path` 仍位于素材库/cache；
- 重命名 manifest 保持同一 ref，无 `artifacts.demo_path`；
- 新 Job input 不含文件或链接。

### 6.3 legacy 回归

- `engine.run(Path)` 仍复制/解压到 Job/input；
- legacy manifest 标记 `legacy_job_copy`，没有 asset 字段；
- 旧 manifest fixture 无 input mode 仍可恢复；
- legacy rename 后 demo path 继续跟随 Job/input；
- `DemoService.prepare_input` 外部源只读和同路径 no-op 不变。

### 6.4 实现、GREEN 与 commit

- Engine 不导入 repository 具体实现，只通过 bound application service resolve；
- 受管分支禁止 fallback，legacy 逻辑放在清楚命名的小方法；
- `DemoService.inspect()` 增加可选 public metadata，默认 legacy 行为不变；
- 不修改语音、回合、转录、翻译、字幕服务。

```powershell
py -3.12 -m pytest -q tests/test_pipeline_demo_assets.py tests/test_workspace_job_pipeline_batch_b.py tests/test_demo_asset_repository.py tests/test_demo_asset_concurrency.py tests/test_job_runtime.py
git diff --check
```

```powershell
git add src/cs2pov/pipeline/engine.py src/cs2pov/services/demo_service.py tests/test_pipeline_demo_assets.py tests/test_workspace_job_pipeline_batch_b.py
git commit -m "feat: run new jobs from managed DemoAssets"
```

Review checkpoint：受管 Job 无 Demo 副本/链接/绝对素材路径；legacy 仍通过原有路径；Pipeline 无全局 workspace lookup。

---

## 7. Task 3：正式入口、向导、benchmark 与 resume

**Files：**

- Modify: `src/cs2pov/cli/commands.py`
- Modify: `src/cs2pov/cli/wizard.py`
- Modify: `src/cs2pov/cli/job_ops.py`
- Create if useful: `src/cs2pov/cli/pipeline_demo.py`
- Modify: `tests/test_workspace_job_pipeline_batch_b.py`
- Modify: `tests/test_batch_c_paths.py`
- Modify: `tests/test_wizard_v020.py`
- Modify: benchmark/JSON tests near `tests/test_models_v080.py`
- Modify: `tests/test_pipeline_demo_assets.py`

### 7.1 共享入口顺序

三个新任务入口统一执行：

```text
resolve_for_write once
→ DemoAssetApplicationService.for_runtime(runtime)
→ import_demo(external_path)
→ resolve_asset(ref) preflight
→ 显示 imported / reused
→ JobRuntime
→ PipelineEngine(ref + display + bound service)
→ engine.run(None)
```

不得复制成三套容易漂移的错误映射。允许新增 `pipeline_demo.py`，只负责返回 bound service + `DemoImportResult` 和生成普通用户文案；由调用者选择 stdout/stderr，不自行读取 global runtime。

### 7.2 `cs2pov run`

先写测试证明：

- import/resolve 失败时未构造 Engine、未创建 Job；
- imported 文案为“已导入到当前工作区素材库，之后可重复使用。”；
- reused 文案为“工作区已有相同 Demo，本次直接复用，不再占用一份长期空间。”；
- Engine 收到 ref、display、同一 bound service，`run(None)`；
- `--output` 仍在任务前后各警告一次，资产进入 workspace，不进入 external output；
- 主命令捕获 `DemoAssetUseCaseError`，已知错误无 traceback。

### 7.3 文本向导

先写测试证明：

- “开始准备 demo”确认前不导入；取消时无素材、无 Job；
- 确认后先 import/resolve，再创建 Job；
- Step 1 显示 imported/reused 与素材 ID，不要求手工 `demos import`；
- 两段 `engine.run()` 都传 `None`，共享同一引用；
- summary 只显示安全 basename，不回显素材库/cache 绝对路径；
- Wizard 捕获稳定 DemoAsset 错误并给中文建议，不进入通用 traceback。

### 7.4 `benchmark-asr`

先写测试证明：

- 多模型 benchmark 只 import/resolve 一次，所有模型 Job 共享 ref；
- 每个 Engine 都运行受管输入，不创建 Job Demo 副本；
- 文本模式 imported/reused 可读；
- `--json` 下人类文案只进 stderr，stdout 是一个 JSON 文档；
- report 记录 `demo_asset_id`、`demo_asset_disposition` 与安全 `demo_display`，不记录外部/素材绝对路径；
- import 失败发生在任何 benchmark Job/report 创建前。

### 7.5 `resume`

新引用 Job：

- 从 manifest 解析 ref/display，创建当前 runtime-bound service；
- 如果执行切片包含 `PREPARE_INPUT`、`INSPECT_DEMO`、`EXTRACT_VOICE` 或 `PARSE_ROUNDS`，在 Engine/manifest 写入前 preflight resolve；
- 只执行不需要 Demo 的后段时不因素材暂时缺失而阻塞；
- 需要 Demo 而当前 workspace 不含资产时返回 `demo_asset_not_found`，Job 文件在 preflight 前后字节级不变；
- 不查看 `--demo` 或 Job/input 掩盖新 ref 缺失；如提供 `--demo`，文案说明先显式导入相同素材，本批不自动改变 Job 引用。

旧 Job：

- 继续 `_resolve_demo_for_resume()`，`--demo` 语义不变；
- 不调用 import，不创建 library asset，不删除 Job/input；
- resume 保存时只补 `legacy_job_copy`；
- 只有实际执行切片包含需要 Demo 的阶段时才要求 Demo。使用与 `_slice_stages` 同一来源的 helper，避免两份阶段列表漂移。

### 7.6 GREEN 与 commit

```powershell
py -3.12 -m pytest -q tests/test_pipeline_demo_assets.py tests/test_workspace_job_pipeline_batch_b.py tests/test_batch_c_paths.py tests/test_wizard_v020.py tests/test_models_v080.py tests/test_demo_asset_cli.py
py -3.12 -m pytest -q
git diff --check
```

只 add 实际修改文件，例如：

```powershell
git add src/cs2pov/cli/commands.py src/cs2pov/cli/wizard.py src/cs2pov/cli/job_ops.py src/cs2pov/cli/pipeline_demo.py tests/test_pipeline_demo_assets.py tests/test_workspace_job_pipeline_batch_b.py tests/test_batch_c_paths.py tests/test_wizard_v020.py tests/test_models_v080.py
git commit -m "feat: auto-import DemoAssets for new pipeline jobs"
```

Review checkpoint：`rg` 确认全部正式新任务入口都 import；benchmark 只 import 一次；resume 严格区分 ref/legacy；错误发生在 Job 创建或重写前。

---

## 8. Task 4：真实 Pipeline E2E、CI 与文档

**Files：**

- Create: `scripts/check_workspace_pipeline_demo_asset_e2e.py`
- Modify: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `README.zh.md`
- Modify: `docs/ARCHITECTURE.zh.md`
- Modify: `docs/FAQ.zh.md`
- Modify: `docs/OUTPUT_FILES.zh.md`
- Modify: `docs/TESTING_GUIDE.zh.md`
- Modify: `docs/RELEASE_CHECKLIST.zh.md`
- Modify: `docs/INDEX.zh.md`

### 8.1 真 E2E 原则

脚本必须使用真实 `python -m cs2pov ...`，不得 import Engine、repository、CLI handler 或 monkeypatch。隔离 HOME、USERPROFILE、LOCALAPPDATA、APPDATA、XDG、TMP、cwd、工作区 A/B 和 external output。只运行到 `prepare_input`，所以不需要 CS2、GPU、真实 Demo、demoparser2、PyOgg、Whisper、模型或 API。

### 8.2 E2E 场景

1. 创建匿名合成 `.dem.zst` 与隔离工作区 A；
2. 第一次真实 `cs2pov run ... --map first --to-stage prepare_input`，输出 imported；
3. 第二次相同内容不同压缩字节/文件名运行，输出 reused；
4. library 只有一个 asset，jobs 有两个不同 Job；
5. 两个 manifest 引用同一 ID，`input_mode=demo_asset`，没有 `artifacts.demo_path`；
6. 两个 Job/input 都没有文件、symlink、hardlink 或 junction；
7. manifest 与输出不包含 external path、workspace/cache 解析路径；
8. 显式 `--output` 创建第三个外部 Job，前后警告存在，资产仍只在工作区 A；
9. 删除外部源和解压 cache，对引用 Job resume `prepare_input`，cache 重建且 Job/input 仍空；
10. 初始化并切换工作区 B，对 A Job执行需要 Demo 的 resume，稳定 `demo_asset_not_found`；B 不出现猜测资产，A Job 在失败前后字节不变；
11. 切回 A 后 resume 恢复成功；
12. 最小旧 Job fixture 的 read/legacy resume 不创建 DemoAsset、不删除旧 input、不添加 asset 字段；
13. 损坏 workspace/asset 后新 run 在 Job 创建前失败；
14. 快照源码树、cwd、隔离 HOME、外部源和其他工作区，确认无旁路写入；
15. 打印唯一成功行：

```text
workspace Pipeline DemoAsset E2E passed: auto-import, reference-only jobs, resume, legacy compatibility, and isolation
```

### 8.3 CI

在既有 matrix job、DemoAsset E2E 之后、compileall 之前加入：

```yaml
- name: Exercise Pipeline DemoAsset references end to end
  run: python scripts/check_workspace_pipeline_demo_asset_e2e.py
```

必须覆盖 Ubuntu Python 3.11/3.12/3.13 与 Windows Python 3.12，不另建单平台弱 job。

### 8.4 文档必须诚实更新

- 快速开始：用户仍选择本机 Demo，但程序自动 import/reuse，不必先执行 `demos import`；
- library 是持久素材，decompressed cache 可清，新 Job/input 不再含 Demo；
- `demos import/list/inspect` 仍用于显式整理和诊断；
- 旧 Job 保留 input，不自动迁移；
- 切换 workspace 后引用 Job 需要原工作区素材；
- external `--output` 只改变 Job 位置，不改变素材归属；
- 01E 标记完成，但不宣称旧 Job 迁移、Web UI、理解翻译、POV 录制或最终视频一体化已实现；
- 最终主产物仍是按回合对齐的双语字幕、校对 YAML/HTML 与绿幕/透明 overlay。

### 8.5 本地发布级门禁

严格串行；workspace E2E 在 compileall 之前：

```powershell
py -3.12 -m pytest -q
py -3.12 scripts/check_workspace_cli_e2e.py
py -3.12 scripts/check_workspace_model_runtime_e2e.py
py -3.12 scripts/check_workspace_job_runtime_e2e.py
py -3.12 scripts/check_workspace_demo_asset_e2e.py
py -3.12 scripts/check_workspace_pipeline_demo_asset_e2e.py
py -3.12 scripts/check_golden_baseline.py --replay
py -3.12 scripts/check_repository_hygiene.py --root .
py -3.12 -m compileall -q src tests scripts
py -3.12 scripts/launch_sanity_check.py
git diff --check
git status --short
```

全部 exit 0；新增核心测试不得 skip，平台链接权限 skip 只能是既有、可解释项。

```powershell
git add scripts/check_workspace_pipeline_demo_asset_e2e.py .github/workflows/ci.yml README.md README.zh.md docs/ARCHITECTURE.zh.md docs/FAQ.zh.md docs/OUTPUT_FILES.zh.md docs/TESTING_GUIDE.zh.md docs/RELEASE_CHECKLIST.zh.md docs/INDEX.zh.md
git commit -m "test: gate Pipeline DemoAsset lifecycle"
```

---

## 9. 强审查清单

独立 reviewer 审查 `9059638..HEAD`，至少回答：

- 是否有正式入口仍把 external Path 直接交给 Pipeline；
- 是否可能在 import/resolve 失败前创建 Job、重写旧 Job 或产生 external output；
- bound service 是否重新读取 global workspace selection；
- manifest/ref 字段篡改是否能逃逸当前 workspace；
- 新 Job 是否可能通过 prepare、rename、resume 或 cache repair 产生 Demo/链接；
- `_require_demo_path` 是否在 ref 失败后降级到 Job/input；
- cache 删除/损坏、持久源损坏与 workspace 切换是否安全；
- demo_info、manifest、JSON、日志、反馈包是否泄露 external/asset 绝对路径；
- benchmark 是否每模型重复 import 或污染 JSON stdout；
- legacy Job 是否被隐式导入、删除 input 或改变引用；
- 后段 resume 是否被无关素材缺失阻塞；
- E2E 是否真 subprocess、真新 Job、真 workspace switch；
- 最终回合字幕与 overlay 数据流是否保持不变。

分类 Critical / Important / Minor。任何 Critical/Important 未关闭，不得 push/merge。

---

## 10. GitHub 交付门禁

本地全绿、独立复审无 Critical/Important 后：

1. push `feature/luna-01e-b-pipeline`；
2. 创建独立 PR，不混入阶段 1.3；
3. 等待 push + PR 的全部 GitHub checks；
4. Ubuntu 3.11/3.12/3.13、Windows 3.12 全部成功；
5. 自动 merge；
6. fast-forward 本地 master；
7. 验证工作树干净；
8. 删除已合并 worktree、本地分支和远端分支。

---

## 11. 01E-B 完成定义

- 新 run、向导、benchmark 自动 import/reuse，用户无需额外技术步骤；
- 相同逻辑 Demo 的多个新 Job 共享一个 DemoAsset；
- 新 Job manifest 只有相对引用和安全显示名；
- 新 Job/input 无 Demo、链接或隐藏副本；
- cache 可删并从持久源自动重建；
- 删除 external source 不影响引用 Job resume；
- workspace switch 不会跨盘猜素材；
- external `--output` Job 仍引用当前 workspace asset 并保留警告；
- 旧 Job 不迁移、不丢 input 且可 resume；
- 后续语音、回合、转录、翻译、双语字幕与绿幕 overlay 逻辑未改变；
- 本地全量、五条 workspace E2E、金标准、卫生、编译、启动全绿；
- 独立强审查关闭全部 Critical/Important；
- GitHub 全矩阵通过，PR 合并，本地/远端 master 同步。

完成后进入阶段 1.3：旧 Job 只读扫描、迁移报告与幂等导入。不得在 01E-B 中提前做迁移。
