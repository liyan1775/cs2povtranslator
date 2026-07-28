# CS2 POV Translator v0.9.8 Release Notes

## 版本主题

**Comms Overlay 默认无时间显示版。**

v0.9.7 尝试用固定 `freeze_seconds=5.0` 修正回合准备期，但真实测试后确认：不同平台、不同 demo、甚至同一平台不同回合的准备/冻结时间都可能不同；POV 视频剪辑后也不一定保留 demo 内部的精确回合边界。因此 v0.9.8 回撤默认倒计时显示，避免在成片中展示不可靠时间。

## 主要变化

1. Overlay 默认不再显示 `1:55` / `准备 0:03` / `1:32` 等时间文本。
2. 画面默认只显示：`Round + 选手名 + 中文 + 原文`。
3. `show_at_seconds` 继续保留，作为每条消息在该回合 overlay 中出现的内部时序。
4. `round_XX.yaml` 新增 `time_display: none`，人工校对时可明确看到默认策略。
5. `cs2pov comms render` 新增 `--time-display none|elapsed|round-clock`：
   - `none`：默认，正式成片推荐。
   - `elapsed`：实验，显示 `+0:07` 这类相对经过时间。
   - `round-clock`：实验，显示回合倒计时；需要用户自行确认 `--freeze-seconds` 是否匹配素材。
6. README、Comms Review README、静态 HTML/Markdown 均说明默认不展示不可靠倒计时的原因。

## 不变内容

- `.bat` / Anaconda Python 自动发现 / clean-room 入口不变。
- Comms Overlay 仍然按回合单独渲染。
- YAML 人工校对流程不变。
- SRT 导出、ASR、翻译、队伍过滤不变。

## 推荐命令

```powershell
cs2pov comms build-review output --rounds 1-3 --team 2 --export-scope pov_team
cs2pov comms render output --rounds 1-3 --formats preview,green
```

实验显示相对时间：

```powershell
cs2pov comms render output --rounds 1 --formats preview --time-display elapsed
```

实验显示倒计时：

```powershell
cs2pov comms render output --rounds 1 --formats preview --time-display round-clock --freeze-seconds 5
```

## 冻结条件

v0.9.8 只有在以下条件满足时冻结：

1. `.bat` 仍能正常安装并进入 v0.9.8 菜单。
2. 真实 Job 重新 `build-review` 后，`round_XX.yaml` 中存在 `time_display: none` 和 `show_at_seconds`。
3. 默认渲染的 overlay 画面不出现 `1:55`、`准备 0:03`、`+0:07` 等时间文本。
4. 消息仍按 `show_at_seconds` 顺序出现。
5. `--time-display elapsed` 和 `--time-display round-clock` 作为实验选项可用，但不影响默认行为。
