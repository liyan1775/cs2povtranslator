# CS2 POV Translator v0.6.0 测试计划

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov doctor
cs2pov config show
```

预期：

```text
57 passed
API key 不显示明文
地图术语词典显示 ON，试点地图 de_mirage
```

## 2. 词典命令

```powershell
cs2pov glossary list --map de_mirage
cs2pov glossary list --map de_mirage --json
```

预期：

```text
能看到 Mirage 词条
包含 connector / jungle / bench / market / palace / ramp 等核心点位
每个词条有英文、俄语、中文、confidence
```

## 3. `.bat` 词典菜单

双击：

```text
Start_CS2_POV_Translator.bat
```

选择：

```text
10. Mirage 词典试点 glossary
```

测试：

```text
1. 查看 de_mirage 词典
2. 检查已有 Job 的词典使用报告
0 / q / back / 返回 回主菜单
```

预期：菜单解释足够清楚，不需要记专家命令。

## 4. 复用已有 Mirage Job 重翻译

如果已有 v0.5.x / v0.4.x 的 Mirage Job：

```powershell
cs2pov retranslate output --dry-run
cs2pov glossary check output
```

预期生成：

```text
artifacts/glossary_used.json
artifacts/glossary_warnings.json
```

`glossary_used.json` 应显示：

```text
map_name = de_mirage
supported = true
enabled = true
term_count > 0
```

## 5. 小范围真实翻译 smoke

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v060_glossary `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 3
```

然后检查：

```powershell
cs2pov glossary check output_v060_glossary
cs2pov feedback output_v060_glossary
```

重点看：

```text
manifest.json 不出现 sk-
glossary_used.json 存在
glossary_warnings.json 存在
feedback 包包含 glossary_used/warnings
字幕仍以双语为首选
```

## 6. v0.5.1 合并测试项

本版也包含 v0.5.1 未单独验收的小修：

```powershell
cs2pov export output --preset editing
cs2pov export output --format bilingual
cs2pov export output --format compact
cs2pov explain-output output
```

预期：

```text
bilingual.srt 仍是首选双语字幕
compact.srt 仍是紧凑双语
zh / zh_clean 是可选纯中文导出
.bat 导出菜单仍然双语优先
```
