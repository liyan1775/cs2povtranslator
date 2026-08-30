# Luna-01A：WorkspacePaths 纯路径内核

- 状态：可实施
- 基线提交：`31e74783156594f647abfafbaa9543dfd3b45843`
- 所属阶段：1.1 Workspace 配置与路径策略
- 实施模型：Luna
- 审查模型：主任务强模型

## 1. 目标

建立一个只依赖 Python 标准库、没有隐式写盘和全局环境副作用的工作区路径内核。后续的工作区初始化、诊断、Demo 导入、Job、模型缓存、知识库、RenderBundle、CLI 和 Web 都必须从这个对象取得路径，不能各自拼接目录或静默回落到系统盘。

本任务只是阶段 1.1 的第一个可独立验收切片，不宣称完成整个工作区功能。

## 2. 允许修改的文件

新增：

```text
src/cs2pov/workspace/__init__.py
src/cs2pov/workspace/errors.py
src/cs2pov/workspace/paths.py
tests/test_workspace_paths.py
```

如果导出公开符号确有需要，可以最小修改 `src/cs2pov/workspace/__init__.py`。除此之外不得修改旧 CLI、PipelineConfig、ArtifactStore、模型管理、工作流、依赖和版本号。

## 3. 必须提供的公开接口

### 3.1 错误类型

```python
class WorkspaceError(Exception): ...
class WorkspaceRootRequiredError(WorkspaceError): ...
class WorkspaceResourcePathError(WorkspaceError): ...
class WorkspacePathOutsideRootError(WorkspaceError): ...
```

错误消息必须说明用户可采取的动作，但不得猜测或打印 API Key 等秘密。

### 3.2 WorkspacePaths

```python
class WorkspacePaths:
    def __init__(self, root: str | Path) -> None: ...

    root: Path
    config_file: Path
    models_dir: Path
    demo_library_dir: Path
    jobs_dir: Path
    knowledge_dir: Path
    knowledge_inbox_dir: Path
    knowledge_exports_dir: Path
    cache_dir: Path
    decompressed_demos_cache_dir: Path
    audio_cache_dir: Path
    render_cache_dir: Path
    huggingface_cache_dir: Path
    huggingface_hub_cache_dir: Path
    whisper_cache_dir: Path
    temp_dir: Path
    render_bundles_dir: Path

    def persistent_directories(self) -> tuple[Path, ...]: ...
    def cache_directories(self) -> tuple[Path, ...]: ...
    def all_directories(self) -> tuple[Path, ...]: ...
    def to_relative(self, path: str | Path) -> str: ...
    def resolve_relative(self, value: str) -> Path: ...
    def cache_paths(self) -> dict[str, Path]: ...
    def environment_overrides(self) -> dict[str, str]: ...
```

属性可以用 `@property` 实现。返回集合的顺序必须稳定且不得包含重复项。

## 4. 固定目录布局

所有路径必须位于显式根目录下：

```text
workspace.json
models/
library/demos/
jobs/
knowledge/
knowledge/inbox/
knowledge/exports/
cache/
cache/decompressed_demos/
cache/audio/
cache/render/
cache/huggingface/
cache/huggingface/hub/
cache/whisper/
cache/tmp/
render_bundles/
```

持久目录至少包含 `models`、`library/demos`、`jobs`、`knowledge`、`knowledge/inbox`、`knowledge/exports` 和 `render_bundles`。缓存目录至少包含 `cache` 及其上述子目录。

## 5. 路径与副作用规则

1. 根目录必须由调用者显式提供，`None`、空字符串、纯空白、相对路径和 `Path()` 必须抛出 `WorkspaceRootRequiredError`。
2. 接受中文和空格路径；保存为规范化绝对 `Path`。
3. 构造对象、读取属性和调用映射方法不得创建任何目录或文件。
4. 不得读取项目配置来猜根目录，不得使用当前目录、用户目录、`C:\` 或任何系统默认目录兜底。
5. `to_relative` 只接受工作区内的路径，返回使用 `/` 的非空相对字符串；根目录本身及外部路径必须拒绝。
6. `resolve_relative` 只接受规范化工作区相对字符串；拒绝空值、`.`、`..`、绝对路径、盘符、UNC、反斜杠、URI 和任何穿越工作区的结果。
7. 两个转换方法必须可往返：`resolve_relative(to_relative(path)) == path`。
8. 已存在的符号链接若指向工作区外，也必须被边界检查拒绝；测试可以在不支持创建符号链接的 Windows 环境跳过。
9. `cache_paths()` 至少返回稳定键 `huggingface`、`huggingface_hub`、`whisper`、`temporary`。
10. `environment_overrides()` 返回将缓存约束到工作区的建议映射，至少包含 `HF_HOME`、`HF_HUB_CACHE`、`HUGGINGFACE_HUB_CACHE`、`TMP`、`TEMP`、`TMPDIR`；本方法不得修改 `os.environ`。
11. 此切片不得创建 `workspace.json`，不得检查可写性或磁盘空间；这些属于 Luna-01B 的显式初始化/诊断服务。

## 6. 必须先写的测试

在实现前新增失败测试，至少覆盖：

1. 缺失、空白、相对根目录全部失败；
2. 中文加空格的绝对根目录被规范化；
3. 完整目录布局精确匹配且都位于根目录下；
4. 构造和读取所有属性后根目录仍不存在；
5. 内部路径转换往返且序列化统一使用 `/`；
6. 外部绝对路径、`../`、Windows 盘符、UNC、反斜杠、URI、空值和根目录本身被拒绝；
7. 已存在的外向符号链接被拒绝；
8. 持久目录、缓存目录顺序稳定、无重复、互不误分；
9. 缓存映射全部落在工作区内；
10. 调用 `environment_overrides()` 前后 `os.environ` 完全相同。

测试不得依赖本机固定盘符；Windows 特例可用 `PureWindowsPath` 输入字符串验证。测试必须在 Linux Python 3.11–3.13 和 Windows Python 3.12 可运行。

## 7. 非目标

- 不创建目录或 `workspace.json`；
- 不实现 workspace 选择记忆、CLI、API 或 Web；
- 不迁移旧 `output_root`、旧 Job 或模型缓存；
- 不修改 `PipelineConfig`、Whisper 适配器或 `os.environ`；
- 不加入第三方依赖；
- 不实现 DemoAsset、哈希导入或资源数据库；
- 不提交 Demo、模型、缓存、输出、密钥或机器绝对路径。

## 8. 实施与验证顺序

1. 阅读本任务书及两份总设计文档中的阶段 1；
2. 只写 `tests/test_workspace_paths.py`，运行并保留预期失败证据；
3. 写最小实现使新测试通过；
4. 运行：

```powershell
python -m pytest tests/test_workspace_paths.py -q
python scripts/check_golden_baseline.py --replay
python -m pytest -q
python scripts/check_repository_hygiene.py --root .
python -m compileall -q src tests scripts
git diff --check
```

5. 自查仅修改允许范围；
6. 提交一个可读提交，建议信息：`feat: add explicit workspace path contract`；
7. 不推送、不创建 PR、不合并，由主任务强模型复核后处理。

## 9. 强模型审查门禁

审查会拒绝以下实现：

- 构造时自动创建目录；
- 相对路径被当前工作目录悄悄转成绝对路径；
- `resolve_relative` 可通过混合分隔符、盘符、UNC、URI 或符号链接逃逸；
- 缓存仍可能回落到工作区外；
- 方法直接修改全局环境变量；
- 为方便实现而改动旧管线或扩大任务范围；
- 只有 happy-path 测试，缺乏越界和无副作用测试。

## 10. 回滚

本切片不接入旧管线。回滚时只需撤销新增的 `workspace` 包和测试，不影响 v0.9.8 现有行为或用户资产。
