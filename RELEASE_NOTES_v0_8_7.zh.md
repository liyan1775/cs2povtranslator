# CS2 POV Translator v0.8.7 发布说明

v0.8.7 将 v0.8.6.post1 / post2 的 K-D-A 热修复整理为正式小版本，并新增一个对 POV 成片非常关键的导出修复：**剪映友好的无重叠 SRT**。

## 为什么需要这个版本

v0.8.6 已经解决了“Ebule 这类 demo 临时昵称如何映射成 donk”等玩家识别问题，但真实制作 POV 时又暴露出两个问题：

1. 真实 Anubis demo 中，K/D/A 统计可能出现 `NaN`，导致 `extract_voice` 阶段崩溃；
2. 多个人同时说话时，SRT 中存在时间重叠，导入剪映后可能显示为多个字幕块互相盖住。

v0.8.7 同时解决这两类问题。

## 关键变化

### 1. 新增 `merge` 字幕重叠策略

旧策略：

- `allow`：保留真实重叠，适合校对，但剪映可能重叠显示；
- `shift`：把后面的字幕往后挪，减少重叠，但会改变时间感；
- `compact`：尽量压缩/错开，适合密集字幕，但仍是多条 cue。

新策略：

- `merge`：把同时发生的多条字幕合并成同一个 SRT cue。

示意：

```text
1
00:00:01,000 --> 00:00:04,000
[donk] one cave
[中文] 山洞一个
[zont1x] flash out
[中文] 给闪出去
```

这样导入剪映时只会生成一个字幕块，不再多个字幕块互相覆盖。

### 2. `editing` 预设默认适配剪映

v0.8.7 起：

```text
cs2pov export output --preset editing
```

默认会使用 `merge` 策略。已有 Job 不需要重跑 Whisper，也不需要重跑 LLM，直接重新导出即可。

也可以手动指定：

```text
cs2pov export output --preset editing --overlap-policy merge
```

`.bat` 菜单的“重新导出字幕 export”中也新增了 merge 选项。

### 3. K-D-A 热修复正式并入 v0.8.7

包含以下修复：

- 17 位 SteamID64 不再被 float 转换污染；
- 旧 Job 可从 `artifacts/player_stats.json` 回填 K-D-A；
- `NaN` K/D/A 不再导致 `extract_voice` 崩溃；
- `players list` 面对旧 manifest / 异常 stats 时安全降级。

## 推荐操作

如果已经有 `.srt`，但导入剪映后多人同时说话会重叠：

```text
cs2pov export output --preset editing --overlap-policy merge
```

然后优先使用 `final/team_*.bilingual.srt` 或 `final/team_*.compact.srt` 重新导入剪映。

## 注意

`merge` 只改变最终 SRT 导出，不修改原始转录、翻译 JSONL 或 voice manifest。用户可以随时切回 `review` / `allow` 来检查真实时间线。
