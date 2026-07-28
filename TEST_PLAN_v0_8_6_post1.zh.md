# CS2 POV Translator v0.8.6.post1 测试计划

## 自动化测试

```bash
pytest -q
```

期望：全部通过。

新增覆盖：

1. 17 位 SteamID64 纯数字字符串不会被 float 转换污染；
2. 旧 Job 的 `voice/manifest.json` 缺少 K-D-A 时，`players list` 能从 `player_stats.json` 回填；
3. 即使旧 `player_stats.json` 的 SteamID 已被 float 污染，也能通过唯一 `Demo昵称 + Team` 恢复显示。

## 本地 demo 验收

### 1. 运行 demo 流程

使用 `.bat` 菜单或 CLI 生成一个 Job。

### 2. 查看玩家识别

```bash
cs2pov players list <Job目录>
```

期望：

- 表格含 Team、Demo昵称、字幕显示名、K-D-A、语音时长、包数；
- 有 K-D-A 的玩家不应显示 `?-?-?`；
- Ebule 行应能显示真实 K-D-A，例如 `45-23-10`。

### 3. 验证别名映射不回归

```bash
cs2pov players alias <Job目录> --name Ebule --as donk
```

期望：

- `artifacts/player_aliases.json` 生成或更新；
- SRT 中 `[Ebule]` 变为 `[donk]`；
- 不需要重跑 Whisper / LLM。

### 4. 验证清除别名

```bash
cs2pov players clear-alias <Job目录> --name Ebule
```

期望：

- SRT 恢复 `[Ebule]`；
- K-D-A 显示不受影响。
