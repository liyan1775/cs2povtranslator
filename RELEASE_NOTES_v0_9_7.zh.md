# CS2 POV Translator v0.9.7 Release Notes

## 版本主题

**Comms Overlay 回合准备时间修复版。**

v0.9.6 已经解决 Windows 双击 `.bat`、Anaconda Python 自动发现和真实 demo 入口问题。本版本不再改启动器主路径，而是修复真实 POV 测试中发现的 Comms Overlay 时间轴问题：CS2 每回合开始后存在一段准备/冻结时间，1:55 的正式回合倒计时不是从 `round_start` 立刻开始。

## 修复内容

1. Comms Feed 新增 `freeze_seconds` 字段，默认 5 秒。
2. `round_XX.yaml` 的 `duration_seconds` 改为优先使用真实回合窗口长度，不再强行截断为 115 秒。
3. 准备期内的消息不再误标为 `1:53`、`1:52`，而是显示为 `准备 0:03` 这类标签。
4. 准备期结束后才从 `1:55` 开始倒计时。
5. 每条消息新增 `phase` 字段：`freeze` / `live` / `post_round`，方便人工检查。
6. `comms build-review` 新增 `--freeze-seconds` 参数，可覆盖默认准备时间。
7. `comms render` 新增 `--freeze-seconds` 兜底参数，用于渲染缺少 `freeze_seconds` 的旧 YAML。
8. `.bat`、Python 自动发现、Comms Overlay UI 参数不变。

## 典型效果

v0.9.6 旧行为：

```yaml
show_at: '1:53'
show_at_seconds: 1.697
```

v0.9.7 新行为：

```yaml
show_at: 准备 0:03
show_at_seconds: 1.697
phase: freeze
freeze_seconds: 5.0
```

准备时间结束后的消息会按真实回合倒计时显示，例如：

```yaml
show_at: '1:52'
show_at_seconds: 7.937
phase: live
```

## 使用建议

已有 v0.9.6 Job 不需要重新跑 demo、ASR 或翻译。升级到 v0.9.7 后，重新生成 Comms Review 即可：

```powershell
cs2pov comms build-review output --rounds 1-3 --team 2 --export-scope pov_team
cs2pov comms render output --rounds 1-3 --formats preview,green
```

如果某个 demo 的准备时间不是 5 秒，可以手动覆盖：

```powershell
cs2pov comms build-review output --rounds 1-3 --freeze-seconds 10
```

## 未改动范围

- 不改 `.bat` 自动安装启动逻辑。
- 不改 demo 解析、语音提取、ASR、LLM 翻译。
- 不改队伍过滤逻辑。
- 不改 overlay 默认位置、字体、面板宽度、淡入动画。

## 验证

- `pytest` 全部通过。
- `python -m compileall -q src tests scripts` 通过。
- 使用 v0.9.6 真实 demo 反馈包中的 Job 重新生成 Round 1：首条消息已从 `1:53` 修正为 `准备 0:03`，回合时长从 `115` 修正为真实窗口 `120.219` 秒。
