# v0.8.3 Anubis 词典试点说明

v0.8.3 新增 `de_anubis` 地图报点试点词典；v0.8.4/v0.8.5 根据真实中文报点反馈校准 Cave/黑屋 与 Stairs/匪口。

这次增加 Anubis 的直接原因是：推广样片候选素材可能来自近期 Anubis POV。为了让“平台机翻 vs CS2 POV Translator”的对比更有说服力，工具需要先理解 Anubis 的核心报点。

## 目标

Anubis 词典不是完整地图百科，也不是硬替换表。它的目标是先覆盖 POV 字幕中最容易出现、也最容易被平台机翻误译的核心区域：

```text
A Main / A Site / A Connector / Temple / Boat / Drop
Canal / Water / Bridge / Stairs/匪口 / Arches
Middle / Top Mid
B Long / Gate / B Site / Pillar / E Box / Cave/黑屋 / Street
T Spawn / CT Spawn / Alley / Ruins
```

## 翻译原则

Anubis 中文报点没有 Mirage、Dust2 那么稳定，所以 v0.8.3 采用更保守的策略：

```text
1. 很稳定的通用区域直接用中文，例如 中路、警家、匪家、A包点、B包点。
2. 容易有社区差异的点位保留英文 + 中文解释，例如 A Main/A大、Canal/水道、Bridge/桥。
3. 不把词典作为硬替换，只注入 LLM prompt，并生成 glossary_used / glossary_warnings 报告。
4. 如果 ASR 把普通单词误识别成 callout，warning 只作为复核线索，不代表翻译一定错。
```

## 第一批高频词条

### 中路 / 水道

```text
Top Mid       -> 中路上 / Top Mid
Middle / Mid  -> 中路
Bridge        -> Bridge/桥
Canal / Water -> Canal/水道
Stairs        -> 匪口
Arches        -> Arches/拱门
```

### A 区

```text
A Main        -> A Main/A大
A Site        -> A包点
A Connector   -> A Connector/A连接
Plateau       -> Plateau/平台
Heaven        -> Heaven/高台
Temple        -> Temple/神庙
Boat          -> Boat/船位
Drop          -> Drop/下跳
```

### B 区

```text
B Long / B Main -> B Long/B大
Gate            -> Gate/B门
Ivy             -> Ivy/藤蔓位
B Site          -> B包点
Pillar          -> Pillar/柱子
Default         -> 默认包位
E Box           -> E Box/E箱
Sniper          -> Sniper/狙位
Cave            -> Cave/黑屋
Street          -> Street/街道
B Connector     -> B Connector/B连接
```

### 出生点 / T 侧路径

```text
T Spawn -> 匪家
CT Spawn -> 警家
Alley -> Alley/小巷
Ruins -> Ruins/废墟
```


## v0.8.5 中文社区叫法校准

根据用户对 Anubis 中文报点的反馈，v0.8.5 将：

```text
stairs / water stairs / canal stairs -> 匪口
```

说明：Anubis 这里的 `Stairs` 在本工具字幕中优先写“匪口”，不使用“警口”，也不推荐直译成“楼梯”。

## 特别注意

Anubis 有几个词非常容易产生歧义：

```text
water    普通英语也可能只是“水”；在 Anubis 才倾向指 Canal/水道。
connector 需要尽量区分 A Connector / B Connector。
drop     既可能是地图下跳，也可能是“给枪 / 掉枪”。
sniper   既可能是点位，也可能指 AWP/狙击手。
heaven   不同资料和玩家口径可能指不同高点。
```

因此，本词典只做 prompt 约束和 warning，不会自动改字幕文本。

## 来源标签

词条来源综合参考公开 Anubis callout 资料，并使用 source tag 记录在代码中：

```text
totalcsgo     TotalCSGO Anubis callout 表
skinport      Skinport Anubis callout 说明
cs2pulse      CS2Pulse Anubis callout 说明
dmarket       DMarket Anubis callout 指南
profilerr     Profilerr Anubis callout 说明
cs2ad         CS2AD Anubis callout 指南
daddyskins    DaddySkins Anubis callout 说明
tradeit       TradeIt Anubis callout 指南
reddit_community  社区讨论中对 connector / long 等叫法差异的提醒
```

## 后续维护建议

Anubis 词典应该跟真实样片一起迭代：

```text
1. 用 Anubis POV 跑前 3 回合。
2. 查看 final/team_*.bilingual.srt。
3. 查看 artifacts/glossary_used.json 和 artifacts/glossary_warnings.json。
4. 只根据真实错误补词或放宽 acceptable_zh。
5. 不为了“看起来完整”盲目扩展几十个低置信度词条。
```
