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
- v0.9.0-v0.9.1：Comms Overlay MVP，支持按回合通讯流、人工校对 YAML、右侧半透明双语 overlay 素材。
- v0.9.8：默认隐藏不可靠倒计时，只展示 Round + 选手 + 双语通讯流，保留 `show_at_seconds` 作为内部播放时序。

## 后续：v0.9.x / v0.10.x Comms Overlay 完善

当前 v0.9.8 已完成 MVP、入口收敛与时间显示回撤：先生成可编辑通讯流，再按回合渲染剪映 overlay 素材；默认画面不展示不可靠回合倒计时。

下一步优先验证真实创作工作流：

- 用 lim-cspov 授权 POV 视频测试每回合 overlay 在剪映里的叠加体验。
- 本地测试 `alpha.mov` 在剪映里的透明通道兼容性；若不稳定，保留 `green.mp4` 色度抠图兜底。
- 根据真实样片调整右侧面板尺寸、位置、最大消息数、字体大小和双语层级。
- 保持每回合独立渲染，不引入全局 video_alignment.csv。
- 后续若要恢复回合倒计时，必须先验证 demo 事件中可稳定提取 freeze_end / live_start；未验证前不作为默认画面元素。
- 不做 GUI / 所见即所得编辑器，先把 YAML 校对 + overlay 渲染闭环跑稳。

## 后续：词典质量研究

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
4. de_inferno：中文报点差异明显，适合验证 glossary warning。
5. de_nuke / de_ancient / de_vertigo：后续逐步推进。

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

