# CS2 POV Translator v0.3 — 实施 Prompt

> **来源:** 3 轮 gstack 审查（/plan-design-review + /plan-eng-review + /plan-devex-review），
> 2026-06-08。17 个决策已锁定，0 个未解决。状态：**READY TO IMPLEMENT**。
>
> **使用方法:** 在新 Claude Code 会话中粘贴此文件内容，逐任务实施。
> 每个任务包含：改什么文件、具体做什么、多少行、怎么验证。

---

## 实施前置条件

开始前请确认：

1. 阅读 `src/cs2tl/web/templates/base.html.j2` — 理解当前 CSS 变量体系和模板结构
2. 阅读 `src/cs2tl/config.py` — 理解当前路径解析逻辑
3. 阅读 `src/cs2tl/dictionary.py` — 理解 CalloutTerm 数据模型和 DictionaryManager
4. 阅读 `src/cs2tl/errors.py` — 理解错误码体系（E1-E8）
5. 阅读 `src/cs2tl/web/routes.py` — 理解 14 个路由和 HTMX 交互模式
6. 运行 `pytest tests/ -x -q` 获取基线——所有 169 个测试必须通过

---

## 总体架构约束

- 单用户本地工具，不引入数据库服务
- Jinja2 + HTMX 模板架构不变，只换 CSS 和 HTML 结构
- Pico.css 内联（不依赖 CDN），~40KB 嵌入 base.html.j2
- CS2 品牌色 #e94560（红色），背景 #1a1a2e（深色），中文栈 Microsoft YaHei UI / PingFang SC
- 7 张服役地图：de_dust2, de_mirage, de_inferno, de_nuke, de_overpass, de_anubis, de_ancient
- 所有错误使用 `[CS2TL-EX-NNNN]` 格式，code + cause + fix 三段式

---

## 任务列表

### T1: 存储路径迁移（copy-then-verify）

**优先级:** P1 — 阻塞后续所有任务（其他组件依赖 cs2tl-data/ 目录）
**文件:** `src/cs2tl/config.py`, `src/cs2tl/web/app.py`, `src/cs2tl/cli/main.py`, `.gitignore`
**预计工作量:** ~100 行 Python

**要做什么:**

1. `config.py` 新增 `_find_project_root()` 函数：
   - 从 `__file__` 位置向上遍历目录，找到第一个含 `.git/` 或 `pyproject.toml` 的目录
   - pip install 场景（site-packages 中无 .git）→ 回退到 `os.getcwd()`

2. `config.py` 新增 `default_data_dir()` 函数：
   - 返回 `{project_root}/cs2tl-data/`

3. `config.py` 修改 `resolve_paths()`：
   - 优先级链：`CS2TL_DATA_DIR` 环境变量 → `./cs2tl-data/`（项目根）→ `~/.cs2tl/`（fallback）

4. `config.py` 新增 `migrate_old_data()` 函数：
   - 检测 `~/.cs2tl/cache/` 是否有旧数据
   - **copy-then-verify**：先复制到新路径 → 验证文件数量和大小 → 确认后删除旧文件
   - 复制失败 → 回滚，保留旧路径，打印警告
   - 交互模式：提示 `"检测到旧缓存 ~/.cs2tl/，迁移到 ./cs2tl-data/？[Y/n]"`
   - 非交互模式（web 启动）：自动 copy-then-verify

5. `app.py` 的 `main()` 函数中，**在 `import faster_whisper` 之前**（而不是 lifespan 中）设置：
   ```python
   os.environ["HF_HOME"] = str(data_dir / "huggingface")
   ```
   注意：实际缓存路径是 `HF_HOME/hub/`，目录名保持 `huggingface/`。

6. `.gitignore` 追加 `cs2tl-data/`

**验证:**
- 新建虚拟环境，`pip install -e .`，运行 `cs2tl config init` → 确认 `cs2tl-data/` 目录创建
- 设置 `CS2TL_DATA_DIR=/tmp/test-data` → 确认使用该路径
- 在 `~/.cs2tl/cache/` 放置测试文件 → 运行首启 → 确认自动迁移且原文件完整
- 运行 `pytest tests/test_config.py -x -q` → 全部通过

---

### T2: Pico.css 内联 + 单栏渐进式布局

**优先级:** P1 — UI 框架统一，后续所有页面改动基于此
**文件:** 所有 7 个模板（`src/cs2tl/web/templates/*.html.j2`）
**预计工作量:** ~200 行改动（删 300 行 CSS，嵌入 40KB Pico.css，加 30 行品牌覆盖，重写管线页 HTML 结构）

**要做什么:**

1. **下载 Pico.css** 最新版 dark theme CSS 文件，内联到 `base.html.j2` 的 `<style>` 块中替换现有 300 行手写 CSS。

2. **品牌变量覆盖**（追加在 Pico.css 之后）：
   ```css
   :root {
     --pico-primary: #e94560;
     --pico-primary-hover: #c03a50;
     --pico-primary-focus: rgba(233, 69, 96, 0.25);
     --pico-background-color: #1a1a2e;
     --pico-font-family: 'Microsoft YaHei UI', 'PingFang SC', 'Noto Sans SC', sans-serif;
     --pico-border-radius: 4px;
     --pico-form-element-spacing-vertical: 8px;
     --pico-form-element-spacing-horizontal: 16px;
   }
   ```

3. **禁止模式**（不引入以下 Pico.css 默认行为）：
   - 不用卡片组件（`<article>` / `.card`）
   - 不用渐变背景
   - 不用圆形图标装饰
   - 不用 emoji 作为设计元素

4. **管线主页改为单栏渐进式**（`import.html.j2`, `preview.html.j2`, `progress.html.j2`）：
   - 导入区 → 进度指示器 → 消息流 → 导出按钮
   - 选中消息的编辑面板改为 **Pico.css 模态框**（`<dialog>` 元素）
   - 团队切换用顶部标签页或 `<select>` 下拉
   - 删除旧的三栏 CSS grid（`.preview-grid`, `.team-sidebar`, `.message-flow`, `.edit-panel`）

5. **词典页改为卡片列表**（`glossary.html.j2`）：
   - 术语按地图分组，每组用地图缩略图作为视觉标题
   - 每条术语用 `<article>` 或 `<details>` 展示三语（俄/英/中 + category 标签）

6. **响应式断点**：
   - ≥1024px：桌面（单栏居中，max-width 1400px）
   - 768-1023px：平板（全宽，间距缩小）
   - <768px：手机（模态编辑变为全屏面板，搜索框占满宽度）

7. **保留现有功能**：
   - HTMX 属性全部保留（`hx-get`, `hx-post`, `hx-trigger`, `hx-target`, `hx-swap`）
   - 无限滚动 sentinel（`#load-more` + IntersectionObserver）
   - 行内编辑 JS 函数（`editGlossaryTerm`, `cancelGlossaryEdit`, `openEditor`）

**验证:**
- 启动 `cs2tl web` → 打开浏览器 → 检查 6 个页面都能正常渲染
- 调整浏览器窗口到 1024 / 768 / 375 宽度 → 布局正确退化
- 导入 demo → 管线进度显示 → 预览页消息流滚动 → 点击消息弹出模态编辑
- 检查控制台无 JS 错误、无 404
- （手动）键盘 Tab 导航能遍历所有可交互元素

---

### T3: 交互状态表实施

**优先级:** P2 — 与 T2 一起做，避免二次改动
**文件:** 所有模板（`import.html.j2`, `progress.html.j2`, `preview.html.j2`, `glossary.html.j2`, `export.html.j2`, `settings.html.j2`）
**预计工作量:** ~100 行模板改动

**要做什么:**

为以下 7 个功能实现五态（加载/空/错误/成功/局部），每态描述用户看到什么：

| 功能 | 加载 | 空 | 错误 | 成功 | 局部 |
|------|------|-----|------|------|------|
| 文件导入 | spinner + "正在解析 demo..." | 上传区突出显示 | "demo 格式不支持" + 错误码 | "导入成功" + 自动跳转进度页 | — |
| 管线进度 | 7 阶段 checklist + 当前阶段高亮 | — | 阶段失败：红色标记 + 错误码 + 重试按钮 | 全部绿色 ✓ + "翻译完成" | 部分阶段完成 |
| 翻译预览 | "正在加载消息..." | "此 demo 无语音数据" + 导入新 demo 链接 | "加载失败" + 重试 | 消息流就绪 | 滚动加载更多 |
| 导出 | spinner + "正在生成 SRT..." | "尚无可用字幕" | "SRT 写入失败" + 错误码 | 下载链接 + 导出按钮 | — |
| 词典搜索 | 输入框 loading 指示器 | "未找到匹配术语" + 建议关键词 | "搜索异常" + 重试 | 术语列表更新 | — |
| 术语编辑 | 行内 spinner | — | "保存失败" + 回滚原始值 | "已保存" 绿色 flash | — |
| 设置保存 | 按钮 loading | — | "保存失败" + 错误详情 | "已保存" 绿色提示 | — |

**关键规则:**
- 空状态必须有温暖提示语 + 下一步引导，禁止 "No items found."
- 错误状态显示具体错误码（如 `[CS2TL-E1-0003]`），不是技术堆栈
- 加载状态用 Pico.css 的 `aria-busy="true"` 属性

**验证:**
- 每个空状态手动触发 → 确认非空白、有引导文案
- 断网后导入 demo → 确认错误提示清晰
- 搜索不存在的术语（如 "xyznonexistent"）→ 确认空结果有提示

---

### T4: Rich 终端进度条

**优先级:** P1
**文件:** 新建 `src/cs2tl/cli/progress.py`，修改 `src/cs2tl/cli/translate.py`
**预计工作量:** ~120 行

**要做什么:**

1. 新建 `src/cs2tl/cli/progress.py`，`PipelineProgress` 类：
   ```python
   class PipelineProgress:
       def __init__(self, enabled: bool = True):
           self.console = Console()
           self.progress = Progress(...) if enabled else None

       def task_model(self) -> TaskID: ...       # Spinner（模型下载不一定长度）
       def task_extract(self, count: int) -> TaskID: ...  # Bar
       def task_transcribe(self, current: int, total: int) -> TaskID: ...  # Bar + 百分比
       def task_translate(self, batch: int, total_batches: int) -> TaskID: ...  # Bar
       def stage_done(self, task_id: TaskID, label: str) -> None: ...
       def stage_failed(self, task_id: TaskID, error: str) -> None: ...
       def __enter__ / __exit__  # 上下文管理器
   ```

2. CLI 直接模式（`cs2tl translate`）启用 Rich 进度条。

3. Web 模式（`cs2tl web`）也启用——用户保留此决定。

4. Rich 输出到 `stdout`，uvicorn 日志到 `stderr`——共存。

**验证:**
- `cs2tl translate test_demo.dem --map de_dust2` → 终端出现 Rich 进度条
- 进度条在管道从头跑到尾，各阶段有正确标签
- `cs2tl web` → 终端同时显示 Rich 进度和 uvicorn 日志，不混乱
- 运行 `pytest tests/ -x -q` → 新增进度模块不破坏已有测试

---

### T5: CalloutTerm 数据模型 + russian_aliases

**优先级:** P1
**文件:** `src/cs2tl/dictionary.py`
**预计工作量:** ~50 行

**要做什么:**

1. 在 `CalloutTerm` dataclass 中新增字段：
   ```python
   russian_aliases: list[str] = field(default_factory=list)
   ```

2. 修改 `_load_one()` 解析逻辑——从 YAML 读取 `ru` 字段填充 `russian_aliases`。

3. 修改 `build_term_table()` 输出三语表格（英/俄/中）。

4. 修改 `MapDictionary.build_index()` 同时索引俄语别名。

5. 修改 `validate_terms()` 检查俄语和英语。

6. 向后兼容：无 `ru` 字段的旧术语默认空列表。

**验证:**
- `CalloutTerm(aliases=["A short"], russian_aliases=["короткий"], chinese_name="A小道", map_name="de_dust2")` 正常创建
- 无 `russian_aliases` 的旧格式术语仍正常加载
- 运行 `pytest tests/test_dictionary.py -x -q` → 全部通过

---

### T6: 删除 git 依赖 + 内置词典加载

**优先级:** P1
**文件:** `src/cs2tl/dictionary.py`（修改），新建 `src/cs2tl/data/builtin_dictionary.yml`（新增），`src/cs2tl/cli/dictionary_cmd.py`（修改）
**预计工作量:** ~200 行改动 + YAML 数据

**要做什么:**

1. **删除** `DictionaryManager` 中的：
   - `ensure_cloned()` 方法
   - `_clone()` 方法
   - `update()` 方法
   - `_git_head()` 方法
   - 所有 `import git` 和 `GitCommandError` 引用

2. **新增** `load_builtin()` 方法：
   - 从 `src/cs2tl/data/builtin_dictionary.yml` 读取（`importlib.resources` 或 `pkg_resources`）
   - 解析 YAML，构建 `MapDictionary` 对象

3. **修改** `load_all()` 方法：
   - 调用 `load_builtin()` 加载内置词典
   - 内置词典始终可用（打包在 wheel 中）

4. **新建** `src/cs2tl/data/builtin_dictionary.yml`：
   - 7 张地图各一个 section，每张 40-70 条术语
   - 格式：`en`（英语别名列表）、`ru`（俄语说法列表）、`zh`（中文术语）、`category`
   - 示例见下方。先用 akiver 词典的英文数据 + LLM 辅助翻译俄语做初版
   - 标注 comment：`# 社区贡献欢迎纠错 — corrections welcome`

5. **修改** `dictionary_cmd.py`：
   - `cs2tl dictionary update` 命令删除（git pull 已不存在）
   - `cs2tl dictionary list` 和 `cs2tl dictionary show` 改为读取内置 YAML

**内置词典 YAML 格式:**
```yaml
# CS2 POV Translator — 内置术语库 (Terminology Database)
# 7 张服役地图的高频报点术语，三语对照（俄/英/中）
# 社区贡献欢迎纠错 — corrections welcome: https://github.com/liyan1775/cs2povtranslator

de_dust2:
  version: "1.0"
  terms:
    - en: ["A short", "catwalk", "cat"]
      ru: ["короткий", "шорт", "кэт"]
      zh: "A小道"
      category: zone
    - en: ["long", "long A", "pit"]
      ru: ["длинный", "лонг", "лонг А", "яма"]
      zh: "A大"
      category: zone
    - en: ["A site", "A bombsite", "A"]
      ru: ["точка А", "плант А"]
      zh: "A包点"
      category: bombsite
    # ... 每张地图 40-70 条 ...

de_mirage:
  version: "1.0"
  terms:
    - en: ["palace", "A palace"]
      ru: ["дворец", "палас"]
      zh: "A2楼"
      category: zone
    # ...
```

**验证:**
- 删除 `cs2tl-data/dictionaries/` 中的 git clone 目录 → 运行翻译 → 管线正常（使用内置词典）
- `cs2tl dictionary list` → 列出 7 张地图
- `cs2tl dictionary show de_dust2` → 显示术语数量和分类统计
- 断网 → `cs2tl translate test_demo.dem --map de_dust2` → 不报错
- `cs2tl dictionary update` → 报错 "此命令已移除，内置词典随 pip install 更新"
- 运行 `pytest tests/test_dictionary.py tests/test_web_routes.py -x -q` → 全部通过

---

### T7: 词典搜索 + 卡片列表（Web 端）

**优先级:** P2
**文件:** `src/cs2tl/web/templates/glossary.html.j2`, `src/cs2tl/web/routes.py`
**预计工作量:** ~80 行

**要做什么:**

1. `glossary.html.j2` 加搜索框：
   - 输入框 `placeholder="搜索术语（俄/英/中）…"`
   - 纯客户端 JS：input 事件 → 对已渲染的术语卡片做 substring contains 匹配
   - 同时在 `ru`（俄语）、`en`（英语别名）、`zh`（中文术语）三个字段搜索
   - 无匹配时显示空状态（T3 中已定义）

2. `routes.py` 的 glossary 路由改术语渲染：
   - 每张地图一个 `<section>`，地图名作为标题
   - 术语用卡片列表展示：俄语别名 + 英语别名 + 中文术语 + category 标签
   - 地图分组可折叠（`<details><summary>`）

**验证:**
- 打开 /glossary → 搜索 "короткий" → 找到 "A小道"
- 搜索 "dust" → Dust2 相关的所有术语出现
- 搜索 "xyznonexistent" → 显示 "未找到匹配术语"
- 输入中文 "小道" → 找到所有含 "小道" 的术语
- 运行 `pytest tests/test_web_routes.py -x -q` → glossary 相关测试通过

---

### T8: csgove 自动下载脚本

**优先级:** P2
**文件:** `src/cs2tl/cli/doctor.py`（修改），新建 `src/cs2tl/cli/csgove_download.py`
**预计工作量:** ~80 行

**要做什么:**

1. 新建 `src/cs2tl/cli/csgove_download.py`：
   ```python
   def download_csgove(target_dir: Path) -> Path:
       """检测 OS/架构 → 从 GitHub Releases 下载 csgove → 返回二进制路径"""
   ```
   - 检测 `sys.platform`（win32/darwin/linux）和 `platform.machine()`（amd64/arm64）
   - 从 `https://github.com/akiver/csgo-voice-extractor/releases/latest` 获取下载 URL
   - 下载到 `{target_dir}/bin/`，Windows 加 `.exe` 后缀
   - 添加执行权限（Unix chmod +x）
   - 返回二进制路径

2. 修改 `doctor.py`：
   - 检测 `csgove` 不在 PATH 时 → offer 自动下载
   - 非交互模式：自动下载（不询问）
   - 交互模式：`"csgove 未找到。自动下载？[Y/n]"`

**验证:**
- 从 PATH 中移除 csgove → `cs2tl doctor` → 提示下载 → 确认 → 二进制下载到 `./cs2tl-data/bin/`
- 重新运行 `cs2tl doctor` → 检测到二进制，通过
- Windows 环境测试下载 `.exe` → 能正常执行

---

### T9: 测试套件补齐

**优先级:** P1 — 与新功能同步编写
**文件:** `tests/test_config.py`, `tests/test_dictionary.py`, `tests/test_web_routes.py`, 新建 `tests/test_progress.py`
**预计工作量:** ~15 个新测试函数

**要做什么:**

1. **config.py 测试**（`tests/test_config.py`，新增 4 个）：
   - `test_find_project_root_from_git` — 从项目目录找到含 .git 的根
   - `test_find_project_root_fallback_to_cwd` — 无 .git 时回退 CWD
   - `test_data_dir_env_var_priority` — CS2TL_DATA_DIR 优先
   - `test_migrate_old_data_copy_verify` — copy-then-verify 迁移

2. **dictionary.py 测试**（`tests/test_dictionary.py`，新增 3 个）：
   - `test_load_builtin_all_maps` — 内置 YAML 包含 7 张地图
   - `test_russian_aliases_parsed` — ru 字段正确解析到 russian_aliases
   - `test_backward_compat_no_ru_field` — 无 ru 的旧术语不崩

3. **progress.py 测试**（新建 `tests/test_progress.py`，4 个）：
   - `test_progress_context_manager` — 上下文管理器正确
   - `test_task_model_spinner` — model 阶段用 spinner
   - `test_task_transcribe_bar` — transcribe 阶段 bar + 百分比
   - `test_progress_disabled` — enabled=False 时无输出

4. **Web 端到端测试**（`tests/test_web_routes.py`，新增 1 个 E2E）：
   - 导入 demo → 检查 job 创建 → 轮询进度 → 预览页有翻译 → 编辑一条 → 导出 SRT 文件

5. **回归测试**（`tests/test_dictionary.py` 和 `tests/test_web_routes.py`，新增 1 个）：
   - `test_dictionary_update_command_removed` — `cs2tl dictionary update` 报友好错误

**验证:**
- `pytest tests/ -x -q --cov=src/cs2tl --cov-report=term` → 覆盖率 ≥ 60%（当前基线 ~40%）
- 所有新增测试通过，所有已有测试通过

---

### T10: DESIGN.md 创建

**优先级:** P3（不阻塞 ship，但应在实施后、发布前完成）
**文件:** 新建 `DESIGN.md`
**预计工作量:** ~20 分钟

**内容:**

```markdown
# CS2 POV Translator — Design System

## Color Tokens
- `--pico-primary`: #e94560 (CS2 accent red)
- `--pico-primary-hover`: #c03a50 (dark red)
- `--pico-background-color`: #1a1a2e (dark background)
- `--pico-color`: #eaeaea (primary text)
- `--pico-muted-color`: #a0a0b0 (secondary text)

## Typography
- Body: Microsoft YaHei UI, PingFang SC, Noto Sans SC, sans-serif
- Mono: Cascadia Code, Fira Code, Consolas, monospace
- Base size: 16px, line-height: 1.6

## Spacing Scale
- xs: 4px, sm: 8px, md: 16px, lg: 24px, xl: 32px

## Border Radius
- sm: 4px, md: 8px

## Component Patterns
- Navigation: Top tab bar, Pico.css nav with custom brand overrides
- Forms: Pico.css form elements, 44px min touch target
- Empty states: Warm message + primary action + context, never "No items found"
- Errors: [CS2TL-EX-NNNN] structured error codes, cause + fix always present

## Forbidden Patterns
- No card grids (use semantic HTML, not `<article>` wrapper)
- No gradient backgrounds
- No circular icon decorations
- No emoji as design elements
- No centered-everything layouts
```

**验证:**
- DESIGN.md 存在，包含上述所有 section

---

### T11: TODOS.md 债务项处理

**优先级:** P3（不阻塞 ship）
**文件:** `TODOS.md`

当前 5 个设计债务项状态：

| ID | 项目 | 本 PR 处理？ |
|----|------|------------|
| D1 | 创建 DESIGN.md | ✅ T10 覆盖 |
| D2 | 交互状态表 | ✅ T3 覆盖 |
| D3 | 响应式断点 + a11y | ✅ T2 覆盖 |
| D4 | minimap 图片 + zone 坐标 | ❌ 延迟（Phase 2 地图浏览器） |
| D5 | Pico.css 品牌变量覆盖值 | ✅ T2 覆盖 |

实施完成后，将 D1/D2/D3/D5 标记为完成，D4 保留。

---

## 实施顺序

推荐的执行顺序（考虑依赖关系）：

```
T1 存储路径 ──┬── T2 Pico.css 迁移 ──┬── T3 交互状态表
               │                      ├── T7 词典搜索+卡片列表
               │                      └── T10 DESIGN.md
               │
               ├── T5 数据模型 ────── T6 内置词典 ──── T7 依赖
               │
               ├── T4 Rich 进度
               │
               └── T8 csgove 自动下载

所有任务完成后: T9 测试补齐 → T11 TODOS 更新
```

**并行机会:** T4（Rich 进度）和 T5+T6（词典改造）互不依赖，可并行。
**关键路径:** T1 → T2 → T3/T7（存储不做好，其他组件不知道文件放哪）

---

## 实施检查清单

- [ ] T1: 存储路径迁移 + copy-then-verify
- [ ] T2: Pico.css 内联 + 单栏布局 + 响应式断点
- [ ] T3: 交互状态表（7 功能 × 5 态）
- [ ] T4: Rich 终端进度条
- [ ] T5: CalloutTerm russian_aliases 字段
- [ ] T6: 删除 git 依赖 + 内置词典 YAML
- [ ] T7: 词典客户端三语搜索 + 卡片列表
- [ ] T8: csgove 自动下载脚本
- [ ] T9: 测试补齐（15 个新测试 + 回归验证）
- [ ] T10: DESIGN.md
- [ ] T11: TODOS.md 更新
- [ ] `pytest tests/ -x -q` 全部通过
- [ ] `cs2tl web` → 浏览器 6 页面正常
- [ ] `cs2tl translate test_demo.dem --map de_dust2` → 完整管线 + Rich 进度
- [ ] 断网 → 管线不报错（内置词典兜底）
- [ ] `cs2tl-data/` 在项目根目录创建
- [ ] 旧数据迁移成功（copy-then-verify）
