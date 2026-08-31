# 架构说明

本文说明 CS2 POV Translator 的核心设计。项目目标不是做一个炫技 demo，而是做一个能长期演进的本地字幕工程工具。

## 一句话架构

```text
Demo 输入
  → PipelineEngine
  → Job 目录
  → 中间产物 artifacts
  → 可复跑/可检查/可导出的 SRT 字幕工程
```

CLI、`.bat`、未来 UI 都只是入口。核心是 PipelineEngine 与 Job artifacts。

## 分层结构

```text
src/cs2pov/
  cli/          # 命令行、向导、菜单式启动器
  pipeline/     # PipelineEngine、Manifest、Progress
  domain/       # Player/Round/Segment/Subtitle 等核心模型
  services/     # 业务服务：demo、voice、transcription、translation、subtitle、dictionary
  adapters/     # 外部依赖适配：demoparser2、PyOgg、faster-whisper、LLM
  storage/      # ArtifactStore、ConfigStore、JSONL 工具
```

## 核心原则

1. **本地优先**：demo、WAV、输出字幕默认留在本地。
2. **阶段明确**：每个阶段都有输入、输出、日志和状态。
3. **中间产物可审计**：JSON / JSONL 是项目内部 API。
4. **入口不拥有业务逻辑**：CLI/Wizard/Launcher 只负责交互，PipelineEngine 负责流程。
5. **外部依赖适配化**：demoparser2、PyOgg、Whisper、LLM 都通过 adapter/service 接入。
6. **失败可反馈**：feedback 包排除大文件和敏感信息，保留诊断产物。

## Pipeline 阶段

| 阶段 | 作用 | 主要产物 |
|---|---|---|
| prepare_input | 复制或解压 `.dem.zst` | `input/demo.dem` |
| inspect_demo | 读取地图、玩家、demo 信息 | `artifacts/demo_info.json` |
| extract_voice | 解析语音包并解码 Opus | `artifacts/voice/` |
| build_voice_activity | 构建语音活动时间轴 | `artifacts/voice_activity.jsonl` |
| parse_rounds | 解析并清洗回合边界 | `artifacts/rounds_raw.json`, `artifacts/rounds.json` |
| transcribe | Whisper 转录并映射回 demo 时间轴 | `artifacts/transcript_segments.jsonl` |
| build_round_contexts | 以回合为单位聚合队伍语音 | `artifacts/round_contexts.jsonl` |
| translate | 按回合调用 LLM 翻译 | `artifacts/translated_segments.jsonl` |
| export_subtitles | 导出多种 SRT | `final/`, `review/`, `debug/` |

## Job 目录

一个 Job 目录就是一个字幕工程。

```text
jobs/20260610_161929_de_mirage/
  input/                  # demo 副本或解压结果
  artifacts/              # 可复跑的中间产物
  final/                  # 最推荐给剪辑软件使用的字幕
  review/                 # 校对用字幕
  debug/                  # 排查用字幕
  manifest.json           # 阶段状态和配置快照
  progress.log            # 进度日志
  errors.log              # 错误日志
```

## Manifest

`manifest.json` 保存 Job 的配置、阶段状态、关键 artifact 路径。公开/反馈场景中不能包含：

- API key
- 原始本地绝对路径
- 原始 demo 文件
- 大音频路径

v0.6.1 起，artifact 路径统一尽量使用 Job 内相对路径。

## 为什么按回合翻译

CS2 队内语音很短、碎、上下文强。逐句翻译容易误译；按回合聚合后，LLM 能看到同一回合的战术沟通，再把翻译回填到原时间轴。

## 为什么先 CLI

项目真正难点是 demo 解析、语音解码、ASR、LLM、时间轴回填、恢复与反馈，不是窗口。强引导 CLI 可以先把主链路打磨稳定，再考虑 UI。

## 为什么词典不硬替换

词典用于 prompt 约束和 warning 报告，不做强制字符串替换。原因是 ASR 可能误识别，如果翻译后硬替换，会把错误放大。当前 `de_mirage` / `de_dust2` 词典试点只验证机制，不追求全地图覆盖。

# 工作区 runtime 与模型边界

`WorkspaceRuntime` 已由 Luna-01D-A/01D-B 接入模型扫描、加载、run、Job、Demo、向导、输出和临时音频路径。默认 Job 使用当前工作区 `jobs/`，模型缓存与临时音频跟随工作区；旧配置与环境缓存仅作为只读迁移候选。显式 `--output` 是带警告的旧版兼容选项，旧 Job 可原地读取和修改，但写操作需要健康工作区。理解翻译、Web UI、录制和正式迁移不属于当前实现范围。
