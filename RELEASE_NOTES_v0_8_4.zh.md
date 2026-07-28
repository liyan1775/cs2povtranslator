# CS2 POV Translator v0.8.4 发布说明

## 版本定位

v0.8.4 是 v0.8.x 的 Anubis 词典小修版，来自真实 Anubis POV smoke 测试后的中文社区用语校准。

本版不增加大功能，主要修正 Anubis `cave` 的中文首选译法。

## 修改内容

- 将 Anubis `cave` 首选中文从 `Cave/洞穴` 调整为 `Cave/黑屋`。
- 保留 `洞穴` 作为可接受别名，避免旧字幕或保守译法触发误报。
- 更新 Anubis 词典文档、测试计划和相关版本号。
- 新增/更新测试，确保 `care cave` 更倾向于提示 LLM 翻成“黑屋”，同时 warning 校验仍接受“洞穴”。

## 推荐测试重点

- `cs2pov glossary list --map de_anubis --scope map`
- 检查 `anubis_cave` 的 `zh` 是否为 `Cave/黑屋`
- 用真实 Anubis demo 跑前 3 回合，观察 `care cave` 是否更容易翻成“小心黑屋”
- `cs2pov glossary check <job>` 不应因为“洞穴/黑屋”产生无意义 warning
