# Luna-01D-A：工作区运行时与模型缓存接入任务书

- 日期：2026-08-31
- 状态：已实施并完成本地审查
- 设计依据：`docs/plans/2026-08-31-workspace-runtime-paths-design.zh.md`
- 基线：`master` 合并提交 `c32b099`
- 工作分支：`feature/luna-01d-a-runtime-paths`
- 实施模型：Luna
- 审查模型：主任务强模型

## 1. 任务目标

本任务只完成 Luna-01D-A：建立当前工作区的不可变运行时快照，并让模型管理、模型加载测试和 faster-whisper 显式使用工作区缓存。

完成后必须真实满足：

1. `models test` 没有健康当前工作区时，在构造模型前失败；
2. `models test` 实际传给 `WhisperModel` 的 `download_root` 是 `workspace/cache/whisper`；
3. 模型查看只把工作区缓存列为当前受管缓存，旧 C 盘/用户缓存单独只读提示；
4. 旧 `whisper_cache_dir` 配置和 CLI 覆盖不能改变运行路径；
5. `FasterWhisperAdapter` 不再修改 `os.environ`；
6. Windows/Ubuntu CI 通过真实子进程验证这些事实。

本任务不接入 `run`、向导、Pipeline、Demo 或 Job。那些属于 Luna-01D-B。

## 2. 开始前必须执行

在任何实现代码前：

1. 完整阅读：
   - `docs/plans/2026-08-31-workspace-runtime-paths-design.zh.md`
   - 本任务书；
   - `src/cs2pov/application/workspace.py`
   - `src/cs2pov/workspace/paths.py`
   - `src/cs2pov/workspace/service.py`
   - `src/cs2pov/storage/workspace_selection_store.py`
   - `src/cs2pov/cli/model_manager.py`
   - `src/cs2pov/adapters/whisper_adapter.py`
   - `src/cs2pov/cli/commands.py` 中模型/config 解析与分发；
   - `src/cs2pov/cli/launcher.py` 的模型菜单；
   - 相关现有测试和 CI。
2. 阅读并遵守 `superpowers:test-driven-development`；写测试前完整阅读其 `writing-good-tests.md`。
3. 确认当前目录是已隔离工作树、当前分支正确且工作区干净。
4. 运行基线：

```powershell
python -m pytest -q
python scripts/check_workspace_cli_e2e.py
git status --short
```

若计划与代码实际情况冲突，先报告，不得自行扩大范围。

## 3. TDD 与提交纪律

每个行为必须按以下顺序：

1. 先写一个最小、以行为命名的测试；
2. 运行该测试并记录预期 RED；
3. 写最小实现；
4. 运行目标测试并记录 GREEN；
5. 运行本批相关回归；
6. 只在全绿后重构；
7. 每批形成一个聚焦提交并停止，等待强模型审查。

禁止：

- 先写生产代码再补测试；
- 用 mock 只断言“某函数被调用”来代替真实路径/文件系统结果；
- 为让测试通过而弱化断言；
- 把测试专用分支、环境变量或假模型逻辑加入生产代码；
- 将多个批次一次性做完后再报告。

每批报告必须包含：修改文件、RED 命令与失败原因、GREEN 命令、回归结果、提交哈希、未解决风险。

## 4. 允许修改范围

允许新增或修改：

```text
src/cs2pov/application/workspace_runtime.py       # 新增
src/cs2pov/cli/model_manager.py
src/cs2pov/adapters/whisper_adapter.py
src/cs2pov/storage/config_store.py
src/cs2pov/cli/commands.py                        # 仅 runtime/model/config 相关
src/cs2pov/cli/launcher.py                        # 仅模型菜单文案/分发
src/cs2pov/application/__init__.py                 # 仅确有导出需要时
tests/test_workspace_runtime.py                    # 新增
tests/test_models_v080.py
tests/test_whisper_adapter.py                      # 新增或使用现有同类文件
tests/test_llm_model_maintenance.py                # 仅旧配置展示相关
tests/test_launcher_navigation.py                  # 仅模型菜单相关
scripts/check_workspace_model_runtime_e2e.py       # 新增
.github/workflows/ci.yml
docs/TESTING_GUIDE.zh.md                           # 只更新相关命令
docs/ARCHITECTURE.zh.md                            # 只更新运行时说明
```

若发现现有测试文件名称略有不同，可以使用最接近的现有文件；不得借机重排整个测试目录。

禁止修改：

```text
src/cs2pov/pipeline/**
src/cs2pov/services/demo_service.py
src/cs2pov/services/transcription_service.py
src/cs2pov/storage/artifact_store.py
src/cs2pov/cli/wizard.py
src/cs2pov/cli/job_ops.py
src/cs2pov/domain/models.py
Demo/**
apikey.txt
版本号、依赖、release workflow、golden 基线数据
```

尤其不得在 01D-A 中修改 `run --output`、`PipelineConfig.output_root`、Demo 副本或临时音频；这些属于 01D-B。

## 5. 批次 A：不可变 WorkspaceRuntime

### 5.1 先写测试

新增 `tests/test_workspace_runtime.py`，至少逐项覆盖：

1. `resolve_selected()` 在没有选择时抛出稳定应用错误 `workspace_selection_required`；
2. 选择状态文件损坏/不可读时保留已有 selection store 错误代码，不伪装成“未选择”；
3. 已选择但 `workspace.json` 缺失或损坏时返回 `workspace_unhealthy`，并附带底层诊断；
4. `resolve_for_write()` 对目录缺失、不可写和空间不足返回 `workspace_unhealthy`，不修复、不创建目录、不改变选择；
5. 健康工作区生成的运行时包含正确 workspace ID、schema/layout 版本和路径政策版本；
6. 所有模型/HF/temp/Job 路径都从同一个规范根目录推导；
7. 运行时 dataclass 字段不可重新赋值；
8. 切换 selection port 后，旧运行时的 root、workspace ID 和派生路径保持不变；
9. `environment_overrides()` 每次返回独立副本，调用者修改副本不会污染运行时；
10. `subprocess_environment(base)` 返回新字典，保留无关 base 项，并用工作区值覆盖六个受管变量；
11. 解析运行时不调用 `os.environ.update/setdefault`，父进程环境原样不变；
12. 意外的普通 `RuntimeError` 不得被广泛捕获并伪装成工作区错误。

测试必须使用真实 `WorkspaceService` 覆盖至少健康、缺配置和布局缺失三条路径。端口/磁盘空间等难以稳定制造的分支可以做窄依赖注入，但不得只断言 mock 调用次数。

先运行：

```powershell
python -m pytest tests/test_workspace_runtime.py -q
```

确认因模块/API 尚不存在而 RED。

### 5.2 实现契约

建议新增以下公开对象；如有更小且等价的接口，可在批次开始前说明，但不得改变语义：

```python
WORKSPACE_PATH_POLICY_VERSION = 1

@dataclass(frozen=True, slots=True)
class WorkspaceRuntime:
    root: Path
    workspace_id: str
    workspace_schema_version: int
    workspace_layout_version: int
    path_policy_version: int = WORKSPACE_PATH_POLICY_VERSION

    @property
    def paths(self) -> WorkspacePaths: ...

    def environment_overrides(self) -> dict[str, str]: ...
    def subprocess_environment(self, base: Mapping[str, str] | None = None) -> dict[str, str]: ...

class WorkspaceRuntimeError(WorkspaceError):
    code: str
    message_zh: str
    suggestion_zh: str
    diagnostic: WorkspaceDiagnostic | None

class WorkspaceRuntimeResolver:
    def __init__(self, selection_port: WorkspaceSelectionPort, *, workspace_service_factory=WorkspaceService): ...
    def resolve_selected(self) -> WorkspaceRuntime: ...
    def resolve_for_write(self) -> WorkspaceRuntime: ...
```

语义：

- `resolve_selected()` 要求选择状态和 `workspace.json` 有效，但不因低空间或不可写阻止只读路径展示；
- `resolve_for_write()` 额外要求完整诊断 `ok=True`；
- 两者都不得初始化、补目录或保存 selection；
- 缺少选择固定使用 `workspace_selection_required`；
- 选中工作区不能安全使用时使用 `workspace_unhealthy`，`diagnostic` 保留具体 issue；
- selection store 的结构化读错误保留原 code/message/suggestion；
- `root` 必须在构造运行时前规范化；
- 派生路径通过新的 `WorkspacePaths(root)` 计算，不保存可被后来切换的全局引用；
- 环境覆盖至少包含 `HF_HOME`、`HF_HUB_CACHE`、`HUGGINGFACE_HUB_CACHE`、`TMP`、`TEMP`、`TMPDIR`；
- 不得存储或读取 API Key、LLM 配置和旧模型缓存路径。

`subprocess_environment(None)` 可以复制当前 `os.environ`，但不得修改它。若为了更纯的 API 选择要求显式 base，需在实现前报告并保持所有调用一致。

### 5.3 批次 A 验证与提交

```powershell
python -m pytest tests/test_workspace_runtime.py tests/test_workspace_application.py tests/test_workspace_service.py tests/test_workspace_selection_store.py tests/test_workspace_paths.py -q
python scripts/check_workspace_cli_e2e.py
python -m compileall -q src tests
git diff --check
```

提交建议：

```text
feat: add immutable workspace runtime resolver
```

提交后停止并报告，等待审查。

## 6. 批次 B：模型缓存与弃用兼容

本批必须建立在批次 A 已审查通过的提交上。

### 6.1 先写模型管理测试

修改 `tests/test_models_v080.py`，按行为拆分测试，至少覆盖：

1. 工作区模型扫描只读取 `cache/whisper` 和 `cache/huggingface/hub`；
2. 不读取 cwd、默认 HOME 或环境变量指定的外部目录作为“当前可用缓存”；
3. 工作区两个缓存根中重复模型按规范路径去重；
4. 扫描不存在目录不会创建目录；
5. 返回行明确包含 `managed=True` 和缓存来源；
6. 旧配置路径、`HF_HOME`、`HF_HUB_CACHE`、平台默认 HF 路径可以只读列为 legacy candidates；
7. legacy candidates 位于当前工作区内时必须排除；
8. 重复 legacy 路径规范化去重；
9. 不存在的 legacy 目录不创建、不报告为已检测缓存；
10. `build_models_info` 明确返回当前工作区缓存、弃用配置状态和旧缓存列表；
11. `test_model_load` 必须由调用方传入现有工作区缓存路径，没有路径时拒绝，不回退；
12. `test_model_load` 实际把路径作为 `download_root` 传给 fake `WhisperModel`；
13. `local_only=True` 实际传递 `local_files_only=True`；
14. 模型构造异常保持结构化失败结果，不打印密钥或 traceback。

扫描函数不得内部调用 `load_config()`、读取全局路径后决定当前缓存。旧配置和环境必须由调用边界显式传入只读检测函数，便于证明没有隐式回退。

### 6.2 先写 Whisper 适配器测试

新增或修改适配器测试，至少覆盖：

1. 传入缓存路径时实际得到 `download_root`；
2. 构造前后 `os.environ` 完全相同；
3. 现有缓存目录不会被改写为 HF 全局环境；
4. 未传路径时不修改环境，维持旧调用兼容；
5. 外部库导入失败仍保留原有中文错误。

这里允许用窄 fake module 捕获第三方构造参数；断言目标是生产适配器传递的真实 kwargs 和全局环境结果，而不是调用次数。

### 6.3 模型管理实现规则

重构 `model_manager.py` 时遵守：

- 当前受管缓存由 `WorkspaceRuntime.paths.whisper_cache_dir` 和 `huggingface_hub_cache_dir` 显式提供；
- 当前模型扫描与 legacy 扫描是两个独立函数/结果，不混成候选优先级；
- faster-whisper 下载根使用 `cache/whisper`；
- Hugging Face 通用 hub 使用 `cache/huggingface/hub`；
- 所有扫描只读，不调用 `mkdir`；
- `test_model_load` 不从 config、env、HOME 或 cwd 猜缓存；
- 不自动复制、移动、删除或加载 legacy cache；
- 不执行递归删除；
- 不新增依赖。

可保留 `format_bytes`、模型目录识别和档位逻辑，但路径来源必须显式。

### 6.4 CLI 行为测试与实现

为 `commands.py` 的模型/config 分支补充测试：

#### `models info --json`

- 有选中工作区时返回 JSON，包含工作区缓存位置、当前默认模型、旧配置是否存在和只读 legacy 列表；
- 没有选择时返回 code 1、稳定 JSON 错误 `workspace_selection_required`，无 traceback；
- 只需 `resolve_selected()`，即使低空间也能显示路径和迁移信息；损坏配置仍失败。

#### `models list --json`

- 只列受管工作区模型为 current；
- legacy 模型单独字段显示；
- 不因扫描创建任何目录。

#### `models test --json`

- 必须使用 `resolve_for_write()`；
- 没有/损坏工作区时，在导入或构造 fake `WhisperModel` 前失败；
- 成功结果的 `cache_dir` 是工作区 Whisper cache；
- 显式 `--cache-dir` 返回 `legacy_model_cache_override_rejected`，不构造模型、不创建该目录。

统一 JSON 错误形状：

```json
{
  "ok": false,
  "command": "models.test",
  "error": {
    "code": "workspace_selection_required",
    "message_zh": "...",
    "suggestion_zh": "..."
  }
}
```

若有 diagnostic，放到顶层 `diagnostic`。JSON stdout 前后不得有额外文本。

#### 弃用入口

- `models set-cache PATH` 保留解析入口，但不创建 PATH、不保存配置，返回非零和中文迁移说明；
- `models test --cache-dir PATH` 同样拒绝；
- `config set --whisper-cache-dir PATH` 原子拒绝整个 config set，不得部分保存同一次命令的其他字段；
- `config show`/`mask_config_for_display` 对已有 `whisper_cache_dir` 增加弃用标志和说明，但不改写原文件；
- 本批不修改 `run --whisper-cache-dir` 和 `benchmark-asr --cache-dir`，由 01D-B 与 Pipeline 一起处理。

非 JSON 模式必须给出普通用户可执行建议，例如先运行 `cs2pov workspace init <绝对路径>` 或 `cs2pov workspace use <绝对路径>`。模型错误不得落入 `main()` 的广泛异常分支后重新抛出 traceback。

### 6.5 文本启动器模型菜单

只修改模型菜单：

- 首页说明模型跟随当前工作区；
- 删除“设置模型缓存目录到 D 盘/自定义目录”的推荐；
- 原第 4 项改为“查看旧缓存迁移说明”，复用模型信息，不写路径；
- 模型加载测试继续使用当前工作区；
- 不改其他菜单编号、Job 默认路径或向导。

### 6.6 批次 B 验证与提交

```powershell
python -m pytest tests/test_workspace_runtime.py tests/test_models_v080.py tests/test_whisper_adapter.py tests/test_llm_model_maintenance.py tests/test_launcher_navigation.py -q
python -m pytest -q
python scripts/check_workspace_cli_e2e.py
python -m compileall -q src tests
git diff --check
```

提交建议：

```text
feat: bind model caches to selected workspace
```

提交后停止并报告，等待审查。

## 7. 批次 C：真实子进程 E2E、CI 与文档

本批必须建立在批次 B 已审查通过的提交上。

### 7.1 新增真实 E2E 脚本

新增 `scripts/check_workspace_model_runtime_e2e.py`。脚本必须用 `subprocess.run` 启动多个真实 Python CLI 进程，不得导入 handler 直接调用。

在单个 `TemporaryDirectory` 下建立完全隔离的：

```text
cwd/
HOME/
LOCALAPPDATA/
XDG/
state/state.json
workspace/
legacy-configured-cache/
legacy-env-cache/
fake-modules/faster_whisper/
fake-record.json
```

设置 `PYTHONPATH` 时让 `fake-modules` 位于源码 `src` 前。测试用 `faster_whisper.WhisperModel` 在构造时把 model 和 kwargs 写入 `fake-record.json`；这是测试模块行为，生产代码不得知道记录环境变量。

按顺序验证：

1. 未选择工作区执行 `models test --model base --json`：code 1、错误为 `workspace_selection_required`、无记录文件、无 traceback；
2. 通过真实 CLI 初始化并选择中文/空格路径工作区；
3. 在隔离 HOME 写入旧 `~/.cs2pov/config.json`，其中 `whisper_cache_dir` 指向 legacy-configured-cache；
4. 设置 `HF_HOME/HF_HUB_CACHE` 指向 legacy-env-cache，并放入只读 marker/假模型目录；
5. 执行 `models info --json`：当前缓存是工作区，旧配置和 legacy 路径只作为弃用/只读信息出现；
6. 执行 `models test --model base --json`：成功，记录的 `download_root` 精确等于 `workspace/cache/whisper`；
7. 记录中没有 legacy/cwd/HOME 路径；legacy markers 和目录快照不变；
8. 执行 `models test --cache-dir <new-external-path> --json`：拒绝、外部路径未创建、fake record 未变化；
9. 删除或破坏一个受管 cache 目录后清除 record，再执行模型测试：在构造模型前失败、无新 record、无半修复；
10. 父进程和各监控目录除预期 state/config/workspace 外没有新资产。

脚本必须自行把 AssertionError 转成清晰 stderr 和 code 1；成功输出一行摘要。

### 7.2 CI

在 `.github/workflows/ci.yml` 所有矩阵中，紧跟现有 workspace CLI E2E 增加：

```yaml
- name: Exercise workspace model runtime end to end
  run: python scripts/check_workspace_model_runtime_e2e.py
```

不降低现有矩阵、不加 `continue-on-error`、不跳过 Windows。

### 7.3 文档

只更新与本任务已实现行为一致的内容：

- 模型缓存跟随当前工作区；
- 旧缓存只读提示、不自动迁移；
- 新的模型 E2E 命令；
- `models set-cache` 和旧 cache override 已弃用；
- 明确 `run`、Job、Demo、临时音频尚待 01D-B 接入，避免宣称文件管理已全部完成。

### 7.4 批次 C 验证与提交

```powershell
python scripts/check_repository_hygiene.py --root .
python scripts/check_golden_baseline.py --replay
python scripts/check_workspace_cli_e2e.py
python scripts/check_workspace_model_runtime_e2e.py
python -m pytest -q
python -m compileall -q src tests scripts
python scripts/launch_sanity_check.py
git diff --check
git status --short
```

提交建议：

```text
test: verify workspace model paths end to end
```

提交后停止并报告，等待最终强审查。

## 8. 强制审查点

主任务强模型会重点检查：

- runtime 是否真的不可变且不修复选中工作区；
- `resolve_selected` 与 `resolve_for_write` 是否没有混淆；
- 模型路径是否仍存在 config/env/HOME/cwd 隐式回退；
- old cache 是否可能被创建、写入、加载或混入 current 列表；
- `os.environ` 是否被任何新代码或适配器修改；
- CLI JSON 是否始终可解析且错误无 traceback；
- `models set-cache`、`--cache-dir`、config set 是否真的零写入；
- E2E 是否启动真实子进程并检查 fake Whisper 的实际 kwargs；
- E2E 是否可能因为只检查预设属性而假绿；
- 是否越界修改了 Pipeline、Job、Demo、向导或版本号。

发现缺陷后必须先增加/收紧失败测试，再修复，不得直接改代码。

## 9. PR 前最终门禁

只有同时满足以下条件才允许创建 PR：

1. 三批提交均经过主任务强模型审查；
2. 工作树只包含本任务范围内文件；
3. 全量测试与两个 workspace E2E 通过；
4. Windows/Ubuntu GitHub CI 全绿；
5. PR 描述明确写出 01D-B 尚未完成，不能宣称所有旧管线已经接入；
6. 不包含 Demo、模型、缓存、输出、秘密或本机状态文件；
7. 不修改版本号、不创建 tag/release；
8. 用户明确确认后才合并。
