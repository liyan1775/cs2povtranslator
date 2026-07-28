# CS2 POV Translator v0.9.8 测试计划

## 测试目标

验证 v0.9.8 回撤默认倒计时显示：Comms Overlay 默认只显示 Round、选手、中文和原文；不再展示不可靠的回合倒计时。内部时序 `show_at_seconds` 仍然保留，用于控制消息出现顺序。

## 测试前置

沿用 v0.9.6 已验证的启动流程，但仍建议 clean-room 解压：

```text
cs2pov_arch_project_v0_9_8/
```

先确认双击入口正常：

1. 双击 `START_HERE_DOUBLE_CLICK.bat`。
2. 启动自检显示版本 `0.9.8`。
3. 进入 6 项核心菜单。

## 测试 1：用已有 output 重新生成 Comms Review

不需要重新跑 demo、ASR、翻译。使用 v0.9.6 / v0.9.7 已经生成过的真实 Job：

```powershell
cs2pov comms build-review output --rounds 1-3 --team 2 --export-scope pov_team
```

预期：

- `review/comms_rounds/round_01.yaml` 存在。
- YAML 顶部有：

```yaml
time_display: none
```

- 每条消息仍有：

```yaml
show_at_seconds: 7.937
```

- `show_at` 可能仍存在，但 README 会说明它不是默认画面元素。

## 测试 2：默认渲染不显示时间

运行：

```powershell
cs2pov comms render output --rounds 1 --formats png,preview,green
```

检查：

- 打开 `final/comms_overlay/round_01_overlay_preview_state.png`。
- 打开 `final/comms_overlay/round_01_overlay_preview.mp4`。

预期画面：

```text
Round 1

选手名
中文
English
```

不应出现：

```text
1:55
1:32
准备 0:03
+0:07
```

## 测试 3：内部时序仍然生效

播放 `round_01_overlay_preview.mp4`。

预期：

- 消息不是一开始全部出现。
- 消息仍按照 `show_at_seconds` 在对应秒数淡入。
- 旧消息会被新消息挤掉，右侧不溢出。

## 测试 4：实验相对时间显示

运行：

```powershell
cs2pov comms render output --rounds 1 --formats png --time-display elapsed
```

预期：

- 单帧或视频可显示 `+0:07` 这类相对时间。
- 这只是实验/调试选项，不是默认成片行为。

## 测试 5：实验倒计时显示

运行：

```powershell
cs2pov comms render output --rounds 1 --formats png --time-display round-clock --freeze-seconds 5
```

预期：

- 可显示 `1:55` / `1:32` / `准备 0:03` 等旧逻辑时间。
- 测试报告必须标注：该模式不作为默认推荐，因为准备时间不稳定。

## 反馈包要求

如果失败，请提供：

```text
1. feedback zip
2. review/comms_rounds/round_01.yaml
3. final/comms_overlay/round_01_overlay_preview_state.png
4. final/comms_overlay/round_01_overlay_preview.mp4
5. 运行命令全文
6. 如果是 .bat 问题，附启动输出前 120 行
```

## 通过标准

v0.9.8 通过的核心标准是：

```text
默认 overlay 不显示任何不可靠时间，但消息出现顺序仍然正确。
```
