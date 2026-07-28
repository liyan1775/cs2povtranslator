# v0.8.6 - 玩家识别与字幕显示名映射

v0.8.6 是为 POV 视频制作前补上的关键体验修复：用户不应在 SRT 后期手动把 `Ebule` 改成 `donk`，工具应该在字幕导出层正式支持玩家显示名映射。

## 新增功能

### 1. 玩家识别命令

```powershell
cs2pov players list output
```

显示 Job 中有语音的玩家：

- Team
- demo 原始昵称
- 字幕显示名
- K-D-A
- 语音时长
- 语音包数

这可以帮助用户用 scoreboard / 视频标题快速确认职业选手小号或临时昵称，例如 `Ebule = donk`。

### 2. 字幕显示名映射

```powershell
cs2pov players alias output --name Ebule --as donk
cs2pov export output --preset editing
```

重新导出后，字幕会从：

```text
[Ebule] Care cave, care cave.
```

变成：

```text
[donk] Care cave, care cave.
```

不需要重跑 Whisper，也不需要重新调用 LLM。

### 3. 清除别名

```powershell
cs2pov players clear-alias output --name Ebule
cs2pov players clear-alias output --all
```

### 4. K-D-A 辅助识别

工具会尝试从 demo 的 `player_death` 事件解析 K-D-A，并写入：

```text
artifacts/player_stats.json
artifacts/voice/manifest.json
```

如果 demo 或 demoparser2 当前字段不支持解析，会显示 `?-?-?`，不影响语音/字幕主流程。

### 5. .bat 菜单入口

主菜单新增：

```text
11. 玩家识别 players
```

可在菜单里查看玩家、设置别名、清除别名。

### 6. 向导内设置显示名

新建字幕工程时，选择 POV 主角后会询问最终字幕显示名。适合直接把临时昵称设置成职业 ID。

## 文档

新增：

```text
docs/PLAYER_ALIAS_WORKFLOW.zh.md
```

并更新 README、文档索引和样片制作流程文档。

## 验证

本地验证：

```text
90 collected tests passed
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov players --help
python -m cs2pov.cli.launcher --once
```

## 推荐给 Anubis 样片的流程

```powershell
cs2pov run "demo.dem.zst" --output output_anubis_12r --map de_anubis --team 2 --max-rounds 12
cs2pov players list output_anubis_12r
cs2pov players alias output_anubis_12r --name Ebule --as donk
cs2pov export output_anubis_12r --preset editing
```
