# v0.8.2 Dust2 词典试点说明

v0.8.2 新增 `de_dust2` 地图报点试点词典。

它的目标不是一次性覆盖所有 Dust2 点位，而是先覆盖 CS2 POV 字幕里最常见、最容易被平台机翻误译的点位：A大、小道、中路、中门、Xbox、B洞、B门、B窗、警家、匪家等。

## 使用原则

1. 词典只注入翻译 prompt，并生成 `glossary_used.json` / `glossary_warnings.json`。
2. 词典不会硬替换字幕文本，避免 ASR 错听后被进一步放大。
3. warning 只是人工复核线索，不代表翻译一定错误。
4. Dust2 的很多短词有歧义，例如 `doors`、`car`、`window`、`short`、`long`，需要结合上下文。
5. 中文推荐译法优先服务视频字幕自然度，不追求逐词翻译。

## 第一批词条范围

### A 大 / A 点

- `a long / long` → A大
- `long doors` → A大门
- `pit` → 大坑
- `side pit` → 大坑边
- `blue / blue box` → 蓝箱
- `a car / car` → A车
- `a ramp / ramp` → A斜坡
- `a site` → A包点
- `goose` → 鹅位

### 小道 / 中路

- `a short / short / cat / catwalk` → A小 / 小道
- `short stairs / cat stairs` → 小道楼梯
- `mid / middle` → 中路
- `top mid` → 中远 / 中路上
- `mid doors / double doors` → 中门
- `xbox` → Xbox箱
- `suicide` → 自杀位
- `ct mid` → 警中 / 警家中路

### B 点 / B 洞

- `b tunnels / tunnels` → B洞
- `upper tunnels` → 上洞
- `lower tunnels` → 下洞
- `dark` → 暗位
- `b site` → B包点
- `b doors` → B门
- `b window` → B窗
- `b car` → B车
- `b plat / platform` → B平台
- `back plat / back site` → 后平台
- `fence` → 铁网

### 出生点 / 下包

- `t spawn` → 匪家
- `ct spawn` → 警家
- `default plant / default` → 默认包位

## 来源标签

词条中的 `sources` 使用来源标签，而不是完整 URL。主要用于开发者判断词条可靠度。

- `totalcsgo`：TotalCSGO Dust2 callout 表；
- `dmarket`：DMarket Dust2 callout 指南；
- `daddyskins`：DaddySkins Dust2 callout 分区说明；
- `skinrave`：SkinRave Dust2 callout 资料；
- `cs2util`：CS2Util Dust2 callout 多语言页面；
- `blog_cs2ad`：CS2AD Dust2 callout 指南；
- `profilerr`：Profilerr Dust2 callout 说明；
- `csbumps`：Dust2 高频 callout 文章；
- `yallacompass`：Dust2 lingo/callout 说明。

## 典型对比目标

本词典主要帮助平台机翻容易出错的地方：

```text
trade -> 补枪，而不是“交易”
push mid -> 压中 / 前压中路，而不是“推动中间”
A long / long -> A大，而不是“长的”
short / cat -> A小 / 小道，而不是“短的/猫”
pit -> 大坑，而不是“坑”或无上下文翻译
B tunnels -> B洞，而不是“隧道”
xbox -> Xbox箱，而不是“Xbox 游戏机”
```

## 后续维护方式

Dust2 词典应该通过真实样片和反馈逐步修：

1. 先跑 3~5 回合。
2. 检查 `glossary_warnings.json`。
3. 对照原声和字幕，只修真实出现的问题。
4. 对短词歧义保持保守，不要为了“命中更多”牺牲准确性。
