# CS2 POV Translator v0.5.0 发布说明

v0.5.0：字幕格式与剪辑体验版。

本版本基于 v0.4.1 稳定基线，不改 demo 解析、Whisper 转录和 LLM 翻译主链路，重点增强已有 Job 的字幕导出能力。

## 新增能力

### 1. SubtitlePolicy 字幕策略层

新增导出时策略：

- `allow`：保留真实重叠，适合校对；
- `shift`：轻微错开重叠字幕，适合剪辑；
- `compact`：尽量压紧，适合字幕太密时。

这些策略只影响导出的 SRT，不修改 `transcript_segments.jsonl` 或 `translated_segments.jsonl`。

### 2. 导出预设

新增：

```powershell
cs2pov export output --preset editing
cs2pov export output --preset review
cs2pov export output --preset debug
cs2pov export output --preset compact
```

含义：

- `editing`：剪辑安全预设，生成 compact/zh/bilingual；
- `review`：校对预设，生成 bilingual/original/debug；
- `debug`：排查预设，生成 debug/voice/original；
- `compact`：极简紧凑预设，只生成 compact。

### 3. 新增字幕格式

新增：

```powershell
cs2pov export output --format compact
cs2pov export output --format zh_clean
cs2pov export output --format debug
```

- `compact`：紧凑双语字幕；
- `zh_clean`：纯中文、无玩家名前缀；
- `debug`：带 round/team/player 的诊断字幕。

### 4. `.bat` 菜单增强

菜单中的“重新导出字幕”现在会解释：

- 哪个预设适合剪辑；
- 哪个预设适合校对；
- 哪个预设适合反馈问题；
- 如何选择重叠策略。

### 5. explain-output 更新

`cs2pov explain-output` 会解释：

- `final/*.compact.srt`：剪辑紧凑版；
- `final/*.bilingual.srt`：双语校对/成片；
- `final/*.zh.srt`：中文字幕；
- `final/*.zh_clean.srt`：极简纯中文；
- `debug/*.debug.srt`：诊断字幕。

## 已验证

开发环境中已通过：

```text
50 passed
python -m py_compile src scripts
cs2pov --help
cs2pov export --help
cs2pov.cli.launcher --once
```

真实 demo 与 Windows `.bat` 仍需要本地测试。
