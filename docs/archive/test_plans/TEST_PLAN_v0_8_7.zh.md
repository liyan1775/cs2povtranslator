# CS2 POV Translator v0.8.7 测试计划

v0.8.7 重点验证两件事：

1. v0.8.6.post1/post2 的 K-D-A 修复没有回归；
2. 多人同时说话时，剪映用的 SRT 不再出现重叠字幕块。

## 1. 自动化测试

```text
pytest -q
```

期望：全部通过。

重点测试：

- SteamID64 精度保持；
- 旧 Job K-D-A 回填；
- `NaN` K/D/A 安全降级；
- `merge` 策略合并重叠字幕；
- 非重叠字幕在 `merge` 策略下仍保持独立 cue。

## 2. 旧 Job 重新导出测试

对已经生成过字幕的 Job 运行：

```text
cs2pov export output --preset editing --overlap-policy merge
```

期望：

- 不重新转录；
- 不重新调用 LLM；
- `final/*.bilingual.srt` 重新生成；
- 重叠时间段被合并为一个 SRT cue。

## 3. 剪映导入测试

步骤：

1. 打开剪映；
2. 导入 POV 视频；
3. 导入 `final/team_*.bilingual.srt`；
4. 找到多人同时说话片段；
5. 检查画面上是否只出现一个字幕块。

期望：

- 不再出现多个字幕块互相盖住；
- 同一时间段内可以看到多名玩家的文字；
- 字幕顺序按说话开始时间排列。

## 4. `.bat` 菜单测试

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
重叠策略：使用预设 或 merge
```

期望：

- 导出成功；
- 菜单文案显示 v0.8.7；
- 输出文件可导入剪映且不再重叠。

## 5. 真实 demo 回归测试

使用之前暴露问题的 Anubis demo：

- `extract_voice` 不再出现 `cannot convert float NaN to integer`；
- `players list` 能显示可用 K-D-A；
- `Ebule -> donk` 这类别名映射仍能在重新导出的 SRT 中生效。
