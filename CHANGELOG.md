# Changelog

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
