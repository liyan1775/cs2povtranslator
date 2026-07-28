# v0.8.3 发布说明：Anubis 词典试点

v0.8.3 是 v0.8.x 词典阶段的小版本，主要用于支持近期 Anubis POV 推广样片测试。

## 新增

- 新增 `de_anubis` 地图报点试点词典。
- `.bat` 词典菜单新增「查看 de_anubis 词典」。
- `glossary list --map de_anubis` 支持查看 global 通用术语 + Anubis 地图词典。
- 新增 `docs/GLOSSARY_ANUBIS_PILOT.zh.md`。
- README / 文档索引 / 样片制作流程更新为 Mirage / Dust2 / Anubis 三地图试点。

## Anubis 词典覆盖

第一批覆盖高频点位：

```text
A Main / A Site / A Connector / Plateau / Heaven / Temple / Boat / Drop
Top Mid / Middle / Bridge / Canal / Water / Stairs / Arches
B Long / B Main / Gate / Ivy / B Site / Pillar / Default / E Box / Sniper / Cave / Street / B Connector
T Spawn / CT Spawn / Alley / Ruins
```

## 设计原则

Anubis 中文报点还不如 Mirage / Dust2 稳定，因此 v0.8.3 保守处理：

```text
1. 很多点位保留英文 + 中文，例如 Canal/水道、Bridge/桥、A Main/A大。
2. 词典只注入 LLM prompt，并生成 glossary_used / glossary_warnings。
3. 不做硬替换，避免 ASR 误识别被强行改错。
```

## 已验证

开发侧已验证：

```text
pytest -q
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov glossary list --map de_anubis --scope map
python -m cs2pov glossary list --map de_anubis --scope map --json
python -m cs2pov.cli.launcher --once
```

真实 Anubis demo 效果需要在用户本机用实际 demo 验证。
