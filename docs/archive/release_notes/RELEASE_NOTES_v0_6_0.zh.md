# CS2 POV Translator v0.6.0 发布说明

## 主题

**Mirage 词典试点版。**

这一版遵循“心急吃不了热豆腐”的原则：不做全地图词典，只做 `de_mirage` 一张地图的可验证试点。

## 新增功能

### 1. Mirage 结构化词典

新增 `de_mirage` 词条，包含：

- 英文 callout；
- 俄语常见说法 / 音译；
- 中文推荐译法；
- 中文别名；
- 置信度；
- 来源标签；
- 备注。

### 2. 翻译阶段注入词典

按回合翻译时，会把 Mirage 词典注入 prompt。

注意：词典只做提示和约束，不硬替换字幕文本。

### 3. 新增词典报告

翻译后会生成：

```text
artifacts/glossary_used.json
artifacts/glossary_warnings.json
```

`glossary_used.json` 记录本次启用和命中的词条。

`glossary_warnings.json` 记录疑似未遵守术语的片段，供人工复核。

### 4. 新增命令

```powershell
cs2pov glossary list --map de_mirage
cs2pov glossary check output
```

### 5. `.bat` 菜单新增词典入口

主菜单新增：

```text
10. Mirage 词典试点 glossary
```

可以查看词典，也可以检查已有 Job 的词典报告。

## 保留 v0.5.1 小修内容

v0.5.1 未单独验收的双语优先调整已合入本版：

- 默认剪辑导出仍以双语为首选；
- `.bat` 导出菜单仍强调 bilingual / compact；
- `explain-output` 仍把 `bilingual.srt` 标为推荐优先检查文件。

## 不做什么

- 不做全地图词典；
- 不做用户自定义词典；
- 不做翻译后硬替换；
- 不做 UI；
- 不做战术复盘。
