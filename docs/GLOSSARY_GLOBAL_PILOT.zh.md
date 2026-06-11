# Global CS2 通用术语词典试点

v0.8.0 新增 global CS2 术语词典 pilot，用于补足地图报点以外的高频术语，例如：

```text
AWP, flash, smoke, molly, push, peek, hold, rotate, trade, save, eco, force, full buy
```

设计原则：

1. 保守收录，不追求一口气做巨大词典。
2. 词典用于 LLM prompt 约束和 warning 报告，不做硬替换。
3. 俄语别名只收录较高可信表达，宁缺毋滥。
4. 通过真实 POV 字幕反向维护词典，而不是闭门造词。

报告文件：

```text
artifacts/glossary_used.json
artifacts/glossary_warnings.json
```

从 v0.8.0 开始，`glossary_used.json` 会区分：

```text
global_terms
map_terms
matched_global_term_count
matched_map_term_count
```

这有利于后续用 donk 天梯 POV 等真实素材逐步打磨通用术语和 Mirage 报点。
