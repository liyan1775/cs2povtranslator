# CS2 POV Translator v0.8.8 测试计划

v0.8.8 重点验证字幕观感策略：默认不再 `merge`，而是 `stack`，即同一时刻最多 2 条字幕，第三条替代最早条。

## 1. 自动化测试

```text
pytest -q
```

期望：全部通过。

重点测试：

- `editing` / `compact` 预设默认使用 `stack`；
- `stack` 同屏最多 2 个玩家文本；
- 同一玩家更新不会占用两条显示槽；
- 极短过渡片段会吸收到相邻字幕，避免 0.x 秒闪烁；
- 第 3 条 cue 开始时替代最早显示的 cue；
- 被替代 cue 不延后、不恢复；
- `merge` 作为高级策略仍然可用；
- K-D-A / NaN / SteamID64 修复不回归。

## 2. 旧 Job 重新导出测试

对已经生成过字幕的 Job 运行：

```text
cs2pov export output --preset editing --overlap-policy stack
```

期望：

- 不重新转录；
- 不重新调用 LLM；
- `final/*.bilingual.srt` 重新生成；
- 同一时间窗口最多保留 2 个玩家文本。

## 3. 三人同时说话场景测试

构造或寻找如下片段：

```text
A: 1.0 - 5.0
B: 2.0 - 6.0
C: 3.0 - 4.0
```

期望 SRT 逻辑：

```text
1.0 - 2.0: A
2.0 - 3.0: A + B
3.0 - 4.0: B + C
4.0 - 6.0: B
```

不允许出现：

```text
A + B + C
```

也不允许把 C 延后到 A/B 之后。

## 4. 剪映导入观感测试

步骤：

1. 打开剪映；
2. 导入 POV 视频；
3. 只导入一个 `final/team_*.bilingual.srt`；
4. 找到多人同时说话片段；
5. 检查字幕是否最多约 4 行、不会半屏遮挡。

期望：

- 大部分时间只有 1 条字幕；
- 多人同时说话时最多 2 条上下显示；
- 不出现 v0.8.7 那种多人合并成半屏字幕；
- 不出现第 3 条字幕被延后很多秒的情况。

## 5. `.bat` 菜单测试

运行：

```text
Start_CS2_POV_Translator.bat
```

进入：

```text
5. 重新导出字幕 export
```

选择：

```text
preset editing
重叠策略：使用预设 或 stack
```

期望：

- 菜单文案显示 v0.8.8；
- 导出成功；
- `stack` 选项可选；
- `merge` 仍作为高级选项保留但不默认推荐。

## 6. 真实 demo 回归测试

使用之前暴露问题的 Anubis demo：

- `extract_voice` 不再出现 `cannot convert float NaN to integer`；
- `players list` 能显示可用 K-D-A；
- `Ebule -> donk` 这类别名映射仍能在重新导出的 SRT 中生效；
- 使用 `stack` 导出的 SRT 在剪映中观感优于 v0.8.7 `merge`。
