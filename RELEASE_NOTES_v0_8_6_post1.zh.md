# CS2 POV Translator v0.8.6.post1 发布说明

这是 v0.8.6 的热修复版本，专门修复玩家识别页面 / `.bat` demo 测试菜单里 **K-D-A 显示为 `?-?-?`** 的问题。

## 修复内容

### 1. 修复 K-D-A 数据源不同步

v0.8.6 已经能把 K-D-A 写入：

```text
artifacts/player_stats.json
```

但 `players list` 主要读取：

```text
artifacts/voice/manifest.json
```

部分真实 demo 中，voice manifest 没有同步写入 `kills/deaths/assists`，所以列表显示成 `?-?-?`。

v0.8.6.post1 做了两层修复：

- 新 Job：`extract_voice` 阶段会把 K-D-A 回填到 voice manifest；
- 旧 Job：即使 voice manifest 缺字段，只要 `player_stats.json` 里有数据，`players list` 也会自动回填显示。

### 2. 修复 SteamID64 精度污染

反馈包暴露出更深层的问题：17 位 SteamID64 曾经过 `float` 转换，导致末尾数字漂移。例如：

```text
76561198386265483 -> 76561198386265488
```

这会让 `voice manifest`、`player_stats.json`、`player_aliases.json` 对不齐。

v0.8.6.post1 已修复 SteamID 归一化逻辑：纯数字字符串不再走 `float(...)`，避免尾数污染。

### 3. 旧数据兼容

对于已经生成的 v0.8.6 Job：

- 不需要重跑 Whisper；
- 不需要重跑 LLM；
- 直接运行 `cs2pov players list <job>`，如果 `player_stats.json` 存在，就会尽量恢复 K-D-A 显示；
- 匹配优先级：精确 SteamID > 唯一 `Demo昵称 + Team`。

## 建议验证

```bash
pytest -q
cs2pov players list <你的Job目录>
```

重点检查：

- K-D-A 不再全部显示 `?-?-?`；
- Ebule / donk 所在行应显示类似 `45-23-10`；
- `players alias Ebule --as donk` 仍然能秒级重新导出字幕；
- 字幕显示名映射不受影响。
