# Luna-01C：工作区选择、CLI 与文本启动器入口

- 状态：可分批实施
- 基线提交：`3a4ec71`
- 所属阶段：阶段 1.1「Workspace 配置与路径策略」
- 设计依据：`docs/plans/2026-08-31-workspace-entry-design.zh.md`
- 前置任务：Luna-01A、Luna-01B
- 实施模型：Luna
- 审查模型：主任务强模型

## 1. 目标

在已经合并的 `WorkspacePaths` 和 `WorkspaceService` 之上增加：

1. 只保存“最后选择工作区路径”的严格状态存储；
2. 与 CLI/Web 无关的工作区应用用例；
3. `cs2pov workspace init/use/show/doctor/forget`；
4. 现有双击文本启动器中的工作区管理入口；
5. 独立、跨进程、真实文件系统的 CLI 与启动器 E2E；
6. GitHub Actions 独立 E2E 步骤。

必须保持以下底线：LocalAppData 只保存无秘密的路径指针；模型、Demo、Job、知识、缓存和输出仍不得写入 LocalAppData。没有有效选择时不得回退到当前目录、源码目录、用户主目录或系统盘资产目录。

本任务分两个检查点。先只实施批次 A，提交并停下供强模型审查；收到继续指令后才实施批次 B。

## 2. 开始前

完整阅读：

```text
docs/plans/2026-08-31-workspace-entry-design.zh.md
docs/tasks/LUNA-01B-WORKSPACE-SERVICE.zh.md
src/cs2pov/workspace/paths.py
src/cs2pov/workspace/models.py
src/cs2pov/workspace/service.py
src/cs2pov/workspace/errors.py
src/cs2pov/cli/commands.py
src/cs2pov/cli/launcher.py
```

执行并记录基线：

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

若基线失败，停止并报告，不要猜测修复。

## 3. 强制 TDD

每一个生产行为必须按 RED → GREEN → REFACTOR：

1. 先写一个描述用户可观察行为的最小测试；
2. 运行测试并确认因为目标功能缺失而失败，不是导入错误或测试拼写错误；
3. 在工作报告中保留 RED 命令、失败测试名和一行预期失败原因；
4. 写使该测试通过的最小实现；
5. 运行目标测试及受影响旧测试；
6. 再进入下一行为。

测试必须断言真实结果、文件系统副作用和退出码。不得通过 grep 源码、断言 mock 自身或复用被测代码计算 expected 来制造通过。只有磁盘空间、时间、UUID、失败注入等不可稳定依赖才允许使用窄注入。

若发现生产代码先于对应失败测试出现，删除该生产代码并重新走 RED；不得补写测试冒充 TDD。

## 4. 批次 A：状态存储与应用服务

### 4.1 文件范围

新增：

```text
src/cs2pov/application/__init__.py
src/cs2pov/application/workspace.py
src/cs2pov/storage/workspace_selection_store.py
tests/test_workspace_selection_store.py
tests/test_workspace_application.py
```

批次 A 允许最小修改：

```text
src/cs2pov/workspace/errors.py
src/cs2pov/workspace/__init__.py
```

批次 A 禁止修改 CLI、启动器、CI、版本号、旧配置、PipelineConfig、ArtifactStore、模型管理或旧测试。

### 4.2 应用模型与端口

在 `application/workspace.py` 定义不可变、可 JSON 序列化的模型：

```python
SELECTION_SCHEMA_VERSION = 1

@dataclass(frozen=True, slots=True)
class WorkspaceSelection:
    schema_version: int
    selected_workspace: str

    def to_dict(self) -> dict[str, object]: ...
    @classmethod
    def from_dict(cls, value: object) -> "WorkspaceSelection": ...

@dataclass(frozen=True, slots=True)
class WorkspaceView:
    selected_workspace: str
    diagnostic: WorkspaceDiagnostic

    def to_dict(self) -> dict[str, object]: ...

@dataclass(frozen=True, slots=True)
class ForgetWorkspaceResult:
    forgotten: bool

    def to_dict(self) -> dict[str, object]: ...
```

`WorkspaceSelection` 精确规则：

- 只允许 `schema_version` 和 `selected_workspace` 两个键；
- 版本必须是精确整数 `1`，拒绝 `True`；
- 路径必须是非空绝对路径；
- 使用 `WorkspacePaths` 取得规范化绝对根路径并保存为字符串；
- `to_dict()` 键顺序固定；
- 不得包含 API Key、模型、Demo、Job、SteamID 或缓存字段。

定义端口：

```python
class WorkspaceSelectionPort(Protocol):
    def load(self) -> WorkspaceSelection | None: ...
    def save(self, selection: WorkspaceSelection) -> None: ...
    def forget(self) -> bool: ...
```

协议必须可以由简单 fake 实现；不要让测试 fake 继承生产持久化类。

### 4.3 稳定应用错误

定义一个包含以下公开属性的应用边界异常：

```python
class WorkspaceUseCaseError(WorkspaceError):
    code: str
    message_zh: str
    suggestion_zh: str
    diagnostic: WorkspaceDiagnostic | None
```

构造后的 `str(error)` 只返回 `message_zh`。不得把绝对路径或秘密拼入错误消息。

状态存储使用以下代码：

- `selection_missing`
- `selection_state_invalid`
- `selection_state_location_unavailable`
- `selection_state_read_failed`
- `selection_state_write_failed`
- `selection_state_forget_failed`

应用服务还需稳定映射：

- `WorkspaceRootRequiredError` → `workspace_root_invalid`
- `WorkspaceInsufficientSpaceError` → `workspace_space_low`
- `WorkspaceNotWritableError` → `workspace_not_writable`
- `WorkspaceConfigError` → `workspace_config_invalid`
- `WorkspaceLayoutError` → `workspace_layout_invalid`
- 其他 `WorkspaceInitializationError` → `workspace_initialization_failed`

如果已经获得 `WorkspaceDiagnostic` 且含 issue，优先使用第一个 issue 的 code、message 和 suggestion，并把完整 diagnostic 附在异常上。

### 4.4 JSON 状态存储

`JsonWorkspaceSelectionStore(state_file: str | Path)`：

1. 构造时要求非空绝对状态文件路径，不创建目录；无效位置抛 `selection_state_location_unavailable`；
2. `load()`：文件不存在返回 `None`；不得创建父目录；
3. 状态路径是符号链接或不是普通文件时抛 `selection_state_invalid`，不得跟随读取；
4. JSON、编码、schema 或路径无效时抛 `selection_state_invalid`；普通读取 I/O 失败抛 `selection_state_read_failed`；
5. `save()` 只接受 `WorkspaceSelection`；显式保存时创建状态父目录；
6. 以 UTF-8、两空格缩进、末尾换行写入同目录唯一临时文件，flush + fsync 后 `os.replace`；
7. 任一写入失败抛 `selection_state_write_failed` 并清理本次临时文件；不得删除旧有效状态；
8. 允许显式保存原子覆盖无效旧状态；如果旧状态是符号链接，必须替换链接本身而不是写入其目标；
9. `forget()`：文件不存在返回 `False` 且不创建目录；普通文件或符号链接只 unlink 状态项并返回 `True`；失败抛 `selection_state_forget_failed`；
10. `forget()` 不删除父目录、不读取或访问 `selected_workspace`、不触碰同目录其他文件。

生产状态路径解析函数不得在默认参数中捕获 `os.environ` 或 `Path.home()`，便于测试注入。顺序固定：

1. `CS2POV_STATE_FILE`：非空绝对路径，否则错误；
2. Windows：绝对 `%LOCALAPPDATA%\CS2POV\state.json`，缺失/相对值错误；
3. 非 Windows：绝对 `XDG_STATE_HOME/cs2pov/state.json`；若未设置，使用 `home/.local/state/cs2pov/state.json`；
4. 解析路径不得创建文件或目录。

### 4.5 `WorkspaceApplicationService`

构造函数接收 `WorkspaceSelectionPort` 和可注入的 `WorkspaceService` 工厂。不要访问环境变量或默认状态目录。

公开方法：

```python
initialize_and_select(root: str | Path) -> WorkspaceView
select_existing(root: str | Path) -> WorkspaceView
show_current() -> WorkspaceView
diagnose(root: str | Path | None = None) -> WorkspaceView
forget_current() -> ForgetWorkspaceResult
```

语义：

- `initialize_and_select`：初始化 → 只读诊断 → 仅当 `diagnostic.ok` 时保存；前两步失败保留旧选择；保存失败不删除已经初始化的工作区；
- `select_existing`：只读 `load_config` 和 `diagnose`，不得调用 `initialize`；仅健康时保存；失败保留旧选择；
- `show_current`：无选择抛 `selection_missing`；有选择时返回路径和当前诊断；磁盘后来丢失仍保留选择；
- `diagnose(root)`：显式路径只诊断，不改变选择；`None` 使用当前选择；
- `forget_current`：只调用 port 的 `forget`，幂等返回结果；
- 所有返回模型的 `to_dict()` 必须可直接 `json.dumps`；
- 不修改 `os.environ`，不创建模型/Demo/Job/输出，不打印文本。

### 4.6 批次 A 必测行为

状态存储至少覆盖：

1. 精确 schema 往返和规范路径；
2. 未知键、错误/布尔版本、空/相对路径；
3. 中文和空格路径；
4. 不存在状态只读加载不创建父目录；
5. 损坏 JSON、目录状态路径、符号链接；
6. 原子写入并保留旧状态直到 replace；
7. 模拟 open/write/fsync/replace 失败且无临时文件遗留；
8. `forget` 不存在、普通文件、符号链接和 unlink 失败；
9. `forget` 不删除工作区或同目录其他文件；
10. 默认路径各分支与无效环境值，解析不写盘。

应用服务至少覆盖：

1. 初始化成功后才保存；
2. 初始化失败、诊断失败、状态保存失败时的旧选择与磁盘状态；
3. 初始化成功但选择保存失败后工作区仍可 `use` 恢复；
4. `use` 不创建或补齐目录；
5. `use` 的配置/布局/空间失败不改变旧选择；
6. 当前工作区后来消失仍保留选择并返回诊断；
7. 显式 doctor 不改变选择；
8. 无选择 show/doctor；
9. forget 幂等且不访问工作区；
10. 异常映射和返回 JSON 可序列化。

尽量使用真实临时目录与真实 `WorkspaceService`；只有磁盘空间/权限等不可稳定条件使用注入。fake 只记录 port 的真实边界行为，不断言 fake 本身“被调用了”来代替状态结果。

### 4.7 批次 A 验证与提交

```powershell
..\..\.venv\Scripts\python.exe -m pytest tests/test_workspace_selection_store.py tests/test_workspace_application.py tests/test_workspace_service.py tests/test_workspace_paths.py -q -p no:cacheprovider
..\..\.venv\Scripts\python.exe scripts/check_golden_baseline.py --replay
..\..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
..\..\.venv\Scripts\python.exe scripts/check_repository_hygiene.py --root .
..\..\.venv\Scripts\python.exe -m compileall -q src tests scripts
git diff --check
git status --short
```

检查只修改批次 A 允许文件后提交：

```text
feat: add workspace selection application service
```

提交后停止，报告：

- 每组 RED 的命令、失败测试名和预期原因；
- 最终验证结果；
- 提交哈希；
- 已知限制或疑问。

不要开始批次 B，不要推送、创建 PR 或合并。

## 5. 批次 A 强模型审查门禁

将拒绝以下实现：

- 构造或只读加载时创建 LocalAppData 目录；
- 状态文件出现两字段以外内容或秘密；
- 相对状态/工作区路径被接受；
- 写状态不原子、覆盖失败丢失旧状态或遗留临时文件；
- `forget` 读取路径后删除工作区；
- `use` 调用初始化或修复目录；
- 初始化失败覆盖旧选择；
- 应用层读取 argparse、打印、修改环境变量；
- 用 mock 调用次数代替真实状态断言；
- 没有可验证 RED 证据。

## 6. 批次 B：CLI、文本菜单与真实 E2E

批次 B 只有在强模型明确回复批次 A 通过后实施。

### 6.1 文件范围

新增：

```text
src/cs2pov/cli/workspace_commands.py
tests/test_workspace_cli.py
scripts/check_workspace_cli_e2e.py
```

允许最小修改：

```text
src/cs2pov/cli/commands.py
src/cs2pov/cli/launcher.py
tests/test_launcher_navigation.py
.github/workflows/ci.yml
```

如真实启动器子进程验收需要，可新增一个聚焦测试文件或把逻辑放入同一 E2E 脚本；必须在报告中说明。不得修改旧管线、模型管理、旧配置、版本号和发布脚本。

### 6.2 CLI

注册：

```text
cs2pov workspace init PATH [--json]
cs2pov workspace use PATH [--json]
cs2pov workspace show [--json]
cs2pov workspace doctor [PATH] [--json]
cs2pov workspace forget [--json]
```

`commands.py` 只注册 parser 和转发 dispatch。状态路径解析、应用组合、用例执行、文本/JSON转换集中在 `workspace_commands.py`，但业务语义仍在应用服务，不在 CLI 复制。

JSON stdout 必须恰好一个文档。成功字段：

```text
ok, command, selected_workspace, diagnostic
```

`forget` 增加 `forgotten`，路径和诊断为 null。错误字段：

```text
ok=false, command, error={code,message_zh,suggestion_zh}
```

若错误带 diagnostic，同时返回完整 diagnostic。不要在 JSON 前后打印提示。

退出码：成功/健康 doctor 为 0，已知可恢复问题为 1，argparse 用法为 2。已知 `WorkspaceUseCaseError` 不打印 traceback。文本模式显示路径、状态、下一步和是否改变选择。

### 6.3 文本启动器

“设置与高级工具”增加“工作区管理”，支持 init/use/show/doctor/forget。首页显示只读状态且不得创建状态目录。

必须显示：

```text
当前步骤只设置新版本数据目录；模型和任务接入将在下一阶段完成。
忘记选择只删除路径指针，不会删除工作区文件。
```

菜单调用同一应用服务/CLI 组合函数，不复制业务逻辑。取消和返回遵循现有 `_read_choice` / `ReturnToMainMenu` 语义。

### 6.4 独立跨进程 E2E

`scripts/check_workspace_cli_e2e.py` 必须用 `subprocess.run` 启动多个真实解释器进程，不得导入 CLI handler 直接调用。使用 `tempfile.TemporaryDirectory` 建立：

- 中文加空格状态路径；
- 隔离 HOME/LOCALAPPDATA/XDG 位置；
- 工作区 A、B；
- 与源码不同的当前目录。

通过绝对 `CS2POV_STATE_FILE` 隔离状态，依次真实执行：

```text
init A --json
show --json（新进程）
doctor --json
init B --json
use A --json
show --json（新进程）
forget --json
show --json（预期退出 1）
```

随后通过子进程 stdin 驱动 `python -m cs2pov.cli.launcher --once` 初始化 B，再由新 CLI 进程 show 验证。

必须断言：

- 每次 JSON 可由 `json.loads(stdout)` 解析；
- 退出码符合契约，stderr 无 traceback；
- 跨进程选择正确；
- 两个工作区配置 ID 在 use/forget 前后不变；
- `workspace.json` 不含根路径和秘密；
- 状态目录没有 models/library/jobs/knowledge/cache/render_bundles；
- 隔离 HOME、当前目录和源码没有新增资产目录；
- forget 后 A、B 完整存在。

脚本结束时自动清理临时目录。失败输出不得打印环境变量全集、API Key 或真实用户目录。

### 6.5 CI

在 pytest 之后或黄金基线之后增加独立步骤：

```yaml
- name: Exercise workspace CLI end to end
  run: python scripts/check_workspace_cli_e2e.py
```

四个现有矩阵任务都运行。不得只在 Windows 跑，也不得把 E2E 包进 pytest 后声称独立验收。

### 6.6 批次 B 验证与提交

先运行 CLI/启动器定向测试，再运行：

```powershell
..\..\.venv\Scripts\python.exe scripts/check_workspace_cli_e2e.py
..\..\.venv\Scripts\python.exe scripts/check_golden_baseline.py --replay
..\..\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
..\..\.venv\Scripts\python.exe scripts/check_repository_hygiene.py --root .
..\..\.venv\Scripts\python.exe -m compileall -q src tests scripts
..\..\.venv\Scripts\python.exe scripts/launch_sanity_check.py
git diff --check
git status --short
```

提交：

```text
feat: expose workspace selection through CLI
```

提交后停止，不推送、不建 PR、不合并，等待强模型完整审查。

## 7. 批次 B 强模型审查门禁

将拒绝：

- JSON stdout 混入提示或 traceback；
- CLI/启动器复制工作区业务逻辑；
- `doctor PATH` 改变当前选择；
- `forget` 删除资产；
- 菜单暗示旧模型/任务已经迁移；
- 只测函数、不跨进程；
- E2E 触碰真实 HOME、LocalAppData、用户工作区、Demo 或 API Key；
- E2E 只在一个操作系统运行；
- 为本任务引入 Web、Playwright 或第三方依赖；
- 修改版本号或旧管线。

## 8. 完整完成门禁

批次 A、B 审查通过后，主任务强模型会重新运行：

- 定向测试；
- 独立 CLI/启动器 E2E；
- 黄金基线；
- 全量 pytest；
- repository hygiene；
- compileall；
- launch sanity；
- `git diff --check`；
- 变更范围和秘密扫描。

之后才允许推送功能分支、创建 PR、等待 GitHub Ubuntu/Windows CI，并在用户明确授权后合并。

## 9. 非目标

- 不实现 HTTP API、Web 或 Playwright；
- 不让旧 pipeline、模型或输出改用工作区；
- 不迁移旧 `output/` 或 `~/.cs2pov/config.json`；
- 不处理模型 API 配置档案和系统凭据存储；
- 不删除、移动、复制用户资产；
- 不修改版本号或创建发布标签；
- Luna 不推送、不创建 PR、不合并。

## 10. 回滚

本任务不改旧管线。回滚代码不会删除任何工作区；用户机器最多遗留一个仅含路径指针的 LocalAppData `state.json`。不得把删除工作区作为回滚或测试清理步骤。
