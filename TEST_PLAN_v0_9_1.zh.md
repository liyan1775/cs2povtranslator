# CS2 POV Translator v0.9.1 测试计划

## 测试目标

验证 v0.9.1 是否解决真实新 demo 反馈中的问题：

1. 右侧通讯流更窄、更贴右、字体略小、可显示更多条。
2. 不再出现最底部语句卡片溢出外层通讯框的问题。
3. 新消息进入有轻量过渡，不再完全生硬。
4. `.bat` 用户可以通过菜单完成 Comms Overlay 的 build-review 和 render。
5. Comms build-review 能确认只导出 POV 所需的一队 5 人。
6. 新建工程向导默认自动生成 Comms Feed 校对文件，通讯流成为主产物。

## 开发者静态/单元测试

```powershell
pytest -q
python -m compileall -q src tests
```

预期：全部通过。

## 快速回归测试

使用已有 v0.9.0 Job，不重新跑 demo/Whisper/LLM：

```powershell
cs2pov comms build-review output --rounds 1-3 --team 2 --export-scope pov_team
cs2pov comms render output --rounds 1 --formats png
cs2pov comms render output --rounds 1 --formats preview,green
```

预期：

- `review/comms_rounds/round_01.yaml` 等文件存在。
- `final/comms_overlay/round_01_overlay_preview_state.png` 存在。
- `round_01_overlay_preview.mp4` 与 `round_01_overlay_green.mp4` 存在。
- build-review 输出中能看到 `export_scope=pov_team`、`selected_team_number=2`。

## `.bat` 主工作流测试

1. 双击 `Start_CS2_POV_Translator.bat`。
2. 选择 `1. 新建 POV 通讯流工程`，只跑 1-3 回合。
3. 完成后检查是否自动生成：
   - `review/comms_rounds/round_XX.yaml`
   - `final/comms_feed/comms_feed.html`
   - `final/comms_feed/comms_feed.md`

预期：不需要再手动输入 `comms build-review`，新建工程结束时已经得到通讯流校对文件。

## `.bat` Comms Overlay 菜单测试

1. 双击 `Start_CS2_POV_Translator.bat`。
2. 选择主菜单 `13. Comms Overlay 通讯流素材`。
3. 输入 Job 路径，或直接回车使用 `output`。
4. 选择 `1` 生成 YAML，输入 `1-3`。
5. 当菜单显示当前 Job 的队伍选择时，输入 POV 所需队伍编号，例如 `2`。
6. 再次进入菜单 13，选择 `2` 渲染 overlay，选择 `1` 输出 preview,green。

预期：普通用户不需要手敲专家命令也能完成 Comms Overlay 工作流。

## 视觉验收测试

打开 `final/comms_overlay/round_01_overlay_preview.mp4` 或 PNG 快照，检查：

- 通讯流位于右侧中部并贴近最右侧。
- 没有 v0.9.0 的大黑色外层面板，只有 Round 标题和语句卡片。
- 字体比 v0.9.0 略小，但中文仍清楚。
- 同屏能容纳更多消息，默认最多 6 条。
- 最底部语句卡片不溢出。
- 新消息出现时有轻量淡入。

## 剪映测试

1. 将 lim POV 视频导入剪映主轨。
2. 将 `round_01_overlay_green.mp4` 放到对应回合上方轨道。
3. 使用色度抠图移除绿色背景。
4. 观察右侧通讯流是否遮挡关键 HUD、雷达、击杀信息。
5. 可选：测试 `alpha.mov` 透明通道兼容性。

## 失败时请打包

如果失败，请提供：

```powershell
cs2pov feedback output
```

并额外提供：

- `review/comms_rounds/round_XX.yaml`
- `final/comms_overlay/round_XX_overlay_preview_state.png`
- `round_XX_overlay_preview.mp4` 或截图
- 终端报错全文
- 剪映叠加效果截图
- `ffmpeg -version` 输出
