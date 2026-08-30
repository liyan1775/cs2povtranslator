# Luna-01B：工作区显式初始化与只读诊断

- 状态：可实施
- 基线提交：`eaec370950218992680fa28ad06271240e999990`
- 所属阶段：1.1 Workspace 配置与路径策略
- 前置任务：Luna-01A `WorkspacePaths`
- 实施模型：Luna
- 审查模型：主任务强模型

## 1. 目标

在已合并的 `WorkspacePaths` 之上建立显式、幂等、可诊断的工作区初始化服务：只有用户明确选择根目录并调用初始化时才创建目录和 `workspace.json`；诊断方法默认只读；损坏配置、不可写、空间不足和符号链接逃逸必须产生稳定错误代码与面向非程序员的中文修复建议。

本任务仍不接入旧 CLI、PipelineConfig、Web 或模型下载。它提供后续 CLI/API 共用的应用内核。

## 2. 允许修改的文件

新增：

```text
src/cs2pov/workspace/models.py
src/cs2pov/workspace/service.py
tests/test_workspace_service.py
```

允许最小修改：

```text
src/cs2pov/workspace/errors.py
src/cs2pov/workspace/__init__.py
```

不得修改旧 CLI、PipelineConfig、ArtifactStore、Whisper/模型管理、工作流、依赖和版本号。

## 3. workspace.json 固定 Schema

### 3.1 WorkspaceConfig

```python
WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_LAYOUT_VERSION = 1

@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    schema_version: int
    layout_version: int
    workspace_id: str
    created_at: str

    def to_dict(self) -> dict[str, object]: ...
    @classmethod
    def from_dict(cls, value: object) -> "WorkspaceConfig": ...
```

规则：

1. v1 只允许这四个键，拒绝未知键；借此防止把 `root`、Demo 路径、SteamID、API Key 或其他秘密塞进配置。
2. 两个版本号必须精确为 `1`。
3. `workspace_id` 必须是规范 UUID 字符串。
4. `created_at` 必须是带时区的 UTC ISO-8601 字符串，序列化统一为 `YYYY-MM-DDTHH:MM:SS.ffffffZ`。
5. `workspace.json` 的位置本身决定根目录，因此文件内容不得保存根目录。
6. `to_dict()` 键顺序固定为 schema、layout、workspace_id、created_at。

## 4. 诊断模型

```python
@dataclass(frozen=True, slots=True)
class WorkspaceIssue:
    code: str
    severity: str       # error | warning
    message_zh: str
    suggestion_zh: str

    def to_dict(self) -> dict[str, str]: ...

@dataclass(frozen=True, slots=True)
class WorkspaceDiagnostic:
    ok: bool
    initialized: bool
    writable: bool | None
    free_bytes: int | None
    required_free_bytes: int
    issues: tuple[WorkspaceIssue, ...]

    def to_dict(self) -> dict[str, object]: ...
```

诊断对象不得包含 API Key、SteamID、Demo 文件名或绝对根路径。稳定 issue code 至少包含：

- `workspace_missing`
- `workspace_not_directory`
- `workspace_config_missing`
- `workspace_config_invalid`
- `workspace_layout_missing`
- `workspace_not_writable`
- `workspace_space_low`
- `workspace_inspection_failed`

`ok` 只有在配置有效、布局完整、可写且空间达标时为真。普通环境问题通过 `issues` 返回，不向非程序员抛 traceback。

## 5. 新错误类型

在现有层级下新增：

```python
class WorkspaceInitializationError(WorkspaceError): ...
class WorkspaceConfigError(WorkspaceInitializationError): ...
class WorkspaceNotWritableError(WorkspaceInitializationError): ...
class WorkspaceInsufficientSpaceError(WorkspaceInitializationError): ...
class WorkspaceLayoutError(WorkspaceInitializationError): ...
```

异常消息必须是可执行的中文提示；异常不得携带秘密。初始化失败可以抛这些错误，`diagnose()` 则把错误转换为稳定 issue。

## 6. WorkspaceService 接口

```python
DEFAULT_MINIMUM_FREE_BYTES = 5 * 1024**3

class WorkspaceService:
    def __init__(
        self,
        paths: WorkspacePaths,
        *,
        minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES,
        id_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] = utc_now,
        disk_usage: Callable[[Path], object] = shutil.disk_usage,
    ) -> None: ...

    def initialize(self) -> WorkspaceConfig: ...
    def load_config(self) -> WorkspaceConfig: ...
    def diagnose(self) -> WorkspaceDiagnostic: ...
```

允许把默认 callable 放在模块级函数中，避免定义时绑定影响 monkeypatch。不得新增第三方依赖。

## 7. 初始化语义

`initialize()` 必须按以下顺序工作：

1. 找到根目录或最近存在的父目录，读取磁盘可用空间；若低于阈值，在创建根目录前抛 `WorkspaceInsufficientSpaceError`。
2. 若根路径已存在但不是目录，抛 `WorkspaceLayoutError`。
3. 在任何 `mkdir`、读取配置或写配置前，对配置路径和所有受管目录做边界检查；如果现有父级符号链接会把路径导向工作区外，抛 `WorkspaceLayoutError`，不得在外部创建文件。
4. 若根目录已存在且 `workspace.json` 已存在，必须先验证配置，验证失败时不创建或补齐任何目录：
   - 有效则加载原 `workspace_id` 和 `created_at`，补齐缺失目录后返回；
   - 无效、是目录或是越界符号链接则抛 `WorkspaceConfigError`，绝不覆盖。
5. 显式创建根目录和 `WorkspacePaths.all_directories()`；保留无关的既有文件，不清空、不移动、不覆盖用户资产。
6. 用根目录内的唯一临时探针验证可写性，并在成功或失败后清理探针。权限或只读错误转换为 `WorkspaceNotWritableError`。
7. 若配置原先不存在：使用注入的 UUID 和时钟创建配置；时钟必须是带时区 datetime，并规范化到 UTC。
8. 配置必须以 UTF-8、两空格缩进、末尾换行写入根目录内的唯一临时文件，然后通过 `os.replace` 原子替换到 `workspace.json`。
9. 配置写入失败时清理本次临时文件，不删除既有目录或用户文件，并抛自定义初始化错误。
10. 重复初始化必须幂等；不得更换 ID/时间，也不得产生遗留探针或临时配置。

目录创建发生在显式 `initialize()` 内是授权行为；构造 `WorkspaceService`、`load_config()` 和 `diagnose()` 不得创建任何文件。

## 8. 只读诊断语义

`diagnose()`：

1. 不创建根目录、探针、配置或缺失目录；
2. 根不存在时返回 `workspace_missing`，并可从最近存在父目录报告空间；
3. 根是文件时返回 `workspace_not_directory`；
4. 配置缺失/损坏、目录缺失、不可写、空间不足分别返回稳定 issue；
5. 使用 `os.access(root, os.W_OK)` 做只读可写性提示；真正可写性仍由初始化探针确认；
6. 文件系统检查自身失败时返回 `workspace_inspection_failed`，不得泄露绝对路径；
7. issues 顺序固定：根/检查失败、配置、布局、可写性、空间，便于 UI 和测试稳定显示。

## 9. 必须先写的测试

至少覆盖：

1. `WorkspaceConfig` 有效往返；未知键、错误版本、非 UUID、无时区/非 UTC 时间全部拒绝；
2. 初始化创建完整目录和精确配置内容，配置不含 `root`、`path`、`key`、`steamid`；
3. 中文加空格根目录；
4. 初始化幂等，并能补齐后来删除的受管空目录；
5. 保留根目录内无关既有文件；
6. 已有损坏配置不会被覆盖，原字节保持不变；
7. 根路径是文件时失败；
8. 注入低空间结果时，在根不存在的情况下也不得创建根；
9. 模拟 mkdir、探针写入和原子替换权限错误，转换为稳定自定义错误且不遗留临时文件；
10. 受管目录的已有父级符号链接指向外部时失败，外部不产生子目录；不支持符号链接的平台可跳过；
11. `diagnose()` 对缺失、损坏配置、缺目录、不可写和低空间返回对应 issue；
12. `diagnose()` 调用前后文件系统树完全一致；
13. diagnostic `to_dict()` 可直接 JSON 序列化且不含根路径；
14. 构造服务和 `load_config()` 不创建根目录；
15. `minimum_free_bytes` 为负数或依赖 callable 返回非法值时，以明确编程错误失败。

测试不得依赖本机真实剩余空间或修改真实权限才能通过；通过注入/monkeypatch 稳定覆盖错误。真实临时目录只用于 happy path 和跨平台文件行为。

## 10. 非目标

- 不记忆“上次选择的工作区”；
- 不添加 CLI、API、Web 或 Playwright；
- 不迁移旧输出和旧配置；
- 不修改 Whisper/Hugging Face 的实际调用；
- 不修改 `os.environ`；
- 不导入 Demo 或创建 Job；
- 不删除、移动或覆盖无关文件；
- 不推送、不创建 PR、不合并。

## 11. 实施与验证顺序

1. 完整阅读本任务书、Luna-01A 任务书和总设计阶段 1；
2. 先只写 `tests/test_workspace_service.py`，运行并保留预期失败证据；
3. 写最小实现使新增测试通过；
4. 运行：

```powershell
python -m pytest tests/test_workspace_service.py tests/test_workspace_paths.py -q
python scripts/check_golden_baseline.py --replay
python -m pytest -q
python scripts/check_repository_hygiene.py --root .
python -m compileall -q src tests scripts
git diff --check
```

5. 自查只修改允许范围；
6. 提交一个可读提交，建议信息：`feat: add explicit workspace initialization service`；
7. 不推送、不创建 PR、不合并，由主任务强模型复核。

## 12. 强模型审查门禁

审查会拒绝：

- 配置写入绝对根路径、秘密或未知扩展字段；
- 低空间判断发生在创建目录之后；
- 损坏配置被“自动修复”或覆盖；
- 诊断为了检查可写性而写入探针；
- 临时文件固定命名导致并发冲突，或失败后遗留；
- 目录/配置符号链接可导向工作区外；
- 初始化直接修改全局环境变量；
- 将旧 CLI/管线接入混入本切片；
- 只测 happy path，未测试失败后的磁盘状态。

## 13. 回滚

本切片未接入旧管线。回滚新增模型/服务/测试及错误导出即可；已经由测试创建的临时工作区仅位于 pytest 临时目录，不涉及用户资产。
