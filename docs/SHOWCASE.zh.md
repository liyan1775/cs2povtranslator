# 作品集展示说明

这个项目适合作品集展示的重点不是“调用了 Whisper 和 LLM”，而是围绕真实 CS2 POV 视频字幕生产，做出了一套可运行、可恢复、可反馈的本地工程流程。

## 可展示亮点

1. **真实 demo 驱动**：不是只处理玩具输入，而是围绕 `.dem/.dem.zst` 真实文件设计。
2. **Pipeline 架构**：阶段清晰，产物可审计，可从失败阶段恢复。
3. **强引导 CLI**：不是纯专家命令，普通用户可通过 `.bat` 菜单使用。
4. **Job 工程化**：支持 inspect/export/retranslate/resume/feedback。
5. **字幕导出体验**：双语优先，支持 editing/review/debug/compact 预设。
6. **安全反馈包**：排除原始 demo、WAV、API key、本地绝对路径。
7. **领域词典试点**：Mirage/Dust2/Anubis 词典不硬替换，而是 prompt 约束 + warning 报告。
8. **版本化闭环开发**：每个版本都有主题、测试计划和反馈核查。

## 演示建议

录制一个 2-3 分钟 GIF/视频：

1. 双击 `Start_CS2_POV_Translator.bat`。
2. 选择 setup-check。
3. 进入新建字幕工程。
4. 选择 demo、POV 玩家、tiny、前 3 回合、dry-run。
5. 生成 `final/team_2.bilingual.srt`。
6. 用 `explain-output` 显示哪个文件该导入剪辑软件。
7. 用 `feedback` 打包反馈包。

## README 展示建议

README 顶部应突出：

- 本地优先。
- CS2 POV 双语字幕。
- 强引导 CLI。
- Job/Manifest/Pipeline。
- 真实 demo 验收。
- 反馈包脱敏。
