# CHANGELOG

所有重要版本变化记录在这里。当前版本号采用「迭代里程碑」语义，不代表已经发布到 PyPI。

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
