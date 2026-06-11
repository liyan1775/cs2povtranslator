# CS2 POV Translator v0.8.8 发布说明

v0.8.8 重点修正 v0.8.7 的字幕产品方向：v0.8.7 的 `merge` 能避免重叠，但会把多人同时说话合成半屏大段字幕，实际 POV 观感不好。v0.8.8 改为默认使用 **max-2 字幕栈策略 `stack`**。

## 为什么需要这个版本

真实剪辑反馈表明：

1. 正常导入单个 SRT 时，剪映大部分字幕效果已经很好；
2. v0.8.7 的 `merge` 过度修复，会把多人语音全部塞进一个 cue；
3. POV 视频更需要“短、清楚、不挡画面”，不是绝对展示所有同时语音。

因此 v0.8.8 的原则是：

```text
同一时刻最多 2 条字幕。
第 3 条字幕开始时，不延后，而是后来者替代最早显示的字幕。
```

## 关键变化

### 1. 新增 `stack` 字幕重叠策略

`stack` 的行为：

- 同屏最多显示 2 个说话 cue；
- 双语字幕下最多约 4 行，不再出现半屏大段；
- 第 3 个说话 cue 开始时，直接替代最早显示的 cue；
- 被替代的旧 cue 不延后，也不会在后来重新出现；
- 同一玩家出现新的重叠 ASR 片段时，会更新该玩家自己的显示槽，不会让同一个人占用两条字幕；
- 极短的过渡片段会吸收到相邻字幕里，减少剪映里 0.x 秒闪烁；
- 源转录、翻译 JSONL 不变，只改变最终 SRT 导出。

示意：

```text
A: 1.0s - 5.0s
B: 2.0s - 6.0s
C: 3.0s - 4.0s
```

导出效果：

```text
1.0s - 2.0s: A
2.0s - 3.0s: A + B
3.0s - 4.0s: B + C   # C 进来后替代 A
4.0s - 6.0s: B       # A 不恢复
```

### 2. `editing` / `compact` 默认改为 `stack`

推荐重新导出：

```text
cs2pov export output --preset editing
```

等价于使用默认 `stack` 策略。也可以显式指定：

```text
cs2pov export output --preset editing --overlap-policy stack
```

已有 Job 不需要重跑 Whisper，也不需要重跑 LLM。

### 3. `merge` 保留但不再默认推荐

`merge` 仍然可用：

```text
cs2pov export output --preset editing --overlap-policy merge
```

但它只适合兜底排查或特殊剪辑风格，不再作为默认剪映方案。

### 4. 继续包含 v0.8.7 的 K-D-A 修复

v0.8.8 仍包含：

- SteamID64 精度污染修复；
- 旧 Job K-D-A 回填；
- `NaN` K/D/A 安全降级；
- `Ebule -> donk` 这类别名映射重新导出生效。

## 推荐操作

对已经做出 `.srt` 的 Job，直接重新导出：

```text
cs2pov export output --preset editing --overlap-policy stack
```

然后优先使用：

```text
final/team_*.bilingual.srt
```

如果觉得双语仍然偏高，可以尝试：

```text
final/team_*.compact.srt
final/team_*.zh.srt
```
