# CS2 POV Translator v0.8.4 测试计划

## 目标

验证 v0.8.4 的 Anubis `cave -> 黑屋` 词典校准不会破坏 v0.8.3 的 Anubis 词典、模型管理和基础 pipeline。

## 1. 基础测试

```powershell
pip install -e ".[all]"
pytest -q
python -m compileall -q src scripts
cs2pov --help
```

预期：测试全部通过，CLI 可正常显示。

## 2. Anubis 词典检查

```powershell
cs2pov glossary list --map de_anubis --scope map
cs2pov glossary list --map de_anubis --scope map --json
```

重点检查：

```text
anubis_cave:
  source: cave
  zh: Cave/黑屋
  acceptable aliases include: 黑屋 / B黑屋 / 洞穴 / Cave / B洞穴
```

## 3. 真实 Anubis smoke

```powershell
cs2pov config set --transcription-profile quality

cs2pov run "D:\demos\anubis_sample.dem.zst" `
  --output output_v084_anubis `
  --map de_anubis `
  --team 2 `
  --max-rounds 3

cs2pov glossary check output_v084_anubis
cs2pov feedback output_v084_anubis
```

重点观察：

```text
care cave -> 小心黑屋 / 注意黑屋
```

如果仍翻成“小心洞穴”，不算 pipeline 失败，但说明翻译 prompt 还可以继续加强。

## 4. 回归范围

确认以下能力不回退：

```powershell
cs2pov glossary list --map de_mirage
cs2pov glossary list --map de_dust2
cs2pov models recommend
cs2pov models info
```

## 5. 反馈包要求

请打包：

```text
manifest.json
progress.log
glossary_used.json
glossary_warnings.json
final/team_2.bilingual.srt
review/team_2.original.srt
README.md 或测试报告
```

并确认不含 API key、真实本地绝对路径、demo、WAV。
