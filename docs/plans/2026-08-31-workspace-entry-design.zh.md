# Luna-01C：工作区选择与用户入口设计

- 日期：2026-08-31
- 状态：已完成讨论，待书面审核
- 所属阶段：阶段 1.1「Workspace 配置与路径策略」
- 前置实现：Luna-01A `WorkspacePaths`、Luna-01B `WorkspaceService`
- 实施模型：Luna
- 审查模型：主任务强模型

## 1. 背景与目标

Luna-01A 和 Luna-01B 已建立显式工作区路径、初始化和只读诊断内核，但用户还无法通过稳定入口选择、记忆、切换或检查工作区。旧 v0.9.8 CLI、文本启动器、模型缓存和处理产物仍各自使用旧路径，因此仅有工作区内核还没有解决真实文件管理问题。

本设计建立工作区选择的应用用例与用户入口，并固定一个重要边界：

- `%LOCALAPPDATA%\CS2POV\state.json` 只允许保存最后选择的工作区路径指针；
- 模型、Demo、Job、知识、缓存、字幕、绿幕和视频等资产不得进入该状态目录，必须跟随用户明确选择的工作区；
- API Key 等秘密不得写入该状态文件；
- 没有有效选择时不得回退到源码目录、当前目录、用户主目录或系统盘默认资产目录。

Luna-01C 只完成选择、应用服务、CLI 和现有文本菜单入口。Luna-01D 再把旧模型、Demo、Job、临时文件和输出实际迁移到当前工作区。只有 01D 验收后，文件管理问题才算闭环。

## 2. 方案选择

### 2.1 采用方案：共享应用服务 → CLI/文本菜单 → 后续 Web

先建立与界面无关的 `WorkspaceApplicationService`，再让 CLI 和现有双击文本菜单调用它。未来本地 HTTP API 和 Web 初始化页复用相同应用服务，不另建业务流程。

优点：

- 不提前冻结尚未完成小型验证的 Web/API 框架；
- 当前阶段即可通过真实子进程和文件系统做端到端验收；
- CLI、自动化、AI、未来 Web 共用相同状态语义和错误代码；
- 变更范围仍限于阶段 1.1，不把旧管线迁移混进同一批次。

### 2.2 不采用：现在加入本地 HTTP API

HTTP API 更接近未来 Web，但会提前引入框架、服务生命周期、端口、打包和安全边界。总计划要求先用原型比较框架并记录 ADR，因此本阶段不应借工作区入口绕过该门禁。

### 2.3 不采用：直接制作 Web 初始化页

直接上 Web 能更快展示非程序员界面，但旧管线和模型路径尚未迁移，会形成“界面已选择工作区、实际资产仍写旧位置”的假完成，也无法诚实满足端到端验收。

## 3. 分层与组件

```text
CLI / 文本启动器 / 未来 Web
              │
              ▼
WorkspaceApplicationService
       │                 │
       ▼                 ▼
WorkspaceService   WorkspaceSelectionPort
                         │
                         ▼
             JsonWorkspaceSelectionStore
```

### 3.1 `WorkspaceApplicationService`

建议位置：

```text
src/cs2pov/application/workspace.py
```

它负责编排用户用例，不直接解析命令行、不打印文本、不读取全局环境变量，也不拥有 JSON 文件格式。公开用例为：

```python
initialize_and_select(root: str | Path) -> WorkspaceView
select_existing(root: str | Path) -> WorkspaceView
show_current() -> WorkspaceView
diagnose(root: str | Path | None = None) -> WorkspaceView
forget_current() -> ForgetWorkspaceResult
```

`WorkspaceView` 包含用于本地用户入口的规范绝对根路径和 `WorkspaceDiagnostic`。绝对路径只在用户主动调用的本地入口结果中出现；不得写回 `workspace.json`、Job、日志包或反馈包。

应用服务依赖：

- `WorkspaceSelectionPort`：读取、保存和忘记当前选择；
- `WorkspaceService` 工厂：根据显式路径创建 Luna-01B 服务；
- `WorkspacePaths`：验证根路径绝对且规范化。

### 3.2 `WorkspaceSelectionPort`

接口与应用服务放在应用层，至少提供：

```python
load() -> WorkspaceSelection | None
save(selection: WorkspaceSelection) -> None
forget() -> bool
```

应用层通过该接口测试状态转换；以后若桌面壳使用系统设置存储，只需替换适配器，不改变 CLI/Web 用例。

### 3.3 `JsonWorkspaceSelectionStore`

建议位置：

```text
src/cs2pov/storage/workspace_selection_store.py
```

它只负责严格读取和原子写入状态文件。构造函数接收显式绝对 `state_file`，因此单元测试不会触碰真实用户目录。

生产组合根按以下顺序解析状态文件位置：

1. 若设置 `CS2POV_STATE_FILE`，其值必须是非空绝对路径；这只供自动化、便携部署和隔离 E2E 使用；
2. Windows 使用 `%LOCALAPPDATA%\CS2POV\state.json`；缺少或无效的 `LOCALAPPDATA` 必须返回稳定错误，不回退到当前目录或源码目录；
3. 非 Windows 优先使用绝对 `XDG_STATE_HOME/cs2pov/state.json`，否则使用 `~/.local/state/cs2pov/state.json`；
4. 解析位置本身不得创建文件或目录。父目录只在用户成功执行 `init` 或 `use` 后保存选择时创建。

## 4. 状态文件契约

v1 精确格式为：

```json
{
  "schema_version": 1,
  "selected_workspace": "D:\\CS2POV-Workspace"
}
```

规则：

1. 只允许这两个键，拒绝未知键；
2. `schema_version` 必须是整数 `1`，布尔值不得当作整数接受；
3. `selected_workspace` 必须是非空、规范化绝对路径；
4. 不允许 API Key、模型名、Demo 路径、Job、SteamID、缓存位置或其他配置；
5. UTF-8、两空格缩进、末尾换行；
6. 使用状态目录内唯一临时文件并通过 `os.replace` 原子替换；成功或失败后不得遗留临时文件；
7. 状态文件是符号链接、目录、无效 JSON、错误版本或字段不符时返回 `selection_state_invalid`，不得跟随链接读取；
8. `load()` 和对不存在状态执行 `forget()` 必须只读且不创建父目录；
9. `forget()` 只删除 `state.json`，不删除状态目录内其他文件，也不访问或删除所指向的工作区；
10. 保存新选择可以原子覆盖损坏的旧状态，这是用户通过显式 `init/use` 执行的恢复动作。

## 5. 用例语义与状态转换

### 5.1 路径优先级

工作区解析优先级固定为：

```text
命令显式提供的根路径 > 已保存的当前工作区 > selection_missing
```

禁止隐式使用 `Path.cwd()`、源码目录、安装目录、旧 `output/` 或任意系统盘资产目录。

### 5.2 `initialize_and_select(root)`

1. 先用 `WorkspacePaths` 验证显式绝对路径；
2. 调用 `WorkspaceService.initialize()`；
3. 调用 `diagnose()`，只有 `diagnostic.ok` 为真才保存选择；
4. 保存成功后返回当前路径和诊断；
5. 初始化或诊断失败时保留原选择不变；
6. 初始化成功但保存选择失败时，工作区目录和 `workspace.json` 保持完好，返回 `selection_state_write_failed`，提示用户重试 `use`；
7. 重复初始化并选择同一路径必须幂等，不更换 `workspace_id` 和创建时间。

跨工作区目录与 LocalAppData 状态文件无法形成单文件事务，因此第 6 条的可恢复部分成功状态是明确契约，不能通过删除已初始化工作区伪造回滚。

### 5.3 `select_existing(root)`

1. 不创建、不补齐、不修复工作区目录；
2. 要求 `workspace.json` 有效且 `diagnose().ok` 为真；
3. 任一诊断问题都返回失败并保留旧选择；
4. 成功后原子替换当前选择。

### 5.4 `show_current()`

1. 没有状态时返回 `selection_missing`；
2. 状态损坏时返回 `selection_state_invalid`；
3. 有选择时返回路径及当前只读诊断；
4. 如果工作区后来丢失、外接磁盘断开、权限变化或空间不足，保留选择并返回对应诊断，不自动清除或切换。

### 5.5 `diagnose(root=None)`

- 提供 `root` 时只诊断该路径，不改变当前选择；
- 未提供时诊断当前选择；
- 没有当前选择时返回 `selection_missing`；
- 诊断沿用 Luna-01B 的稳定 issue、顺序和无路径诊断对象。

### 5.6 `forget_current()`

- 删除有效或损坏的状态指针；
- 状态不存在时幂等成功并报告 `forgotten=false`；
- 绝不删除、移动、清空或修复工作区和其中任何资产；
- 文本界面必须明确显示“只忘记选择，不删除文件”。

## 6. CLI 契约

在现有 `cs2pov` 下新增：

```text
cs2pov workspace init PATH [--json]
cs2pov workspace use PATH [--json]
cs2pov workspace show [--json]
cs2pov workspace doctor [PATH] [--json]
cs2pov workspace forget [--json]
```

命令注册和输出转换放入聚焦模块，例如：

```text
src/cs2pov/cli/workspace_commands.py
```

`commands.py` 只做最小的 parser 注册和 dispatch，不能继续把业务实现堆进已有大文件。

### 6.1 JSON 成功结构

工作区命令的 JSON 必须可直接机器解析，stdout 只能包含一个 JSON 文档：

```json
{
  "ok": true,
  "command": "workspace.doctor",
  "selected_workspace": "D:\\CS2POV-Workspace",
  "diagnostic": {
    "ok": true,
    "initialized": true,
    "writable": true,
    "free_bytes": 10000000000,
    "required_free_bytes": 5368709120,
    "issues": []
  }
}
```

`forget` 额外返回 `forgotten`，并令 `selected_workspace` 与 `diagnostic` 为 `null`。

### 6.2 JSON 错误结构

已知用户错误不得输出 traceback：

```json
{
  "ok": false,
  "command": "workspace.use",
  "error": {
    "code": "workspace_config_invalid",
    "message_zh": "工作区配置缺失或损坏。",
    "suggestion_zh": "请恢复有效配置或重新选择工作区。"
  }
}
```

若诊断包含多个 issue，错误输出可同时带完整 `diagnostic`，顶层 `error` 使用第一个稳定 issue，便于 shell 和 AI 快速判断。

### 6.3 退出码与文本输出

- `0`：命令成功；`doctor` 仅在诊断健康时为 0；
- `1`：可恢复的选择、状态、路径、初始化或诊断问题；
- `2`：argparse 命令用法错误；
- 未预期的编程错误仍由现有顶层策略暴露给开发者，但异常文本必须经过秘密卫生检查。

非 JSON 文本使用简短中文，显示当前路径、状态、修复建议和“是否修改了选择”。不得只显示错误类型名。

## 7. 文本启动器入口

现有双击启动器在“设置与高级工具”中增加“工作区管理”，包含：

1. 初始化并设为当前工作区；
2. 使用已有工作区；
3. 查看当前工作区；
4. 诊断当前或指定工作区；
5. 忘记当前选择。

启动器首页显示简短状态：已选择、未选择或需要修复。读取状态不得创建 LocalAppData 目录。

由于旧 v0.9.8 管线在 Luna-01C 尚未迁移，界面必须明确提示：“当前步骤只设置新版本数据目录；模型和任务接入将在下一阶段完成。”本阶段不阻止用户进入旧流程，也不得声称旧流程已经跟随工作区。

`forget` 菜单在执行前再次说明“不会删除工作区文件”；不需要危险删除确认，因为操作只删除可恢复的路径指针。

## 8. 错误代码

选择层新增稳定代码：

- `selection_missing`
- `selection_state_invalid`
- `selection_state_location_unavailable`
- `selection_state_read_failed`
- `selection_state_write_failed`
- `selection_state_forget_failed`

工作区自身问题继续沿用 Luna-01B：

- `workspace_missing`
- `workspace_not_directory`
- `workspace_config_missing`
- `workspace_config_invalid`
- `workspace_layout_missing`
- `workspace_not_writable`
- `workspace_space_low`
- `workspace_inspection_failed`

每个错误都必须有稳定代码、面向非程序员的中文消息和可执行建议。错误对象不得含 API Key、Demo 文件名或其他秘密。

## 9. 测试与真实端到端验收

### 9.1 单元测试

覆盖：

- 状态严格 schema 往返；
- 未知键、布尔版本、相对/空路径、损坏 JSON、符号链接和错误版本；
- 中文及空格路径；
- 原子替换失败与临时文件清理；
- 只读 `load` 和空状态 `forget` 不创建目录；
- `forget` 不访问工作区、不删除状态目录其他文件；
- 默认状态路径和 `CS2POV_STATE_FILE` 绝对路径规则。

### 9.2 应用契约测试

覆盖：

- 初始化成功后才保存；
- 初始化失败、诊断失败和 `use` 失败都保留旧选择；
- 初始化成功但状态保存失败的可恢复部分成功；
- `use` 不创建或修复目录；
- 当前磁盘后来丢失时保留选择；
- 显式 `doctor PATH` 不改变选择；
- `forget` 只忘记指针；
- 所有结果可 JSON 序列化。

### 9.3 CLI 契约测试

覆盖 parser、退出码、JSON stdout 单文档、中文文本和已知错误无 traceback。JSON 测试必须使用 `json.loads(stdout)`，不能只搜索字符串。

### 9.4 独立真实 CLI E2E

新增独立脚本，例如：

```text
scripts/check_workspace_cli_e2e.py
```

脚本不能直接调用命令处理函数。它必须用多个真实 Python 子进程和真实临时文件系统，在中文路径中依次执行：

```text
init A → show（新进程）→ doctor → init B/use A → show（新进程）→ forget → show 失败
```

E2E 使用绝对 `CS2POV_STATE_FILE` 指向隔离临时目录，并断言：

- 跨进程选择持久化；
- `workspace.json` 不含绝对根路径；
- LocalAppData/状态目录只有允许的指针和临时写入，不出现 models、Demo、jobs、cache 或输出；
- 源码目录、隔离 HOME 和进程当前目录没有新资产目录；
- `forget` 后两个工作区及其标识保持原样；
- stdout JSON 可解析、stderr 不含 traceback；
- 脚本失败时只报告隔离路径和错误摘要，不输出秘密。

### 9.5 独立文本启动器 E2E

通过子进程标准输入驱动 `python -m cs2pov.cli.launcher --once` 的工作区菜单完成初始化，再由另一个 `cs2pov workspace show --json` 进程验证选择。它验证菜单路由、应用服务和真实状态文件的整条链，而不是只调用内部函数。

### 9.6 CI

GitHub Actions 在 pytest 之外增加独立步骤：

```text
python scripts/check_workspace_cli_e2e.py
```

Ubuntu 3.11/3.12/3.13 与 Windows 3.12 都执行。Windows 是 `%LOCALAPPDATA%` 和中文路径行为的主要门禁；Ubuntu 防止平台逻辑与路径实现被写死。

本阶段不使用 Playwright，因为尚无浏览器界面。未来 Web 初始化页必须从真实浏览器复用这些用例并加入 Playwright；不得用 HTTP 契约测试冒充浏览器 E2E。

## 10. 文件范围

建议新增：

```text
src/cs2pov/application/__init__.py
src/cs2pov/application/workspace.py
src/cs2pov/storage/workspace_selection_store.py
src/cs2pov/cli/workspace_commands.py
tests/test_workspace_selection_store.py
tests/test_workspace_application.py
tests/test_workspace_cli.py
scripts/check_workspace_cli_e2e.py
```

允许最小修改：

```text
src/cs2pov/cli/commands.py
src/cs2pov/cli/launcher.py
src/cs2pov/workspace/errors.py
.github/workflows/ci.yml
tests/test_launcher_navigation.py
```

若无需新增选择错误类到 `workspace/errors.py`，可在应用层定义；不得为缩短文件数量把持久化、业务编排和输出混入一个模块。

## 11. 非目标

- 不接入 FastAPI、Flask、Web 框架或 HTTP 服务器；
- 不增加 Playwright、Node 或前端依赖；
- 不修改旧 PipelineConfig、ArtifactStore、Whisper 或 Hugging Face 调用；
- 不迁移旧 `output/`、旧模型缓存或旧 `~/.cs2pov/config.json`；
- 不处理 API Key 存储重构；
- 不导入 Demo、不创建 Job、不生成字幕或视频；
- 不自动删除、移动或复制任何用户资产；
- 不修改版本号或创建发布标签。

## 12. 安全、隐私与可恢复性

- 状态文件只存路径指针，不存秘密和用户资产；
- 所有变更都由显式 `init/use/forget` 触发；读取和诊断默认只读；
- 切换失败保留旧选择，避免用户突然失去可用工作区；
- 外接磁盘断开时保留指针，恢复连接后无需重新选择；
- 忘记选择不触碰工作区；
- 状态写入失败不会删除已经初始化的工作区；
- JSON 和日志输出须通过仓库秘密卫生检查；
- E2E 只使用临时合成目录，不读取真实 Demo、API Key、模型或用户工作区。

## 13. 完成定义

Luna-01C 只有同时满足以下条件才可合并：

1. CLI 与文本启动器调用同一个 `WorkspaceApplicationService`；
2. 当前选择只以严格、原子、无秘密的路径指针持久化；
3. 没有选择或状态损坏时不存在任何资产路径静默回退；
4. `init/use/show/doctor/forget` 的文本、JSON 和退出码契约通过；
5. 失败不改变原选择，`forget` 不删除工作区；
6. 独立跨进程 CLI E2E 与文本启动器 E2E 通过；
7. GitHub Ubuntu/Windows CI、黄金基线、完整 pytest、编译和仓库卫生检查全部通过；
8. 文档明确 Luna-01C 只是入口基础，Luna-01D 才负责让旧模型和处理产物真正跟随工作区；
9. 代码经过主任务强模型审查，PR 仅在用户明确授权后合并。

## 14. 回滚

Luna-01C 不改旧管线行为。回滚代码后，用户工作区和 `workspace.json` 保持不变；LocalAppData 中最多遗留一个无秘密的 `state.json` 路径指针，可由用户手动删除。不得把删除用户工作区作为回滚步骤。
