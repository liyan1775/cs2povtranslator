# v0.1.2 反馈修复报告

本版基于用户重新准备的 `feedback_for_dev(1).zip`，按 v0.1.0 真实运行产物重新分析；v0.1.1 已覆盖的修复继续保留。

## 反馈包中的关键事实

真实环境已经跑通：

- `.dem.zst` 解压成功
- 地图识别为 `de_mirage`
- 9 名玩家语音成功提取
- Opus 解码 0 丢包
- Whisper tiny 转录出 1106 条片段
- 原文/双语占位/中文占位 SRT 成功导出

新发现的主要问题是：`demoparser2` 的 `round_start` 事件不能直接当作最终比赛回合边界，因为真实 FACEIT demo 中会出现暂停、重开或开局控制事件。

## 本版新增修复

### 1. 新增 round_start 清洗逻辑

v0.1.0 直接把 33 个 `round_start` 全部当成 round。反馈包显示其中：

- Round 2 只有约 7.5 秒
- Round 3 只有约 1.8 秒
- 用户预期该 demo 是 16+14，约 30 个正式回合

v0.1.2 改为：

- 先生成原始候选回合；
- 保存到 `artifacts/rounds_raw.json`；
- 默认过滤短于 10 秒的疑似暂停/重开伪回合；
- 对开局 tick 1 附近出现的 restart preamble 做清洗；
- 清洗后重新编号为 1..N，保存到 `artifacts/rounds.json`。

用反馈包里的旧 `rounds.json` 模拟清洗，结果为：

```text
raw rounds:     33
cleaned rounds: 30
first cleaned:  56.359s ~ 119.188s
last cleaned:   2661.469s ~ 2772.635s
```

### 2. 保存原始回合候选

新增：

```text
artifacts/rounds_raw.json
```

这很重要：如果清洗错了，我们还能回看 parser 原始事件，而不是只能猜。

### 3. 新增 `--min-round-duration`

专家命令支持：

```powershell
cs2pov run demo.dem.zst --min-round-duration 10
```

验收脚本支持：

```powershell
python scripts\run_acceptance.py --demo demo.dem.zst --min-round-duration 10
```

默认值为 10 秒。

### 4. 调整验收脚本默认值

v0.1.0 的验收脚本默认 `--max-rounds 1`，容易让用户误以为完整 round mapping 已经验证。

v0.1.2 改为：

```text
--max-rounds 0
```

含义是不限制，完整构建所有有效 round contexts。

如果要省 LLM 成本，需要用户主动传：

```powershell
--max-rounds 1
```

或：

```powershell
--max-rounds 5
```

### 5. 日志进一步明确

`parse_rounds` 阶段现在会说明：

- 已按最短时长清洗；
- 原始候选见 `artifacts/rounds_raw.json`；
- 清洗后的有效回合数见 `artifacts/rounds.json`。

### 6. 单元测试补充

新增测试：

- 开局 restart preamble 会被过滤；
- 短伪回合会被过滤；
- 清洗后 round 会重新编号；
- 正常非 0 秒开头的回合不会被误删；
- warmup round 会被过滤。

当前纯单元测试：

```text
11 passed
```

## 仍然需要真实环境确认的点

由于当前沙盒缺少 `demoparser2 / pyogg / faster-whisper`，我无法完整复跑真实 demo。请在你的本机重点确认：

1. `rounds_raw.json` 是否约 33 条；
2. `rounds.json` 是否约 30 条；
3. `round_contexts.jsonl` 是否不再出现一个巨大的 Round 0；
4. `combined.original.srt` 的字幕是否从正式回合附近开始更合理；
5. `--team 2` 或 `--team 3` 是否能导出对应队伍字幕。
