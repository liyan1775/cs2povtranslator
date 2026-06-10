# CS2 POV Translator v0.5.1 测试计划

v0.5.1 是双语优先偏好校正版。它不改主 pipeline，重点验证默认配置、导出说明和 `.bat` 菜单文案。

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov config show
cs2pov doctor
```

预期：

```text
52 passed
subtitle_export_preset = editing
subtitle_overlap_policy = shift
API key 不显示明文
中文不乱码
```

如果你本机已有旧配置，`config show` 可能仍显示旧值。可以手动迁移：

```powershell
cs2pov config set --subtitle-preset editing --overlap-policy shift
```

## 2. 复用已有 Job 测 editing 预设

```powershell
cs2pov export output --preset editing
```

预期至少生成：

```text
final/team_2.bilingual.srt
final/team_2.compact.srt
final/team_2.zh.srt
```

重点看：

- `bilingual.srt` 包含原文和 `[中文]`；
- `compact.srt` 是紧凑双语；
- `zh.srt` 只是兜底可选，不是默认首推。

## 3. 测单独双语导出

```powershell
cs2pov export output --format bilingual
cs2pov export output --format compact
```

预期：

- `bilingual.srt` 保留完整双语标签；
- `compact.srt` 更适合剪辑导入，但仍然是双语。

## 4. 测 explain-output

```powershell
cs2pov explain-output output
```

预期：

```text
final/team_2.bilingual.srt  ← 首选双语字幕...
final/team_2.compact.srt    ← 紧凑双语字幕...
final/team_2.zh.srt         ← 只中文字幕，可选...
```

## 5. 测 .bat 菜单

双击：

```text
Start_CS2_POV_Translator.bat
```

选择：

```text
5. 重新导出字幕
```

预期菜单说明应该显示：

```text
preset editing  推荐：双语 + 紧凑双语 + 中文兜底
format bilingual 双语（最推荐先看）
format compact   紧凑双语（剪辑优先）
```

并且输入 `0 / q / back / 返回` 能返回主菜单。

## 6. 是否需要重新跑完整 demo？

通常不需要。v0.5.1 不改转录和翻译，只改导出默认与说明。

如需 smoke：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v051_smoke `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 1
```

预期 `manifest.json` 中：

```json
"subtitle_export_preset": "editing",
"subtitle_overlap_policy": "shift"
```
