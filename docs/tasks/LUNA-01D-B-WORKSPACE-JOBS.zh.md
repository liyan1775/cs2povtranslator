# Luna-01D-B：工作区 Job、Pipeline 与文件生命周期接入任务书

- 日期：2026-08-31
- 状态：待实施
- 设计依据：`docs/plans/2026-08-31-workspace-runtime-paths-design.zh.md`
- 基线：`master` 合并提交 `b7c846c`
- 工作分支：`feature/luna-01d-b-job-paths`
- 实施模型：Luna
- 审查模型：主任务强模型

## 1. 任务目标

本任务只完成 Luna-01D-B：让新任务、文本向导、Pipeline、旧 Job 写操作和输出工具统一消费 01D-A 已实现的不可变 `WorkspaceRuntime`。

完成后必须真实满足：

1. `cs2pov run demo.dem` 先通过工作区写门禁，再在 `workspace/jobs/<job-id>/` 建立 Job；
2. 正常向导不再询问输出根目录；
3. 外部 `.dem`/`.dem.zst` 只读，任务副本或解压结果只进入 Job 的 `input/`；
4. Whisper 下载根固定为工作区缓存，旧配置和旧参数不能改写；
5. 默认临时音频只进入 `workspace/cache/audio/<job-id>/` 并在转录后删除；显式保留时进入 `job/debug/temp_audio/`；
6. 显式 `run --output` 只走一个可见、可审计的旧版外部输出兼容分支；
7. 旧 Job 可按显式路径查看；任何写操作都先取得健康工作区，并提示正在原位置修改外部旧 Job；
8. Job ID 不能穿越目录，冲突时不能复用或合并已有 Job；
9. 普通路径门禁错误不显示 traceback，manifest 不泄露工作区或外部输出绝对路径；
10. Windows/Ubuntu CI 通过真实 CLI 子进程验证文件实际落点和失败原子性。

本任务不实现 DemoAsset 数据库、哈希去重、旧 Job 导入器、新领域状态机、理解翻译、回合并行、Web UI、Playwright 或 POV 录制。

## 2. 开始前必须执行

在任何实现代码前：

1. 完整阅读设计文档、本任务书及以下文件：
   - `src/cs2pov/application/workspace_runtime.py`
   - `src/cs2pov/workspace/paths.py`
   - `src/cs2pov/storage/artifact_store.py`
   - `src/cs2pov/pipeline/engine.py`
   - `src/cs2pov/pipeline/manifest.py`
   - `src/cs2pov/services/demo_service.py`
   - `src/cs2pov/services/transcription_service.py`
   - `src/cs2pov/cli/commands.py`
   - `src/cs2pov/cli/job_ops.py`
   - `src/cs2pov/cli/wizard.py`
   - `src/cs2pov/cli/launcher.py`
   - 相关测试、E2E 和 CI；
2. 阅读并遵守 `superpowers:test-driven-development` 及其 `writing-good-tests.md`；
3. 确认当前目录是本任务隔离工作树、分支正确、工作树干净；
4. 运行基线：

```powershell
python -m pytest -q
python scripts/check_workspace_cli_e2e.py
python scripts/check_workspace_model_runtime_e2e.py
git status --short
```

若计划与代码实际情况冲突，先报告；不得自行扩大阶段边界。

## 3. 实现原则与提交纪律

每批必须严格遵循：

1. 先写最小行为测试；
2. 运行并记录预期 RED；
3. 写最小实现；
4. 运行目标测试得到 GREEN；
5. 运行本批相关回归；
6. 全绿后才可重构；
7. 形成一个聚焦提交并停止，等待强模型审查。

禁止：

- 先写生产代码再补测试；
- 用只断言 mock 调用次数的测试代替真实路径和文件结果；
- 在多个 CLI handler 中分别覆盖 `output_root`/`whisper_cache_dir`；
- 用 `os.environ.update()` 或 `setdefault()` 改写父进程环境；
- 为新任务回退到 cwd、源码目录、安装目录、旧 `output/` 或用户目录缓存；
- 自动移动、改写或删除旧 Job；
- 提前实现 DemoAsset、知识库或 Web UI；
- 一次完成多个批次后再报告。

每批报告必须包含：修改文件、RED 命令与失败原因、GREEN 命令、回归结果、提交哈希、未解决风险。

## 4. 允许修改范围

允许新增或修改：

```text
src/cs2pov/application/job_runtime.py             # 建议新增：单一 Job 路径兼容/分类层
src/cs2pov/application/__init__.py                 # 仅必要导出
src/cs2pov/storage/artifact_store.py
src/cs2pov/pipeline/engine.py
src/cs2pov/pipeline/manifest.py
src/cs2pov/services/demo_service.py                # 仅准备输入边界
src/cs2pov/services/transcription_service.py       # 仅临时音频清理生命周期
src/cs2pov/cli/commands.py
src/cs2pov/cli/job_ops.py
src/cs2pov/cli/wizard.py
src/cs2pov/cli/launcher.py
scripts/run_acceptance.py
scripts/acceptance_smoke.ps1
scripts/check_workspace_job_runtime_e2e.py         # 新增
.github/workflows/ci.yml
tests/test_job_runtime.py                          # 新增
tests/test_artifact_store.py
tests/test_job_tools_v030.py
tests/test_wizard_v020.py
tests/test_manifest_paths_v061.py
tests/test_models_v080.py                          # 仅 run/benchmark 旧缓存覆盖
tests/test_transcription_*.py                      # 仅临时音频行为
相关 CLI/launcher 现有测试
README.md
docs/ARCHITECTURE.zh.md
docs/OUTPUT_FILES.zh.md
docs/TESTING_GUIDE.zh.md
docs/RELEASE_CHECKLIST.zh.md
docs/FAQ.zh.md
docs/ASR_BENCHMARK.zh.md
docs/PLAYER_ALIAS_WORKFLOW.zh.md
```

如果现有测试文件更合适，可复用，不能借机重排整个测试目录。不要修改 `docs/archive/**`。

禁止修改：

```text
src/cs2pov/domain/models.py                        # 保留旧 manifest 字段，运行时另行注入
src/cs2pov/workspace/**                            # 01A/01B 已冻结的路径与服务边界
src/cs2pov/storage/workspace_selection_store.py
src/cs2pov/cli/model_manager.py                    # 01D-A 已完成，除非审查确认真实回归
Demo/**
apikey.txt
版本号、依赖、release workflow、golden 基线数据
```

## 5. 总体接口契约

### 5.1 单一应用边界

新增一个小型应用层模块（建议 `application/job_runtime.py`），集中完成以下职责：

- 根据 `WorkspaceRuntime` 选择默认 `jobs_dir`；
- 明确识别是否提供外部 `--output`；
- 将运行时的 `whisper_cache_dir` 注入本次配置副本；
- 为新 Job 构造带正确临时音频策略的 `ArtifactStore`；
- 判断显式 Job 是否位于当前 `workspace/jobs`，供旧 Job 警告使用；
- 提供稳定的 Job 路径错误 code/message/suggestion。

可采用不同名称，但不得把相同覆盖逻辑散落在 `run`、wizard、benchmark、resume 中。`PipelineConfig.output_root` 和 `whisper_cache_dir` 继续用于读取旧 manifest；新任务只允许这个兼容层回填，且必须返回配置副本，不能修改调用者对象或全局配置。

### 5.2 Pipeline 显式依赖

`PipelineEngine` 的新建和恢复路径都必须显式得到同一个 `WorkspaceRuntime` 快照。允许保留 `store=` 处理旧 Job，但禁止在缺少运行时的情况下根据 `PipelineConfig.output_root` 静默创建新 Job或选择模型缓存。

所有入口在构造 `PipelineEngine` 前调用 `resolve_for_write()`；工作区门禁失败时不得创建 Job、复制 Demo、构造模型或写外部输出。

### 5.3 路径错误

至少提供以下稳定错误：

```text
job_id_invalid
job_path_escape
legacy_model_cache_override_rejected
```

外部输出不是失败；使用 `legacy_external_output_active` 作为可结构化记录的警告代码或等价常量。路径门禁错误由 CLI 和向导捕获后输出中文说明与可执行建议，并返回非零；不得抛出到普通用户看到 traceback。意外编程错误仍可抛出，不能被伪装成路径错误。

## 6. 批次 A：Job 路径政策、原子创建与 manifest

### 6.1 先写测试

新增 `tests/test_job_runtime.py` 并扩展相关现有测试，至少覆盖：

1. 未显式给输出时，新 Job 根目录严格为 `runtime.paths.jobs_dir`；
2. 显式输出只进入一个 `legacy_external_output=True` 分支，仍保留工作区模型/临时缓存；
3. 兼容适配返回新的 `PipelineConfig`，原对象不变；
4. 旧 `output_root` 与旧 `whisper_cache_dir` 不影响新任务落点；
5. Job ID 拒绝 `None` 以外的空白、`.`、`..`、绝对路径、盘符、`/`、`\` 和任何路径穿越；
6. Unicode、连字符、下划线等安全可读名称仍可用；
7. 自动 ID 和显式 ID 在目录已存在时稳定使用 `_2`、`_3` 等后缀，绝不复用旧目录；
8. 两个并发创建者不能同时取得同一目录；测试必须验证真实文件系统结果；
9. 创建结果最终位于规范化 Job 根目录内；符号链接/junction 逃逸必须拒绝；
10. `resolve_job_dir` 在 mtime 相同时用规范名称稳定选出最新结果；
11. 新 manifest 记录 `path_policy_version=runtime.path_policy_version` 和 `legacy_external_output`；
12. 读取缺少这两个字段的旧 manifest 保持兼容；
13. public manifest 中 `config.output_root`、`config.whisper_cache_dir` 和 artifacts 都不含工作区或外部输出绝对路径；
14. 门禁适配失败不创建任何目录。

### 6.2 实现契约

- `ArtifactStore.create()` 必须用原子目录 claim（例如目标根已确认后，对候选 Job 目录使用 `mkdir(exist_ok=False)`），不能先 `exists()` 再复用；
- 输出根和最终候选都要规范化并做 containment 检查；显式外部输出只豁免“必须位于 workspace/jobs”，不豁免 Job ID 安全和必须位于该显式根目录；
- 碰撞命名可从 `_2` 顺序递增，用户能从最终 `job_dir` 和 manifest 观察到真实名称；
- `rename_suffix()` 必须保留临时音频策略，并继续原子避让冲突；
- public manifest 使用语义占位值而非本机绝对路径，例如 `[workspace-managed]` 或 `[legacy-external-output]`；加载后由单一兼容层重新注入真实运行路径；
- 新字段使用向后兼容默认值：旧 manifest 不应被误标为本次显式外部输出。

### 6.3 验证与提交

```powershell
python -m pytest tests/test_job_runtime.py tests/test_artifact_store.py tests/test_manifest_paths_v061.py tests/test_secret_redaction.py tests/test_job_tools_v030.py -q
python -m compileall -q src tests
git diff --check
```

提交建议：

```text
feat: enforce workspace job path policy
```

提交后停止并报告。

## 7. 批次 B：run、Pipeline、Demo 与临时音频生命周期

本批建立在已审查通过的批次 A 上。

### 7.1 先写测试

至少覆盖：

1. `run --output` 的 argparse 默认值为 `None`，不能用字符串 `output` 推断用户意图；
2. `run` 在新建任何文件前调用写运行时门禁；无选择、损坏或不可写时不创建 Job；
3. 默认 `run` 注入 `runtime.paths.jobs_dir` 与 `runtime.paths.whisper_cache_dir`；
4. `run --whisper-cache-dir` 返回 `legacy_model_cache_override_rejected`，不能静默忽略；
5. 外部 `.dem` 源内容和元数据保持不变，Job/input 中得到独立副本；
6. 外部 `.dem.zst` 只在 Job/input 生成解压后的 `.dem`；
7. 同名源和目标不造成覆盖或递归复制；
8. 默认临时音频路径为 `workspace/cache/audio/<final-job-id>`，转录成功或失败后均尽力删除任务目录，但不得越界清理其他 Job；
9. `keep_temp_audio=True` 时从开始就写入 `job/debug/temp_audio`，不先写 cache 再复制；
10. 根据地图重命名自动 Job 后，临时音频路径同步使用最终 Job ID；
11. `PipelineEngine` 没有显式 runtime 时不能创建新 Job；恢复旧 Job 时也使用 runtime 的模型缓存和临时根；
12. 显式外部输出在启动前和完成后均打印醒目警告；manifest 标志为 true；
13. 正常默认分支不打印外部输出警告，标志为 false。

测试可使用窄 fake Demo adapter/Transcription service 避免真实模型，但必须断言真实目录和文件，不得只检查构造参数。

### 7.2 实现契约

- `DemoService.prepare_input()` 继续支持 `.dem` 与 `.dem.zst`，目标只来自 `store.input_dir`；外部源不写旁路文件；
- `ArtifactStore` 可显式接收 `audio_cache_root` 与 `keep_temp_audio`，旧的只读 `ArtifactStore(job_dir)` 仍可解析旧 Job；
- 默认临时音频任务目录在 Pipeline 结束转录阶段后删除，失败路径也应 best-effort 清理；保留模式不得删除 `debug/temp_audio`；
- 不得把工作区环境覆盖写入 `os.environ`；需要子进程时只传 `runtime.subprocess_environment(...)`；
- `run --output` 允许绝对或相对显式目录，以当前 CLI 含义规范化，但无论它是否碰巧位于工作区内，只要用户显式提供就标记为兼容分支；
- 外部输出 manifest 和日志可显示 Job 内相对产物；可分享 manifest 不保存外部根绝对路径。

### 7.3 验证与提交

```powershell
python -m pytest tests/test_job_runtime.py tests/test_artifact_store.py tests/test_transcription_postprocess.py tests/test_transcription_windowing.py tests/test_transcription_coverage.py tests/test_models_v080.py -q
python -m compileall -q src tests
git diff --check
```

提交建议：

```text
feat: route pipeline assets through workspace runtime
```

提交后停止并报告。

## 8. 批次 C：向导、旧 Job、输出工具、启动器与 benchmark

本批建立在已审查通过的批次 B 上。

### 8.1 入口分类

必须按行为分类，不能仅改 `run`：

- 无路径且只读：`inspect-job`、`explain-output`、`glossary check`、`players list` 默认读取当前 `workspace/jobs`，只需可读运行时；用户显式给路径时可在无当前工作区下查看旧 Job；
- 写 Job：`export`、`retranslate`、`resume`、`comms build-review/render`、`players alias/clear-alias`、确认执行的 `clean --yes` 必须先取得可写运行时；
- 反馈包：默认输出到目标 Job 的 `debug/feedback/`，显式 `--out` 继续可用；实际写入前必须取得可写运行时；
- `clean` 预览保持只读；清理旧 `artifacts/temp_audio` 与新 `debug/temp_audio` 时只触及明确目标；若清理当前 workspace audio cache，只能触及与该 Job ID 对应的单个子目录；
- `benchmark-asr` 是资产写入口，也必须取得一个运行时快照。

对所有写操作：如果目标 Job 不位于当前 `workspace/jobs`，在写入前打印“正在原位置修改外部旧 Job”；不自动移动、不改写旧 Job 路径政策字段。模型与临时音频仍使用当前工作区。

### 8.2 先写测试

至少覆盖：

1. 向导移除输出目录提问和普通 `--output` 选项，开始前显示当前工作区与预计 Job 根；
2. 向导在选择 Demo 后、任何 Job 写入前完成门禁；
3. 向导配置不再采用 defaults 中的旧 `whisper_cache_dir`；
4. 无路径只读命令默认选择当前 `workspace/jobs` 的最新 Job；
5. 显式旧 Job 的 `inspect`/`explain` 在无选择时仍可用且不写任何文件；
6. 旧 Job 的 export/retranslate/resume/comms/alias/clean 写入在无健康工作区时被拒绝；
7. 健康工作区下旧 Job 写入成功、打印外部旧 Job 警告、原地修改且不自动迁移；
8. resume/transcribe 从旧 manifest 读取到的缓存路径不能驱动模型或临时音频；
9. launcher 默认 Job 提示和选择指向当前工作区，不再说“直接回车 = output”；
10. `benchmark-asr --cache-dir` 返回稳定弃用错误；默认每个 benchmark Job 位于 `workspace/jobs`，报告也位于工作区；
11. benchmark 的显式 `--output` 走同一外部兼容分支，不能另写一套路径逻辑；
12. 反馈包默认不再写 cwd；
13. 写门禁路径错误不显示 traceback，带 `--json` 的入口 stdout 仍是单个可解析 JSON 文档。

### 8.3 benchmark 落点

默认 benchmark 每个模型建立一个正常的顶层 Job，例如 `jobs/<timestamp>_benchmark_<model>`；汇总报告写到 `jobs/asr_benchmark_<timestamp>.json`。可以采用等价、无嵌套歧义的可读命名，但不得创建 `jobs/bench_model/<另一个job>` 这种双层 Job 根。

显式 `benchmark-asr --output` 在同一过渡规则下把 Job 和报告写到该根目录；仍使用工作区模型与临时缓存，并显示外部输出警告。所有 model 名在进入 Job ID 前必须经过同一安全命名逻辑。

### 8.4 验证与提交

```powershell
python -m pytest tests/test_wizard_v020.py tests/test_job_tools_v030.py tests/test_comms_overlay_v090.py tests/test_launcher_navigation.py tests/test_feedback_pack.py tests/test_models_v080.py -q
python scripts/check_workspace_cli_e2e.py
python scripts/check_workspace_model_runtime_e2e.py
python -m compileall -q src tests
git diff --check
```

提交建议：

```text
feat: migrate job tools and wizard to workspace
```

提交后停止并报告。

## 9. 批次 D：真实子进程 E2E、CI 与文档

本批建立在已审查通过的批次 C 上。

### 9.1 真实 E2E

新增 `scripts/check_workspace_job_runtime_e2e.py`。它必须启动真实 Python/CLI 子进程，不得直接调用 handler，并完成：

```text
建立隔离的临时 HOME、cwd、状态目录、旧缓存目录、工作区和工作区外 Demo
→ 通过真实 CLI 初始化工作区
→ 真实运行 cs2pov run <external.dem> --to-stage prepare_input
→ 验证 Job 在 workspace/jobs，Demo 是 Job/input 中的独立副本
→ 验证 cwd/output、HOME、旧缓存和源 Demo 目录没有新资产
→ 真实运行一次显式 --output
→ 验证前后兼容警告、外部 Job 与 manifest 标志
→ 验证 manifest 不含工作区根、外部输出根或 HOME 绝对路径
→ 损坏 workspace.json 后再次运行默认和外部输出
→ 验证均在建 Job/复制 Demo 前失败，所有目标根快照不变
```

合成 `.dem` 只运行到 `prepare_input`，不需要 demoparser、CS2、GPU 或模型。测试必须隔离 `HOME`、`USERPROFILE`、`LOCALAPPDATA`、`APPDATA`、`XDG_STATE_HOME` 和 cwd，并对目录集合与已有文件哈希做前后快照。Windows 与 Ubuntu 都要运行。

可再加一个窄的真实子进程场景验证 `--whisper-cache-dir` 拒绝，但不得在 E2E 下载模型。

### 9.2 CI

在现有跨平台 Python matrix 中加入新 E2E。保留并继续运行：

```text
完整 pytest
check_workspace_cli_e2e.py
check_workspace_model_runtime_e2e.py
check_workspace_job_runtime_e2e.py
check_golden_baseline.py
compileall / repository hygiene 等现有门禁
```

不得降低既有矩阵或用 `continue-on-error` 掩盖失败。

### 9.3 文档

只更新当前用户文档，不改 archive：

- 默认流程先 `workspace init/use`，然后 `cs2pov run demo.dem` 或向导；
- 默认 Job 使用当前工作区 `jobs/`，正常用户不再选择输出根；
- 示例中的 `inspect/export/retranslate/comms/feedback` 默认可省略路径，或明确使用 Job 路径；
- `--output` 只作为有警告的临时旧版兼容选项；
- 模型缓存和临时音频永远跟随工作区；
- 旧 Job 可原地查看和修改，但写操作需要健康工作区；
- 当前架构说明改为 01D-A/01D-B 均已接入，不再写“run、Job 尚未完成”；
- 不宣称 Demo 去重、正式迁移、理解翻译、Web UI 或录制已实现。

### 9.4 最终验证与提交

必须重新运行，不得引用旧输出：

```powershell
python -m pytest -q
python scripts/check_workspace_cli_e2e.py
python scripts/check_workspace_model_runtime_e2e.py
python scripts/check_workspace_job_runtime_e2e.py
python scripts/check_golden_baseline.py
python -m compileall -q src tests
git diff --check
git status --short
```

提交建议：

```text
test: gate workspace job filesystem behavior
```

提交后停止并报告。

## 10. 强模型逐批审查门禁

每批 Luna 提交后，主任务强模型必须：

1. 查看完整 diff 与提交范围；
2. 对照本任务书逐项核查；
3. 检查异常路径、Windows 路径、symlink/junction、并发冲突和旧 Job 兼容；
4. 重新运行目标测试；
5. 若有问题，给 Luna 精确修正范围；
6. 只有该批无 Critical/Important 后才允许进入下一批。

最终再由独立强模型做一次只读代码审查。合并门禁为：

- 本任务全部验收项满足；
- 本地全量测试、三个 workspace E2E、golden、compileall、diff check 全绿；
- 独立审查无 Critical/Important；
- PR 的 GitHub CI 全绿。

用户已授权在以上门禁全部满足时自动合并。若出现失败、冲突、数据迁移或超出本任务书的高风险改动，必须停止自动合并并报告。

## 11. 完成定义

01D-B 完成不等于“若干单元测试通过”。必须同时有以下证据：

- 默认新 Job 真实落在当前工作区；
- cwd、源码树、隔离 HOME 和旧模型缓存没有新资产；
- Demo 外部源未被修改；
- 临时音频默认可清理，保留模式可人工找到；
- 外部输出是唯一、显式、带警告和 manifest 标记的兼容例外；
- 旧 Job 读兼容、写门禁、原地修改和工作区缓存均有测试；
- 路径错误不会向普通用户喷 traceback；
- Windows/Ubuntu 真实子进程 E2E 和 GitHub CI 均通过。
