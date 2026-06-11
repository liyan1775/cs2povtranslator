# ROADMAP

本路线图按「阶段目标」推进，而不是按功能愿望清单推进。

## 已完成

- v0.1.x：主 pipeline 跑通，并通过真实 demo 验证。
- v0.2.x：强引导 CLI，让普通用户能按步骤处理 demo。
- v0.3.x：Job 工具化，支持 inspect/export/retranslate/resume/feedback。
- v0.4.x：发布准备，补充 setup-check、安装脚本、输出解释和反馈包。
- v0.5.x：字幕导出体验，默认双语优先，支持剪辑/校对/debug 预设。
- v0.6.x：Mirage 词典试点机制，验证 glossary prompt 与 warning 报告。
- v0.7.x：GitHub 仓库落地，补充 README、CHANGELOG、路线图、贡献指南和发布检查清单。
- v0.8.x：模型管理、ASR 质量档位、global 通用术语、Dust2/Anubis 词典试点与推广样片流程。

## 后续：v0.9.x 词典质量研究

目标：继续做词典，但必须逐图、逐词、可考证地推进。

原则：

- 不一次性铺全地图。
- 每张地图单独试点。
- 词条包含英文、俄语可能说法、中文推荐译法、别名、置信度和备注。
- 允许社区提交修正，但必须经过复核。

候选顺序：

1. de_mirage：已有试点，继续校正。
2. de_dust2：v0.8.2 新增试点，用于推广样片和 Dust2 POV 字幕验证。
3. de_anubis：v0.8.4 新增试点，用于近期 Anubis POV 样片验证。
3. de_inferno：中文报点差异明显，适合验证 glossary warning。
4. de_nuke / de_ancient / de_inferno / de_vertigo：后续逐步推进。

## 后续：v1.0.0 稳定 CLI 发布版

目标：普通 CS2 玩家可以按 README 和 `.bat` 稳定使用。

进入 v1.0.0 前需要：

- 一条完整真实 demo 验收流程稳定。
- README/FAQ/安装教程足够清楚。
- 反馈包脱敏机制可靠。
- 默认字幕导出结果可用于剪辑。
- 关键命令都有测试覆盖。

## 暂缓

- GUI / Web UI：CLI 体验稳定后再考虑。
- 云端 SaaS：涉及上传大文件、隐私、成本和鉴权，当前不做。
- 战术复盘：需要 kills/bomb/damage/position 等事件地基，不能只靠语音。

