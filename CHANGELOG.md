# Changelog

## v0.9.8 - Comms Overlay 默认无时间显示

- 回撤 v0.9.7 的固定 `freeze_seconds=5` 默认方案：不同平台、不同回合的准备期不稳定，默认展示倒计时会降低可信度。
- Comms Overlay 默认只显示 `Round + 选手 + 中文 + 原文`，不再显示 `1:55` / `准备 0:03`。
- `show_at_seconds` 继续作为内部播放时序保留，人工校对后仍可精确控制消息出现顺序。
- 新增 `time_display` 选项：`none` 默认、`elapsed` 显示 `+0:07`、`round_clock` 作为实验倒计时。
- `round_XX.yaml` 新增 `time_display: none`，README/测试计划说明为何正式成片不建议显示不可靠倒计时。

## v0.9.5 - Windows .bat 编码修复版

- 修复中文 Windows 双击 `.bat` 时，UTF-8 中文 `echo` / 注释被 CMD 按 GBK 解析导致乱码命令的问题。
- `Start_CS2_POV_Translator.bat`、`Install_CS2_POV_Translator.bat`、`START_HERE_DOUBLE_CLICK.bat` 改为 ASCII-only；中文提示统一由 Python launcher / 文档输出。
- 新增 `README_FIRST_READ_ME_FIRST.txt`，避免中文文件名在部分 zip/终端环境下显示异常。
- 新增 release-entry 测试：强制校验 `.bat` 文件可用 ASCII 解码且无 UTF-8 BOM。
- 不改变 Comms Overlay 主链路、渲染参数、demo/ASR/翻译流程。

## v0.9.4 - Windows release-entry pytest 编码修复版

- 修复 v0.9.3 在 Windows/GBK 环境下 release-entry pytest 捕获中文启动自检输出时可能失败的问题。
- 统一启动入口、launcher、wizard、README、版本自检到 0.9.4。
- 不改变 Comms Overlay 主链路与渲染参数。

## v0.9.3 - 发布入口可信版与 clean-room 测试要求

- 发布包顶层目录改为 `cs2pov_arch_project_v0_9_3`，避免用户把新版解压进旧 `cs2pov_arch_project` 后继续双击外层旧 `.bat`。
- 新增 `README_FIRST_先看我.txt` 与 `START_HERE_DOUBLE_CLICK.bat`，让用户一眼看到正确入口。
- `Start_CS2_POV_Translator.bat` 启动时显示当前运行目录，并在进入菜单前运行 `scripts/launch_sanity_check.py`。
- 启动自检会核查 `cs2pov.__version__ == 0.9.3`，并确认 Python 加载的是当前文件夹 `src/` 下的源码；若被旧 `.venv` / 旧安装污染，会直接阻止继续运行。
- 启动器和安装器会检测 `cs2pov_arch_project/cs2pov_arch_project` 这类嵌套目录风险，并提示用户改用 clean-room 解压。
- `Install_CS2_POV_Translator.bat` 增加安装目录提示、clean-room 提醒、安装后启动自检。
- 测试计划升级：要求本地 agent 先清洁测试目录，记录真实 `.bat` 绝对路径、启动菜单前 60 行、目录 tree，不能只用 Job 反馈包证明用户入口通过。

## v0.9.2 - 极简 .bat 主菜单与当前源码强制加载

- 重构 `.bat` 主入口体验：启动页只保留 Comms Overlay 核心流程，不再显示旧字幕工具时代的长说明。
- 重构 launcher 主菜单：从 15 个并列入口收敛为 6 个核心入口：新建工程、渲染 Overlay、查看工程、打包反馈、启动前检查、设置与高级工具。
- 将 SRT 导出、重翻译、恢复、词典、玩家别名、模型管理、doctor 等功能收进「设置与高级工具」，避免新用户一打开就被专家命令淹没。
- `Start_CS2_POV_Translator.bat` 与安装脚本现在会显式设置 `PYTHONPATH=%CD%\src;%PYTHONPATH%`，优先加载当前文件夹源码，降低旧 `.venv` / 旧 editable install 导致显示 v0.8.x 过时菜单的概率。
- README、向导提示和测试更新为 v0.9.2 的「核心菜单」工作流。

## v0.9.1 - Comms Overlay 观感与 .bat 工作流修复

- Comms Overlay 正式成为默认主功能：`.bat` 与向导文案改为「新建 POV 通讯流工程」，新建工程结束后自动生成 `review/comms_rounds/round_XX.yaml` 与 `final/comms_feed/`。
- 默认 overlay 改为右侧贴边的浮动消息卡片：面板更窄、字体略小、同屏默认最多 6 条，不再绘制 v0.9.0 的大黑色外层面板。
- 修复最底部语句卡片可能溢出外层通讯框的问题：渲染前先测量卡片高度，空间不足时优先保留最新消息并丢弃更旧消息。
- 新增轻量淡入过渡：新消息不再完全硬切出现。
- `cs2pov comms render` 新增 `--fade-seconds` 与 `--classic-panel`；需要回到 v0.9.0 大面板时可显式开启 classic panel。
- `.bat` 菜单新增 Comms Overlay 入口：普通用户可在菜单中生成 YAML、选择目标队伍 2/3、渲染 preview/green/alpha，不再必须手敲专家命令。
- `comms build-review` 完成后显示实际导出范围，帮助确认是否只导出了 POV 所需的一队 5 人。

## v0.9.0 - Comms Overlay MVP

- 新增 `cs2pov comms build-review`：从已有 Job 的 `translated_segments.jsonl` 生成按回合组织的 `final/comms_feed/comms_feed.json`、`comms_feed.md`、`comms_feed.html`。
- 新增 `review/comms_rounds/round_XX.yaml`：每回合一个可人工校对中间产物，可修改 `show_at`、`speaker`、`zh`、`source`、`enabled`，再只重渲染该回合。
- 新增 `cs2pov comms render`：从校对后的 YAML 渲染右侧中部浮动通讯流素材，支持 `preview`、`green`、`alpha`、`png` 格式。
- 展示形态为 POV 全屏不缩小，通讯流作为右侧中部半透明双语信息层；中文为主视觉，英文作为弱化辅助核对。
- 支持 `--rounds 1-3` / `1,3,5-7`，符合原有只跑部分回合、只测试部分回合的工作流。
- 反馈包会收集 Comms Feed 的 JSON/HTML/Markdown/YAML 文本产物，但不会打包较大的 overlay 视频。
- 输出解释与 inspect-job 现在会展示 Comms Feed / Comms Overlay 产物。
- 顺手修正 v0.8.8 发布卫生问题：版本号更新、launcher 中 editing 预设不再误写“默认合并重叠”。

## v0.8.8 - 剪映观感优先的 max-2 字幕栈策略

- 新增字幕重叠策略 `stack`：同一时刻最多显示 2 条字幕；当第 3 条字幕开始时，后来者直接替代最早显示的字幕，不把新字幕延后。
- `editing` 与 `compact` 预设默认改为 `stack`，避免 v0.8.7 `merge` 把多人语音合成半屏大段字幕。
- 保留 `merge` 作为高级/兜底策略，但不再作为剪映默认推荐。
- `.bat` 重新导出菜单新增 `stack` 选项，CLI `--overlap-policy stack` 可直接使用；已有 Job 只需重新 export，不需要重跑 Whisper/LLM。
- 新增 max-2 字幕栈回归测试，覆盖“第 3 条替代最早条”“被替代字幕不恢复”“单 cue 不超过 2 个玩家文本”。

## v0.8.6.post2 - K-D-A NaN 崩溃热修复

- 修复真实 Anubis demo 在 `extract_voice` 阶段因 `float('nan')` 转 `int` 崩溃的问题。
- K/D/A 写入 voice manifest 时改用安全整数转换，`NaN` / 非法值按 0 安全降级。
- `players list` 从旧 `player_stats.json` 回填 K-D-A 时同样容忍 `NaN`。
- `_normalize_steamid(float('nan'))` 现在返回 `None`，避免异常 SteamID 值打断流程。
- 新增 NaN 回归测试，覆盖新 Job 合并、旧 Job 回填和 SteamID 归一化边界。

## v0.8.6.post1 - K-D-A 显示热修复

- 修复 `players list` / `.bat` 玩家识别菜单中 K-D-A 显示为 `?-?-?` 的问题。
- 修复 17 位 SteamID64 被 `float` 转换后发生尾数漂移，导致 voice manifest、player_stats、alias 文件无法稳定对齐的问题。
- 新增旧 Job 兼容：当 `artifacts/player_stats.json` 已有 K-D-A、但 `artifacts/voice/manifest.json` 没有统计字段时，`players list` 会按精确 SteamID 或唯一 `name + team_number` 回填显示。
- 新增回归测试覆盖 SteamID 精度与旧 Job K-D-A 回填。
## v0.8.6 - 玩家识别与字幕显示名映射

  * 新增 `cs2pov players list`：查看 Job 中有语音的玩家、Team、K-D-A、语音时长、语音包数和当前字幕显示名。
  * 新增 `cs2pov players alias`：将 demo 临时昵称映射为字幕显示名，例如 `Ebule -> donk`，重新导出即可生效，不需要重跑 Whisper/LLM。
  * 新增 `cs2pov players clear-alias`：清除单个或全部字幕显示名映射。
  * 向导选择 POV 主角后增加字幕显示名设置，适合制作 POV 视频时把 FACEIT/Steam 临时昵称改成职业 ID。
  * 尝试从 `player_death` 事件解析 K-D-A，并写入 `artifacts/player_stats.json` 与 voice manifest，帮助用户确认谁是谁。
  * `.bat` 主菜单新增玩家识别入口。


## v0.8.5 - 中文社区报点校准

- 校准 Mirage 报点：`ninja -> 忍者位`。
- 校准 Mirage B 区 `bench -> 沙发`，不再推荐“长椅”。
- 校准 Mirage `ladder / ladder room -> 黑屋`，不再推荐“梯子房”。
- 校准 Anubis `stairs -> 匪口`，避免直译“楼梯”或误写“警口”。
- 新增术语 warning 回归测试，确保上述自然中文表达不误报，直译/错误译法会进入复核 warning。

## v0.8.4 - Anubis 词典试点

- 新增 `de_anubis` 地图报点试点词典，用于 Anubis POV 推广样片测试。
- `.bat` 词典菜单新增 de_anubis 查看入口。
- `glossary list --map de_anubis` 支持查看 global 通用术语 + Anubis 地图词典。
- 新增 `docs/GLOSSARY_ANUBIS_PILOT.zh.md`。
- README、文档索引和样片制作流程更新为 Mirage / Dust2 / Anubis 三地图试点。


所有重要版本变化记录在这里。当前版本号采用「迭代里程碑」语义，不代表已经发布到 PyPI。

## v0.8.2 - Dust2 词典试点与推广样片流程

- 新增 `de_dust2` 地图词典 pilot，覆盖 A大 / 大坑 / 鹅位 / A小 / 中门 / Xbox / B洞 / B门 / B窗 / 警家 / 匪家等高频点位。
- `glossary list --map de_dust2` 支持查看 global 通用术语 + Dust2 地图词典。
- setup-check、.bat 菜单、README 与词典说明更新为 Mirage / Dust2 双地图试点。
- 新增 `docs/GLOSSARY_DUST2_PILOT.zh.md`，说明 Dust2 词典边界、来源标签和使用原则。
- 新增 `docs/SHOWCASE_SAMPLE_WORKFLOW.zh.md`，用于制作“平台机翻 vs 本工具字幕”的 60~120 秒推广样片。
- 保持策略：词典只注入 prompt 与产生 warning，不做字幕硬替换。

## v0.8.1 - 术语 warning 降噪与 benchmark 隐私修复

- 修复 global `nade` 术语把普通英文代词 `he` 误识别为 HE grenade 的问题。
- 优化通用术语 warning 的可接受中文表达，降低 `boost` / `push` 等自然译法的误报。
- `benchmark-asr` 报告不再写入原始 demo 的本地绝对路径，改为保存脱敏显示名。
- 继续保留 v0.8.0 的模型管理、质量档位和 global CS2 glossary pilot。

## v0.8.0 - 模型管理与通用术语试点

- 新增 `cs2pov models info/list/recommend/set-cache/test`。
- 新增转录质量档位：fast / balanced / quality / medium_cpu / cuda_quality。
- 新增 `cs2pov benchmark-asr`，用于在真实 demo 上比较 tiny/base/small/medium。
- Whisper 支持项目级缓存目录，方便把模型放到 D 盘。
- 新增 global CS2 通用术语词典 pilot，并与 Mirage 地图词典共同注入翻译 prompt。
- `glossary_used.json` 区分 global_terms 和 map_terms。

## v0.7.1 - Feedback 隐私脱敏小修

- 修复 `cs2pov feedback` 中 `progress.log` 仍可能包含 Windows 本地绝对路径的问题。
- 反馈包中的 log/txt 诊断文件现在会保留 job 内相对路径，同时隐藏本地盘符、用户目录和 demo 所在路径。
- 不改 ASR、LLM、字幕策略、词典和 CLI 主流程。

## v0.7.0 - GitHub 仓库落地 / 作品集发布整理

- 重写 `README.zh.md`，新增英文 `README.md`。
- 新增 `CHANGELOG.md`、`ROADMAP.md`、`CONTRIBUTING.md`、`LICENSE`、`.gitignore`。
- 新增发布相关文档：`docs/TESTING_GUIDE.zh.md`、`docs/SECURITY_AND_PRIVACY.zh.md`、`docs/RELEASE_CHECKLIST.zh.md`、`docs/SHOWCASE.zh.md`、`docs/DEVELOPMENT_WORKFLOW.zh.md`。
- 扩展架构文档，明确 Pipeline / Job / Manifest / Artifact / Adapter 边界。
- 更新版本号与 `.bat` 启动文案为 v0.7.0。
- 新增仓库就绪度测试，确保关键文档存在且版本号一致。

## v0.6.x - Mirage 词典试点机制

- 只试点 `de_mirage`，不铺全地图词典。
- 新增结构化英文 / 俄语 / 中文术语对照。
- 翻译阶段注入 glossary prompt。
- 生成 `glossary_used.json` 和 `glossary_warnings.json`。
- 反馈包加入 glossary 诊断，并脱敏本地绝对路径。

## v0.5.x - 字幕格式与剪辑体验

- 新增导出预设：`editing / review / debug / compact`。
- 新增字幕格式：`compact / zh_clean / debug`。
- 默认产品心智改为双语优先。
- `.bat` 菜单解释字幕预设和重叠策略。

## v0.4.x - 发布准备 / 普通用户可用性

- 新增 `setup-check`、`explain-output`。
- 新增安装脚本和 acceptance smoke 脚本。
- 新增 Windows 安装、输出文件、FAQ 文档。
- 修复 Windows 路径分隔符导致输出解释错误的问题。

## v0.3.x - 字幕工程工具化

- 新增 `inspect-job / export / retranslate / resume / feedback`。
- `.bat` 改成菜单式入口。
- 子菜单支持 `0 / q / back / 返回` 回到主菜单。

## v0.2.x - 强引导 CLI 产品化

- `cs2pov-wizard` 改成 8 步向导。
- 支持 POV 玩家选择、Whisper 配置、快速测试、翻译配置。
- 新增反馈包命令。
- 修复字幕拆词和长 cue 挂屏策略。

## v0.1.x - Pipeline 主链路稳定

- 新建 PipelineEngine / Job / Manifest / ArtifactStore 架构。
- 真实 demo 验证：解压、地图识别、语音提取、round 清洗、转录、导出、DeepSeek 翻译。
- 修复 API key 泄露、Windows `.bat` 乱码、PyOgg 依赖、ASR 长 cue 等问题。
