# 输出文件说明

每次处理 demo 都会生成一个 Job 目录，例如：

```text
output/20260610_141449_de_mirage/
```

v0.5.1 以后，最常用的文件仍在 `final/`，默认推荐双语字幕；纯中文文件作为可选导出。

## final/

给剪辑软件使用的最终字幕。普通用户最应该看这里。

- `*.compact.srt`：剪辑紧凑版。显示时间更短，重叠更少，适合直接导入剪映 / Premiere。
- `*.bilingual.srt`：原文 + 中文双语字幕，适合校对和半成品剪辑。
- `*.zh.srt`：只中文字幕，保留玩家名，适合最终成片。
- `*.zh_clean.srt`：纯中文、无玩家名前缀，适合极简风格。

推荐命令：

```powershell
cs2pov export output --preset editing
```

## review/

校对用文件。

- `*.original.srt`：只看 Whisper 识别出来的原文。
- `*.zh.srt`：中文校对副本。

推荐命令：

```powershell
cs2pov export output --preset review
```

## debug/

开发者排查用文件。

- `*.debug.srt`：带 round/team/player 信息的调试字幕。
- `*.voice_activity.srt`：只有语音活动时间轴，不是转录文字。

推荐命令：

```powershell
cs2pov export output --preset debug
```

## artifacts/

中间产物。不要随便删除，`resume / retranslate / export` 会用到它们。

- `transcript_segments.jsonl`：转录片段。
- `round_contexts.jsonl`：按回合组织的上下文。
- `translated_segments.jsonl`：翻译片段。
- `transcription_coverage.json`：转录覆盖诊断。

也可以运行：

```powershell
cs2pov explain-output output
```
