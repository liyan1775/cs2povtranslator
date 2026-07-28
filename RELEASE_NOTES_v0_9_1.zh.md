# CS2 POV Translator v0.9.1 Release Notes

## 版本主题

**Comms Overlay 成为默认主功能，并完成观感与 .bat 工作流修复。**

v0.9.0 已经跑通了「可编辑 YAML → 每回合 overlay → 剪映叠加」主链路。本版本把 Comms Overlay 正式提升为默认主输出：普通用户通过 `.bat` 新建工程后会自动得到按回合 YAML/HTML/Markdown 通讯流；SRT 保留为可选剪辑资产。同时处理真实新 demo 反馈中的右侧 overlay 观感、底部卡片溢出、队伍过滤和 `.bat` 操作问题。

## 主要变化

1. **默认 overlay 改为右侧贴边浮动消息卡片**
   - 面板宽度从 520px 调整为 460px。
   - 右边距从 48px 调整为 16px，更贴近画面最右侧。
   - 字体略微缩小：中文 24、英文 17、meta 17。
   - 同屏最多消息数从 4 条提高到 6 条。
   - 默认不再绘制 v0.9.0 的大黑色外层面板，只保留独立语句卡片。

2. **修复底部卡片溢出**
   - v0.9.0 是「画完卡片再判断是否超出」，导致最底部语句卡片可能有一点露出大卡片外。
   - v0.9.1 改为「先测量卡片高度，再选择能放下的最新消息」。空间不够时优先保留最新消息，丢弃更旧消息。

3. **新增轻量淡入过渡**
   - 新消息进入时增加短淡入，不再完全硬切。
   - 专家命令可用 `--fade-seconds` 调整；设为 `0` 可关闭。

4. **渲染速度优化**
   - 默认 fps 从 30 调整为 15。通讯流主要是文本卡片，15fps 足够用于轻量淡入，同时能明显降低每回合渲染时间。
   - H.264 preview/green 输出增加 `veryfast` 编码预设。

5. **`.bat` 菜单新增 Comms Overlay 入口**
   - 主菜单新增「13. Comms Overlay 通讯流素材」。
   - 可以在菜单里执行 build-review、render 或两者连续执行。
   - build-review 菜单会显示并允许覆盖 `selected_team_number`，避免本地 agent 或专家命令误跑成非 POV 所需队伍。

6. **导出范围提示增强**
   - `cs2pov comms build-review` 完成后会显示实际 `export_scope / selected_team_number / selected_pov_steamid`，用于确认是否只导出了 POV 所需的一队 5 人。

7. **Comms Overlay 成为默认主流程**
   - `.bat` 主菜单与向导文案从「新建字幕工程」调整为「新建 POV 通讯流工程」。
   - 强引导向导完成转录/翻译/字幕导出后，会自动运行 `comms build-review`，生成 `review/comms_rounds/round_XX.yaml` 与 `final/comms_feed/`。
   - `inspect-job` / `explain-output` 的下一步推荐现在优先指向 Comms Feed 校对与 overlay 渲染，SRT 作为可选资产保留。

## 兼容性

- 不改变 v0.9.0 的 YAML 数据结构。
- 不要求重新跑 Whisper 或 LLM。已有 v0.9.0 Job 可以直接重新运行：

```powershell
cs2pov comms render output --rounds 1-3 --formats preview,green
```

- 如果想回到 v0.9.0 的大外层面板，可使用：

```powershell
cs2pov comms render output --rounds 1 --formats preview --classic-panel
```

## 推荐使用方式

普通用户：双击 `Start_CS2_POV_Translator.bat`，先选择主菜单 1 新建 POV 通讯流工程；完成后会自动生成 YAML 校对文件，再选择主菜单 13 渲染 overlay。

专家命令：

```powershell
cs2pov comms build-review output --rounds 1-3 --team 2 --export-scope pov_team
cs2pov comms render output --rounds 1-3 --formats preview,green
```
