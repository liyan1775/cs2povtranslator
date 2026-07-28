# v0.8.3 测试计划：Anubis 词典试点

## 1. 基础回归

```powershell
pip install -e ".[all]"
pytest -q
python -m compileall -q src scripts
cs2pov --help
cs2pov setup-check
cs2pov doctor
```

预期：无测试失败，CLI 可正常启动。

## 2. 词典命令测试

```powershell
cs2pov glossary list --map de_anubis
cs2pov glossary list --map de_anubis --scope map
cs2pov glossary list --map de_anubis --scope global
cs2pov glossary list --map de_anubis --scope map --json
```

重点检查：

```text
1. de_anubis 有地图词典。
2. global 通用术语仍然存在。
3. 输出中能看到 Canal/水道、Bridge/桥、A Main/A大、B Long/B大、Temple/神庙、Cave/黑屋。
4. JSON 输出可解析。
```

## 3. .bat 菜单测试

双击：

```text
Start_CS2_POV_Translator.bat
```

检查：

```text
1. Banner 显示 v0.8.3。
2. 主菜单 10 仍是词典试点。
3. 词典子菜单包含 de_mirage / de_dust2 / de_anubis。
4. 输入 3 能查看 de_anubis 词典。
5. 0 / q / back / 返回 仍可返回主菜单。
```

## 4. Anubis 真实 demo smoke

如果 Anubis demo 已下载，建议先跑前 3 回合：

```powershell
cs2pov config set --transcription-profile quality

cs2pov run "D:\demos\anubis_sample.dem.zst" `
  --output output_v083_anubis `
  --map de_anubis `
  --team 2 `
  --max-rounds 3
```

完成后检查：

```powershell
cs2pov inspect-job output_v083_anubis
cs2pov glossary check output_v083_anubis
cs2pov export output_v083_anubis --preset editing
cs2pov feedback output_v083_anubis
```

重点看这些词是否发挥作用：

```text
Canal / Water -> Canal/水道 / 水道 / 水下
Bridge -> Bridge/桥 / 桥
A Main -> A Main/A大 / A大
A Connector -> A连接
Temple -> Temple/神庙 / 神庙
B Long / B Main -> B Long/B大 / B大
Cave -> Cave/黑屋 / 洞穴
Pillar -> Pillar/柱子 / 柱子
```

## 5. 对比样片准备

若要制作 LIM/其他 POV UP 主的短样片，建议只截取 60~120 秒，挑 3~5 个明显例子：

```text
平台机翻：water -> 水
本工具：Canal/水道

平台机翻：bridge -> 桥梁
本工具：Bridge/桥

平台机翻：temple -> 寺庙
本工具：Temple/神庙

平台机翻：trade -> 交易
本工具：补枪
```

公开样片建议短而克制，不要完整搬运他人视频。

## 6. 反馈包要求

请上传：

```text
feedback zip
final/team_*.bilingual.srt
review/team_*.original.srt
artifacts/glossary_used.json
artifacts/glossary_warnings.json
```

不要上传：

```text
原始 demo
WAV
API key
完整视频素材
```
