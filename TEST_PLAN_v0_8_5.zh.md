# v0.8.5 测试计划

v0.8.5 是词典小修版，不需要重新完整回归所有地图，但建议在做 Anubis 12 回合样片前做一次快速检查。

## 1. 基础测试

```powershell
pip install -e "[all]"
pytest -q
python -m cs2pov --help
```

预期：

```text
测试全部通过
版本号显示 0.8.5
```

## 2. 词典列表检查

```powershell
cs2pov glossary list --map de_mirage --scope map
cs2pov glossary list --map de_anubis --scope map
```

重点确认：

```text
mirage_bench -> 沙发
mirage_ladder_room -> 黑屋
mirage_ninja -> 忍者位
anubis_stairs -> 匪口
anubis_cave -> Cave/黑屋
```

## 3. Anubis 12 回合样片 smoke

```powershell
cs2pov config set --transcription-profile quality

cs2pov run "你的anubis demo.dem.zst" `
  --output output_v085_anubis_12r `
  --map de_anubis `
  --team 2 `
  --max-rounds 12
```

完成后检查：

```powershell
cs2pov glossary check output_v085_anubis_12r
cs2pov export output_v085_anubis_12r --preset editing
cs2pov feedback output_v085_anubis_12r
```

重点看：

```text
final/team_*.bilingual.srt
review/team_*.original.srt
artifacts/glossary_used.json
artifacts/glossary_warnings.json
```

## 4. 字幕人工抽查重点

对比样片应优先挑这些能证明工具价值的片段：

```text
trade -> 补枪，不是交易
push -> 前压 / 压，不是推动
cave -> 黑屋，不是洞穴
stairs -> 匪口，不是楼梯 / 警口
water / canal -> 水道
```

## 5. 反馈包要求

如果要发回反馈，请包含：

```text
feedback zip
final/team_*.bilingual.srt
review/team_*.original.srt
artifacts/glossary_used.json
artifacts/glossary_warnings.json
```

不要包含：

```text
原始 demo
WAV
API key
完整视频文件
```
