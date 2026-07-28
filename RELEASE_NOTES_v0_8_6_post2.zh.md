# CS2 POV Translator v0.8.6.post2 发布说明

这是 v0.8.6 的第二个热修复版本，基于本地 agent 对 v0.8.6.post1 的真实 Anubis demo 验收反馈。

## 修复内容

### 1. 修复真实 demo 在 extract_voice 阶段崩溃

v0.8.6.post1 已修复 K-D-A 显示为 `?-?-?` 的主因，但真实 Anubis demo 暴露出新的数据兼容问题：

```text
[ERROR] [extract_voice] 失败：cannot convert float NaN to integer
```

根因是 demoparser2 在某些真实 demo 的 `kills/deaths/assists` 字段中可能返回 `float('nan')`。旧代码使用：

```python
int(stat.get(field) or 0)
```

但 `NaN` 在 Python 中是 truthy，`or 0` 不会生效，最终触发 `int(float('nan'))` 异常。

v0.8.6.post2 已将 K-D-A 写入和回填逻辑改为安全整数转换：

- `float('nan')` / 非有限浮点值会被视作缺失值；
- K/D/A 字段存在但不可转换时按 `0` 处理；
- 不再因为单个玩家的异常统计值打断整个 demo 管线。

### 2. 补强 SteamID / K-D-A 边界处理

额外补强：

- `_normalize_steamid(float('nan'))` 现在返回 `None`，不会崩溃；
- `players list` 从旧 `player_stats.json` 回填 K-D-A 时同样容忍 `NaN`；
- 如果 voice manifest 已经含有 `NaN`，显示层也会安全展示为 `0`，而不是崩溃。

## 建议验证

```bash
pytest -q
```

重点重新运行本地 `.bat` demo 流程：

1. 真实 Anubis demo 能通过 `extract_voice`；
2. `players list` 不再因为 `NaN` 崩溃；
3. 有统计数据的玩家继续显示 K-D-A；
4. 别名映射 `Ebule -> donk` 与字幕重新导出不回归。
