# CS2 POV Translator v0.8.6.post2 测试计划

## 自动化测试

```bash
pytest -q
```

期望：全部通过。

新增覆盖：

1. `_normalize_steamid(float('nan'))` 不崩溃，并返回 `None`；
2. `extract_voice` 阶段将 `player_stats` 合并进 voice manifest 时，`kills/deaths/assists` 中的 `NaN` 会被安全处理为 `0`；
3. `players list` 从旧 `player_stats.json` 回填 K-D-A 时，同样容忍 `NaN`。

## 本地 demo 验收

### 1. 运行真实 Anubis demo

使用 `.bat` 菜单或 CLI 跑完整 demo 流程。

重点观察：

```text
extract_voice
```

阶段不应再出现：

```text
cannot convert float NaN to integer
```

### 2. 查看玩家识别

```bash
cs2pov players list <Job目录>
```

期望：

- 命令不崩溃；
- 有 K-D-A 的玩家不应全部显示 `?-?-?`；
- 个别 parser 返回 NaN 的字段可以显示为 `0`，这是安全降级；
- Ebule / donk 相关行仍可用 K-D-A、队伍、语音时长辅助识别。

### 3. 验证别名映射

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
