# v0.8.6 测试计划

v0.8.6 重点测试玩家识别、K-D-A 辅助确认和字幕显示名映射。

## 1. 基础回归

```powershell
pip install -e ".[all]"
pytest -q
cs2pov --help
cs2pov players --help
```

预期：

```text
players 出现在主命令列表中
players 包含 list / alias / clear-alias
测试全部通过
```

## 2. .bat 菜单检查

双击：

```text
Start_CS2_POV_Translator.bat
```

检查：

```text
显示 v0.8.6
主菜单包含 11. 玩家识别 players
菜单 12 仍是 Whisper 模型管理
```

## 3. 用真实 Job 查看玩家

对已有 Job：

```powershell
cs2pov players list output_anubis_12r
```

检查是否显示：

```text
Team
Demo昵称
字幕显示名
K-D-A
语音时长
包数
```

如果 demo 中 Ebule 是 donk，应该能通过 K-D-A 或视频标题辅助确认。

## 4. 设置 Ebule -> donk

```powershell
cs2pov players alias output_anubis_12r --name Ebule --as donk
```

预期：

```text
玩家列表里 Ebule 的字幕显示名变成 donk
artifacts/player_aliases.json 生成
artifacts/voice/manifest.json 中该玩家 display_name = donk
```

## 5. 重新导出字幕

```powershell
cs2pov export output_anubis_12r --preset editing
```

检查：

```text
final/team_2.bilingual.srt
final/team_2.compact.srt
final/team_2.zh.srt
```

预期字幕显示：

```text
[donk] ...
```

而不是：

```text
[Ebule] ...
```

## 6. 不应重跑昂贵步骤

设置 alias 和 export 不应重新：

```text
解码 demo
跑 Whisper
调用 LLM
```

只应重新导出 SRT。

## 7. 清除别名

```powershell
cs2pov players clear-alias output_anubis_12r --name Ebule
cs2pov export output_anubis_12r --preset editing
```

预期字幕恢复为：

```text
[Ebule]
```

## 8. 反馈包检查

```powershell
cs2pov feedback output_anubis_12r
```

反馈包中应包含：

```text
artifacts/player_stats.json
artifacts/player_aliases.json
```

不应包含：

```text
原始 demo
WAV
API key
本地绝对路径
```
