# CS2 POV Translator v0.9.7 测试计划

## 测试目标

验证 v0.9.7 修复 Comms Overlay 的回合准备时间问题：每回合开始后先显示准备/冻结时间，准备结束后才从 1:55 开始正式倒计时。

## 测试前提

v0.9.6 已经验证 `.bat` 可用，本轮不需要重复完整安装排障。仍建议 clean-room 解压 v0.9.7，并确认启动菜单显示 v0.9.7。

## 必测 1：入口回归

1. 解压到全新目录：`cs2pov_arch_project_v0_9_7`。
2. 双击 `START_HERE_DOUBLE_CLICK.bat`。
3. 确认启动自检通过，菜单显示 v0.9.7。

预期：不出现 v0.8.x / v0.9.6 旧菜单，不出现 Python not found，不出现 `.bat` 乱码。

## 必测 2：用已有真实 Job 重新生成 Comms Review

不需要重新跑 ASR/翻译，直接对 v0.9.6 生成过的 output 运行：

```powershell
cs2pov comms build-review output --rounds 1-3 --team 2 --export-scope pov_team
```

检查：

```text
review/comms_rounds/round_01.yaml
review/comms_rounds/round_02.yaml
review/comms_rounds/round_03.yaml
```

预期：

1. 每个 YAML 顶部有 `freeze_seconds: 5.0`。
2. `duration_seconds` 不再固定为 115；应接近该回合真实窗口长度。
3. 回合开头 5 秒内的语音显示为 `准备 0:xx`。
4. 准备时间后的语音才显示为 `1:55`、`1:52` 等正式回合时间。
5. 消息里有 `phase: freeze` 或 `phase: live`。

## 必测 3：渲染 1 个回合 overlay

```powershell
cs2pov comms render output --rounds 1 --formats png,preview,green
```

预期：

1. `final/comms_overlay/round_01_overlay_preview_state.png` 生成。
2. `round_01_overlay_preview.mp4` 生成。
3. `round_01_overlay_green.mp4` 生成。
4. 视频开头 header 显示准备时间，准备结束后再显示 1:55 附近倒计时。

## 可选测试：覆盖准备时间

```powershell
cs2pov comms build-review output --rounds 1 --freeze-seconds 10
```

预期：

- YAML 中 `freeze_seconds: 10.0`。
- 10 秒内消息进入 `phase: freeze`。
- 10 秒后才进入 live clock。

## 如果失败，请打包

请提供：

1. `feedback` 包。
2. `review/comms_rounds/round_01.yaml`。
3. `final/comms_feed/comms_feed.json`。
4. `artifacts/rounds.json`。
5. `artifacts/translated_segments.jsonl` 前 20 行。
6. 如果是渲染观感问题，附 `round_01_overlay_preview.mp4` 或截图。

## 冻结标准

v0.9.7 只有在以下条件满足时冻结：

1. `.bat` 入口仍然可用。
2. `pytest` 全通过。
3. 真实 Job 重新 build-review 后有 `freeze_seconds`。
4. 回合开头语音不再被误标为 1:5x，而是显示准备时间。
5. 准备期结束后倒计时从 1:55 开始。
