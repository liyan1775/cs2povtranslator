# v0.6.0 Mirage 词典试点说明

## 目标

v0.6.0 只做 `de_mirage` 一张地图的试点词典，不做全地图铺开。

词典用于：

1. 在按回合翻译时注入 prompt，约束 LLM 使用更稳定的中文报点；
2. 生成 `artifacts/glossary_used.json`，记录本次实际启用的词条；
3. 生成 `artifacts/glossary_warnings.json`，提示疑似未遵守术语的片段，供人工复核。

词典不用于：

- 不做翻译后硬替换；
- 不强制把所有英文/俄语短词都当作报点；
- 不假装覆盖所有 Mirage 点位。

## 资料来源标签

词条来自多方交叉整理，代码中以 `sources` 标签记录来源类别：

- `dmarket`：英文 Mirage callout 说明；
- `skinrave`：英文 CS2 Mirage callout 分区说明；
- `totalcsgo`：英文交互式 Mirage callout 表；
- `cs2util_cn`：中文 Mirage callout 对照；
- `17173_cn`：中文 Mirage 报点教学；
- `5e_cn`：中文 Mirage 报点对照表；
- `cybersport_ru`：俄语 Mirage 位置说明；
- `respawn_ru`：俄语/英语位置说明；
- `steam_ru`：俄语社区 callout 对照；
- `stavka_ru` / `profilerr_ru` / `betteam_ru`：俄语资料补充。

## 保守原则

- 置信度为 `high` 的词条才适合作为强推荐；
- `medium` 词条只作为提示，尤其是 Jungle、Top Mid、Tetris 等中英文/中文社区叫法存在差异的位置；
- 如果 ASR 把普通词误识别成 callout，LLM 可以忽略词典，不应硬套；
- `glossary_warnings.json` 是人工复核线索，不代表翻译一定错误。


## v0.8.5 中文社区叫法校准

根据真实 POV 样片制作前的中文报点反馈，v0.8.5 对 Mirage 的几个容易直译错误的点位做了校准：

```text
ninja -> 忍者位
bench -> 沙发
ladder / ladder room -> 黑屋
```

说明：

- `bench` 指 Mirage B 区包点附近位置，中文 POV 字幕优先写“沙发”，不再推荐“长椅”。
- `ladder / ladder room` 优先写“黑屋”，不推荐直译“梯子房”。
- `ninja` 优先写“忍者位”，避免平台机翻按普通名词处理。

## 下一步

如果 Mirage 试点有效，后续再扩展：

1. 用户自定义词典覆盖；
2. 按地图逐张扩充；
3. 词典校验报告更细化；
4. 根据真实 demo 反馈调整中文首选叫法。
