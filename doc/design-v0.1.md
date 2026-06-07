# CS2 POV Translator v0.1 — 设计文档

2026-06-07 | Branch: master | Status: DRAFT

## 版本目标

**从「自己能用的 MVP」到「非程序员能用的工具」。**

v0.0 证明了管线跑得通——下载 demo、提取语音、翻译、输出 SRT。但每一步都依赖命令行、需要手动编辑 YAML 词典、翻译结果出来前只能信任黑盒。

v0.1 的核心命题：一个不写代码的 CS2 玩家能独立完成「导入 demo → 运行翻译 → 检查纠错 → 编辑词典 → 导出字幕」全流程。

---

## 一、承接 v0.0：已完成项

| # | 决策 | 结果 |
|---|------|------|
| 1 | 8 阶段管线：extract → transcribe → align → dictionary → rounds → players → translate → subtitles | 两个真实 Faceit demo 端到端跑通 |
| 2 | 翻译批次 50 条/批，5 层 JSON 解析容错 | DeepSeek 截断问题已解决 |
| 3 | 队伍识别：demoparser2.parse_player_info().team_number | 2×5 人正确分队，不依赖 LLM |
| 4 | 时间轴对齐：parse_voice() voice packet tick | SRT 从 3 分钟恢复到完整 30 分钟 |
| 5 | 词典：de_dust2（20 条）+ de_mirage（24 条），Git 独立仓库 | 已接入 translator system prompt |
| 6 | SRT 按队伍分文件输出 | demo.team_2.srt + demo.team_3.srt |
| 7 | 翻译后端：DeepSeek chat API | 极低成本，中文能力强 |
| 8 | 93 个 pytest 测试 | 全部通过 |

### v0.0 阶段踩坑记录（已写入 gstack learnings）

| 坑 | 根因 | 修复 |
|----|------|------|
| SRT 时间轴被压缩到 3 分钟 | csgove split-compact 去除静音，每个玩家 WAV 从 t=0 开始 | voice_aligner.py：从 demoparser2 读 voice packet tick 重建真实时间线 |
| 所有球员显示 team_unknown | awpy 无法解析较新 CS2 demo（UnknownDemoCmd 14399） | 替换为 demoparser2.parse_player_info().team_number |
| LLM 响应被截断 | 1019 片段一次调用，DeepSeek max_tokens 截断 | MAX_SEGMENTS_PER_BATCH=50 |
| JSON 解析失败 | DeepSeek 用 ```json 包裹响应、偶尔截断 | 5 层解析：提取 code block → 完整 JSON → 逐行解析 → 正则 → 原始文本 |
| 球员名 l23n 被误判为临时文件后缀 | Go mktemp 后缀检测规则过宽 | 改为精确匹配：恰好 8 位、全小写+数字 |
| demoparser2 不能直接读 .zst | 缺少 zstandard 解压步骤 | 三处模块各自解压（已知冗余，v0.1 统一） |
| demoparser2 没有 tick_rate() | 方法不存在 | 硬编码 64.0（CS2 Faceit 标准） |

---

## 二、v0.1 新增决策

### A. 替代 csgove：demoparser2 + pyogg 原生语音提取

**选择：** 用 demoparser2.parse_voice() 获取原始 opus 语音包 → pyogg（内置 libopus DLL）解码 → Python wave 模块写 WAV。

**PoC 验证：** 拿真实 demo 的 200 个连续 voice packet，用 pyogg 调用 libopus 解码为 24kHz 16-bit 单声道 PCM。200/200 全部成功，零解码失败，产出 2.0 秒有效音频。WAV 头格式正确。

**消灭的模块和问题：**

| 消掉的 | 原因 |
|--------|------|
| csgove（Go 二进制） | demoparser2 替代，纯 Python 依赖 |
| voice_aligner.py（355 行） | parse_voice() 自带 tick，时间戳一开始就正确 |
| 三处 zst 解压重复 | 提取阶段解压一次，路径向下游传递 |
| WAV 文件堆积 | 固定文件名，每次覆盖不积累 |

**新增依赖：** `pyogg`（Windows/Linux/macOS 均提供预编译 wheel，含 libopus DLL）。

### B. UI 框架：FastAPI + Jinja2 + HTMX

**选择：** 服务端渲染的 Web 应用。

**拒绝的替代方案：**
- Streamlit：reactive 执行模型每次交互重跑整个脚本，状态流隐式，Claude 难以追踪 bug
- Gradio：同样隐式状态重跑问题
- TUI（Textual）：非程序员不会用终端

**选择 FastAPI 的理由：**
- 每个操作对应一个路由（GET /preview/<id> → POST /edit/<id> → 302 redirect），完整因果链可读可测
- `httpx.TestClient` 直接写端到端测试，不需要 Selenium
- Jinja2 服务端渲染，零前端构建工具链
- HTMX 用在小范围局部刷新（编辑保存后不整页重载），总量 < 20 行

### C. 调试方案：gstack browse + pytest TestClient

**双层覆盖：**

| 层 | 工具 | 作用 |
|----|------|------|
| API 回归 | pytest + httpx.TestClient | 运行 < 1 秒，每次 git push 前跑 |
| UI 验收 | gstack browse | 模拟用户操作：导航 → 填表单 → 点击 → 检查 DOM 文本 → 截图。Claude 通过读页面文本、DOM 结构、控制台报错、网络请求来 debug，不需要视觉多模态 |

### D. 通用术语词典：common/glossary.yml

**选择：** 方案 A——在词典仓库中新建 `common/glossary.yml`，与地图目录（de_dust2/、de_mirage/）平级。

**格式：**
```yaml
# common/glossary.yml
# 武器、道具、战术用语等跨地图通用 CS 术语

AWP:
  zh: "大狙"
  en_aliases: ["awp", "AWP"]
  category: weapon
  notes: "AWP 狙击步枪的中文俗称"

smoke:
  zh: "烟雾弹"
  en_aliases: ["smoke", "smokes"]
  category: utility

flash:
  zh: "闪光弹"
  en_aliases: ["flash", "flashbang", "pop flash"]
  category: utility

HE:
  zh: "手雷"
  en_aliases: ["HE", "HE grenade", "nade", "grenade"]
  category: utility

Molotov:
  zh: "燃烧弹"
  en_aliases: ["molly", "molotov", "fire"]
  category: utility
```

**加载逻辑：** 词典管理器在加载所有地图 zones.yml 后，额外加载 `common/glossary.yml`。翻译时两部分术语合并注入 system prompt。

### E. 导出前预览：群聊式对话流

**交互设计：**

- 左侧：队伍选择器（team 2 / team 3）
- 中间：按时间排序的消息流，每条消息显示：
  - 玩家名 + 时间戳
  - 原文（灰色，较小字号）
  - 译文（白色/主色，正常字号）
- 右侧：编辑面板（点击任一条消息后展开）
  - 直接编辑译文文本框
  - 保存后更新预览 + 标记该条为「已编辑」
  - 导出 SRT 时使用编辑后的文本

**为什么像群聊：** CS2 队内语音本质就是群聊——快速的、上下文交织的多人对话。群聊界面比字幕列表更直观，用户一眼能看出翻译是否合理。

### F. 预览编辑：直接改单条译文

**选择：** 方案 A——在预览中点击一条消息，直接编辑译文文字，保存后反映到最终 SRT。

**不做 v0.1：** 方案 B（编辑后自动生成 glossary 规则。如改 "AWP → 狙击枪" 时自动向 glossary 添加条目）。保留到 v0.2。

### G. 双语 SRT

**格式：** 原文在上，译文在下。标准 SRT 格式无法容纳双语，用双条目实现：

```
1
00:00:03,400 --> 00:00:05,200
[AudiRS6] I'm holding A long

2
00:00:03,400 --> 00:00:05,200
[AudiRS6] 我在架 A 大
```

**收益：** B站观众看到双语字幕 → 弹幕/评论区纠正错误翻译 → 收集反馈维护 glossary。社区校对成本趋近于零。

### H. zst 解压统一

**问题：** v0.0 中 extractor、player_resolver、voice_aligner 各自解压 .dem.zst，每次生成临时文件。

**v0.1 方案：** 提取阶段（extractor）解压一次，解压后的 .dem 路径通过管线上下文向下游传递。player_resolver 和 voice_aligner 直接复用。临时文件在管线结束后统一清理。

### I. WAV 文件清理

**v0.0 问题：** csgove 每次运行生成新的随机 temp 后缀 WAV（`demo_2qg_fqlx_-AudiRS6_...wav` → `demo_d0b74tba_-AudiRS6_...wav` → `demo_z_jmi91g_-AudiRS6_...wav`），同一玩家 3+ 份 WAV 堆积。

**v0.1 方案：** 随决策 A（demoparser2 替代 csgove）自然解决——新提取器生成固定文件名，每次覆盖写入。

---

## 三、架构变化

### v0.0 管线
```
extract (csgove) → transcribe → align (voice_aligner) → dictionary → rounds → players → translate → subtitles
     ↑_zst_解压              ↑_zst_解压                      ↑_zst_解压
```

### v0.1 管线
```
extract (demoparser2+pyogg) → transcribe → dictionary → rounds → players → translate → preview(Web UI) → subtitles
     ↑_一次zst解压，路径向下传递                                         ↑_用户在此编辑、导出
```

**消掉的模块：** voice_aligner.py（不再需要——时间戳在提取阶段就已正确）

### 新增模块

```
src/cs2tl/
├── extractor.py          # 重写：demoparser2 + pyogg 替代 csgove
├── web/                  # 新增 Web UI
│   ├── app.py            # FastAPI 应用入口
│   ├── routes.py         # 路由：预览、编辑、导出
│   └── templates/        # Jinja2 模板
├── shared.py             # 新增：共享工具（zst 解压等）
└── ...                   # 其他模块不变
```

---

## 四、验收条件

| 条件 | 内容 |
|------|------|
| **端到端验收** | Claude 模拟新用户操作：启动 Web UI → 导入新 demo → 运行全管线 → 在预览中检查翻译 → 编辑一条译文 → 导出双语 SRT → 编辑 common/glossary.yml → 重新翻译验证 glossary 生效 |
| **验收素材** | `/d/agent_workspace/cs2demos/1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst`（285MB，最新下载的 Faceit demo） |
| **回归测试** | 93 个已有 pytest + 新增 Web UI TestClient 测试 + 新增 extractor 测试全部通过 |
| **glossary 验证** | 翻译结果中武器、道具名称使用了 glossary 中的中文术语（如 "AWP" → "大狙"） |

---

## 五、暂缓到 v0.2+

| # | 项 | 原因 |
|---|------|------|
| 1 | ASS 格式（队伍颜色标注） | 等双语 SRT 实际导入剪映用过，确认需求 |
| 2 | 翻译加入回合上下文 | 等用户反馈——当前逐句翻译是否真有歧义 |
| 3 | LLM 横向对比（GPT-4o / Claude） | DeepSeek 够用且极便宜 |
| 4 | 词典可视化编辑器（地图 SVG 叠加标注） | 工作量太大，先靠 GitHub 网页编辑 YAML |
| 5 | 预览编辑反哺 glossary（方案 B） | v0.2 做——从「改了这条」到「记住这条规则」 |

---

## 六、未解决问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | 第一个真实用户（你自己）的使用反馈尚未收集——双语 SRT 导入剪映后的体验、字幕阅读体验、翻译质量是否够「地道」 | 可能改变 G 和后续决策 |
| 2 | demoparser2 + pyogg 的新提取器需要与 csgove 的输出做 A/B 对比——音频质量、时间戳精度、边界 case（丢包、corrupt opus frame） | 如果 pyogg 解码有异常，可能需要 fallback 到 ffmpeg 方案 |
| 3 | Web UI 的首屏加载——一个 demo 可能有 1000+ 条消息，群聊界面如何分页/虚拟滚动 | 如果不处理，30 分钟比赛的消息流可能卡顿 |

---

## 附录 A：PoC 代码（demoparser2 + pyogg 语音提取）

```python
"""PoC: CS2 voice extraction without csgove."""
from demoparser2 import DemoParser
from pyogg.opus import opus_decoder_create, opus_decode
import ctypes, wave
from pathlib import Path
from collections import Counter

SAMPLE_RATE = 24000
CHANNELS = 1
MAX_SAMPLES = 5760

parser = DemoParser(str(demo_path))
voice = parser.parse_voice()
# → [{tick, steamid, bytes}, ...]

# Group by steam_id, sort by tick
by_player: dict[str, list] = {}
for pkt in voice:
    sid = str(int(pkt["steamid"]))
    if len(sid) == 17 and sid.startswith("7656"):
        by_player.setdefault(sid, []).append(
            (pkt["tick"], pkt["bytes"])
        )

# Decode per player, write WAV
err = ctypes.c_int()
decoder = opus_decoder_create(
    ctypes.c_int32(SAMPLE_RATE), ctypes.c_int(CHANNELS),
    ctypes.pointer(err)
)
pcm_buf = (ctypes.c_short * MAX_SAMPLES)()

for sid, packets in by_player.items():
    packets.sort(key=lambda x: x[0])
    all_pcm = bytearray()
    for _, opus_bytes in packets:
        raw = (ctypes.c_ubyte * len(opus_bytes))(*opus_bytes)
        samples = opus_decode(
            decoder, ctypes.cast(raw, ctypes.POINTER(ctypes.c_ubyte)),
            ctypes.c_int32(len(opus_bytes)),
            ctypes.cast(pcm_buf, ctypes.POINTER(ctypes.c_short)),
            ctypes.c_int32(MAX_SAMPLES), ctypes.c_int(0)
        )
        if samples > 0:
            for j in range(samples):
                all_pcm.extend(pcm_buf[j].to_bytes(2, 'little', signed=True))

    if all_pcm:
        wav = voices_dir / f"{sid}.wav"
        with wave.open(str(wav), "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(all_pcm)
```

## 附录 B：gstack learnings 索引

v0.0 阶段记录的 6 条 learnings：
- `csgove-compact-loses-timeline`
- `awpy-fails-new-cs2-demos`
- `deepseek-batch-and-parse`
- `player-name-from-wav-filename`
- `team-number-not-t-ct`
- `zst-decompression-needed-everywhere`

---

## 三、UI 设计决策（/plan-design-review 审查通过）

### 导航与信息架构

| 决策 | 选择 | 理由 |
|------|------|------|
| 全局导航 | **顶部标签导航**（导入 / 预览 / 词典 / 导出） | 用户可随时切换——边等管线跑边编辑词典 |
| 首页 | **导入页作首页** | 第一步就是选 demo 文件，零歧义 |
| 预览页层次 | **消息流为主（60%+ 视觉空间）** | 读翻译是核心任务——队伍切换和编辑是辅助 |
| 词典编辑器 | **完整 CRUD**（增删改查 + 搜索 + 批量导入） | 非程序员友好——表单直接写 glossary.yml + git push |

### 交互状态

| 状态 | 设计方案 |
|------|----------|
| 管线运行中 | 6 阶段清单 + HTMX 每 3-5 秒轮询刷新。当前阶段高亮 + spinner。**无动画、无 WebSocket**——办公本 CPU 全给 Whisper，UI 自身零开销 |
| 预览页空态 | "还没有翻译结果，去导入 demo 开始吧" + 跳转到导入标签的按钮 |
| 词典页空态 | "词典仓库尚未克隆，点击更新" + 更新按钮 |
| 导入页空态 | 天然无空态（本身就是起点） |
| 阶段失败 | 中文大白话报错（如"翻译 API 暂时不可用，已保留原文"），部分失败不阻断整体——导出前警告提示未翻译条目数 |

### 用户旅程：三处安心点

| 时刻 | 内容 | 缓解的焦虑 |
|------|------|-----------|
| 导入后 | 显示 demo 基本信息（地图名、10 球员名、2 队） | "文件选对了吗？" |
| 管线中 | 已完成阶段摘要（"已提取 10 人语音"、"已识别为 de_dust2"） | "在正常跑吗？" |
| 导出前 | 统计摘要（"已翻译 844 条，其中 3 条使用了词典术语，0 条失败"） | "翻译质量靠谱吗？" |

### 视觉规范

```css
:root {
  --color-bg-primary: #1a1a2e;
  --color-bg-secondary: #16213e;
  --color-accent: #e94560;
  --color-accent-secondary: #0f3460;
  --color-text-primary: #eaeaea;
  --color-text-secondary: #a0a0b0;
  --color-border: #2a2a4a;
  --font-body: 'Microsoft YaHei UI', 'PingFang SC', 'Noto Sans SC', sans-serif;
  --font-mono: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  --space-xs: 4px; --space-sm: 8px; --space-md: 16px; --space-lg: 24px; --space-xl: 32px;
  --radius-sm: 4px; --radius-md: 8px;
}
```

| 规范 | 值 |
|------|-----|
| 字体 | 中文优先系统字体栈——Windows 用 Microsoft YaHei UI，macOS 用 PingFang SC，Linux 用 Noto Sans SC。**不使用外部字体 CDN** |
| 暗色主题 | #1a1a2e 主背景 / #16213e 次背景 / #e94560 强调色 |
| 响应式 | **仅桌面 ≥1024px**。视频制作用桌面端，v0.1 不做移动适配 |
| 触控目标 | ≥44px（键盘导航友好） |
| 对比度 | 正文 #eaeaea 对 #1a1a2e ≈ 12:1，辅助文字 #a0a0b0 ≈ 5:1，均满足 WCAG AA |
| 无障碍 | 标签页用 `role="tablist"`，消息区用 `role="log"`，所有交互元素有可见聚焦环 |

---

## 四、NOT in scope（显式推迟）

| 项 | 原因 |
|----|------|
| 移动端 / 平板适配 | 视频制作工作流在桌面端，v0.1 不做 |
| DESIGN.md 建立 | 无历史设计系统，CSS 变量体系已在本文档定义，v0.2 跑 /design-consultation |
| 仪表盘首页 | 用户选导入页作首页，仪表盘留 v0.2 |
| ASS 格式输出 | 等双语 SRT 实际验证 |
| 预览编辑反哺 glossary（方案 B） | v0.2 |
| 翻译加入回合上下文 | 等用户反馈 |

## 五、What already exists（可复用）

| 资源 | 位置 | 用途 |
|------|------|------|
| 6 阶段管线（CLI） | `src/cs2tl/cli/translate.py` | 阶段名称、进度描述直接映射到 Web UI 进度页 |
| 93 个 pytest | `tests/` | 管线核心逻辑已覆盖，Web UI 只需测路由 |
| gstack browse | `~/.claude/skills/gstack/browse/` | UI 验收自动化——模拟用户操作 |
| 词典仓库 | ~/.cs2tl/dictionaries/ | Web UI 直接读写同一路径 |

## 六、Eng Review 新增决策（2026-06-07）

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| D1 | 复杂度检查：13+ 文件是否过度设计 | 保持完整计划 | 6 个是 HTML 模板，删除 voice_aligner 降低复杂度 |
| D2 | 后台管线执行模型 | Web 调用 CLI 子进程 | 管线出问题不影响 Web；CLI 和 Web 共享同一套代码；调试时两个面独立 |
| D3 | 进度持久化 | progress.json 文件 | 刷新网页 → 重读文件 → 进度恢复 |
| D4 | 用户启动方式 | 桌面 .bat 快捷方式 | 非程序员双击即用，自动打开浏览器 |
| D5 | opus 坏帧处理 | 跳过坏帧 + 记录警告 | 200/200 PoC 成功但不冒险——万一坏帧不拖垮全流程 |
| D6 | 球员名解析来源 | 从 demoparser2 获取 name | 不再依赖 WAV 文件名格式；删 50 行文件名解析逻辑 |
| D7 | PoC 代码工程化 | 加日志 + 错误码 + 常量 | opus_decode < 0 时 log warning，decoder 创建失败抛 CS2tlError |
| D8 | extractor 测试策略 | mock 单元测试 + 1 个真实集成测试 | 单元测 < 1 秒覆盖所有分支，集成测验证真实 demo |
| D9 | 预览页 1000+ 消息加载 | 分批加载，滚动追加 | 首屏 50 条，往上滚 HTMX 自动加载更多；DOM 保持 50-200 条 |

### 管线架构细化（D2/D3 决策）

```
用户双击 start-cs2tl.bat
  → 浏览器打开 http://localhost:8765
  → 导入页：选择 .dem/.dem.zst
  → POST /import → Web 后台启动子进程：
      cs2tl translate demo.dem --machine-readable
  → 302 到 /progress/<job_id>
  → CLI 每阶段完成 → 写 progress.json
  → HTMX 每 5 秒 GET /progress/<id>/status → 读 progress.json → 返回 HTML 片段
  → 刷新页面 → 重读 progress.json → 进度恢复
  → 管线完成 → 导出页显示统计 + SRT 下载
```

### 错误传播路径（D5/D7 决策）

```
opus_decode < 0 → log warning + 计数器 +1 → 跳过此帧，继续下一个
opus_decoder_create → NULL → CS2tlError(E1-0004) → progress.json 写 error
demoparser2 异常 → CS2tlError(E1-0002) → progress.json 写 error
DeepSeek API 异常 → 已有 fallback "[翻译失败]" → 部分失败不阻断整体
```

Web UI 读 progress.json 的 `error` 字段，显示 message + fix（中文大白话）。

---

## 七、实现任务清单

按依赖关系排序：

- [ ] **T1 (P1)** — 重写 extractor.py：demoparser2 + pyogg 替代 csgove
  - 文件：`src/cs2tl/extractor.py`（重写 ~150 行）
  - 关键：opus 解码容错 + CS2tlError 接入 + tick→时间戳
  - 验证：`pytest tests/test_extractor.py -v`

- [ ] **T2 (P1)** — 新增 shared.py：统一 zst 解压
  - 文件：`src/cs2tl/shared.py`（新增 ~30 行）
  - 验证：`pytest tests/test_shared.py -v`

- [ ] **T3 (P1)** — 修改 player_resolver.py：从 demoparser2 获取球员名
  - 文件：`src/cs2tl/player_resolver.py`（修改 ~20 行，删 ~50 行）
  - 验证：`pytest tests/test_player_resolver.py -v`

- [ ] **T4 (P1)** — 删除 voice_aligner 模块
  - 文件：删除 `src/cs2tl/voice_aligner.py`, `tests/test_voice_aligner.py`

- [ ] **T5 (P1)** — CLI 管线适配：移除 align stage + 加 --machine-readable
  - 文件：`src/cs2tl/cli/translate.py`（修改 ~30 行）
  - 关键：JSON 进度输出到 progress.json

- [ ] **T6 (P2)** — FastAPI Web 应用骨架
  - 文件：`src/cs2tl/web/app.py`, `src/cs2tl/web/routes.py`（新增 ~300 行）
  - 文件：`src/cs2tl/web/templates/base.html.j2`（新增）
  - 验证：`pytest tests/test_web_routes.py -v`

- [ ] **T7 (P2)** — 导入页 + 进度页 + HTMX 轮询
  - 文件：`src/cs2tl/web/templates/import.html.j2`, `progress.html.j2`（新增）
  - 关键：子进程启动 + progress.json 读写

- [ ] **T8 (P2)** — 预览页：群聊消息流 + 编辑面板
  - 文件：`src/cs2tl/web/templates/preview.html.j2`（新增）
  - 关键：分批加载（首屏 50 条 + HTMX 滚动追加）

- [ ] **T9 (P2)** — 词典 CRUD 页
  - 文件：`src/cs2tl/web/templates/glossary.html.j2`（新增）
  - 关键：git push on save

- [ ] **T10 (P2)** — 导出页：统计摘要 + 双语 SRT 下载
  - 文件：`src/cs2tl/web/templates/export.html.j2`（新增）

- [ ] **T11 (P2)** — 桌面启动脚本
  - 文件：`start-cs2tl.bat`（新增）

- [ ] **T12 (P3)** — gstack browse 验收
  - 模拟用户全流程：启动 → 导入 → 看进度 → 预览 → 编辑 → 导出

---

## 八、NOT in scope（Eng Review 确认 + 新增）

| # | 项 | 原因 |
|---|------|------|
| 1 | ASS 格式 | 等双语 SRT 验证后 |
| 2 | 翻译加入回合上下文 | 等用户反馈 |
| 3 | LLM 横向对比 | DeepSeek 够用 |
| 4 | 词典可视化编辑器 | 工作量太大 |
| 5 | 预览编辑反哺 glossary | v0.2 |
| 6 | 移动端适配 | 视频制作在桌面端 |
| 7 | DESIGN.md | CSS 变量已定义 |
| 8 | 仪表盘首页 | 导入页作首页 |
| 9 | opus 坏帧 vs csgove 的 A/B 对比 | 跳过坏帧方案已定，对比留 v0.2 |
| 10 | WebSocket 实时推送 | HTMX 轮询已满足需求 |

---

## 九、What already exists（可复用）

| 资源 | 位置 | 用途 |
|------|------|------|
| 7 阶段管线（CLI） | `src/cs2tl/cli/translate.py` | 阶段名称、进度描述直接映射到 Web UI 进度页 |
| demoparser2 集成 | `src/cs2tl/player_resolver.py:88-97` | 已有 parse_player_info() 调用——extractor 复用相同模式 |
| 错误码体系 | `src/cs2tl/errors.py` | E1 系列扩展 E1-0004（opus decoder 失败），其余复用 |
| 93 个 pytest | `tests/` | 管线核心逻辑已覆盖，Web UI 只需测路由 |
| gstack browse | `~/.claude/skills/gstack/browse/` | UI 验收自动化 |
| 词典仓库 | ~/.cs2tl/dictionaries/ | Web UI 直接读写同一路径 |
| zst 解压逻辑 | `extractor.py:172-196` | 已有完整实现——搬到 shared.py |

---

## 十、失败模式检查

| 失败场景 | 是否静默 | 有无测试 | 有无错误处理 | 用户看到 |
|----------|---------|---------|-------------|---------|
| opus decoder 创建失败 | 否 | 有（mock） | CS2tlError(E1-0004) | progress.json error → UI 显示 message + fix |
| opus 单帧解码失败 | 部分（log warning） | 有（mock 注入坏帧） | skip + 计数器 | 导出页显示 "跳过 3 帧" |
| demoparser2 崩溃 | 否 | 有 | CS2tlError | UI 显示错误 |
| CLI 子进程崩溃 | 否 | 有 | progress.json 写 exit_code + stderr | UI 显示哪一步失败 |
| DeepSeek API 限流 | 否 | 已有 | retry 3 次 → "[翻译失败]" | UI 显示警告 + 未翻译数 |
| 词典 git push 失败 | 否 | 有 | 返回错误消息 | UI 弹窗 "推送失败，请检查网络" |
| 刷新进度页 | — | 有 | 重读 progress.json | 进度恢复 |

**无 critical gap。** 所有失败路径都有处理方案。

---

## 十一、并行化策略

| Lane | 任务 | 依赖 |
|------|------|------|
| A | T1 (extractor) + T2 (shared) + T4 (删除 voice_aligner) | — |
| B | T3 (player_resolver 修改) | —（独立于 A） |
| C | T5 (CLI 适配) | T1, T4 完成后 |
| D | T6-T10 (Web UI) | C 完成后 |

**执行顺序：** A + B 可并行 → 合并 → C → D → T11（启动脚本）→ T12（验收）

---

## GSTACK REVIEW REPORT

| Review | Trigger | Runs | Status | Findings |
|--------|---------|------|--------|----------|
| Plan CEO Review | /autoplan | 1 | CLEAR | Scope & strategy confirmed |
| Plan Eng Review | /plan-eng-review | 1 | CLEAR | 9 issues → 9 resolved. Architecture: subprocess + progress.json + .bat launcher. Code quality: demoparser2 names + PoC hardening. Tests: mock + 1 integration. Perf: lazy load messages. |
| Plan Design Review | /plan-design-review | 1 | CLEAR | 7 passes: IA 3→7, States 2→7, Journey 3→8, AI Slop 5→8, Design Sys N/A, Responsive 2→7, Decisions 10/10 resolved. Score 3.3→7.3/10 |
| Plan DX Review | /autoplan | 1 | ISSUES | From autoplan — stale (2 commits behind). Key DX pain points addressed by design: no Go binary, pure Python deps, zero build toolchain |

**CODEX:** not run (no OpenAI key configured)

**CROSS-MODEL:** not applicable

**UNRESOLVED:** 0 — all 19 decisions (10 design + 9 eng) resolved

**VERDICT:** DESIGN + ENG CLEARED — plan ready for implementation
