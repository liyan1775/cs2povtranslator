# v0.8.1 发布说明：术语 warning 降噪与 benchmark 隐私修复

v0.8.1 是 v0.8.0 的小修版本，不新增大功能，主要修复本地验收反馈中发现的两个问题。

## 修复内容

### 1. 修复 `global_nade` 误报

v0.8.0 的 global 术语词典中，`nade` 词条包含英文别名 `he`，本意是识别 HE grenade。

但在真实字幕里，`he` 更多时候是普通英文代词，例如：

```text
I kill if he push mid.
Could he push Palace?
Nah, I think he dropped down.
```

这会导致 `glossary_warnings.json` 误报 `global_nade`。

v0.8.1 已将 `he` 调整为更明确的：

```text
he grenade
he nade
```

从而避免普通代词误命中。

### 2. 降低 `boost` / `push` 的自然译法误报

根据反馈包中的真实翻译样本，以下译法是合理自然的：

```text
gimme boost up mid please -> 请架我上中路
he push mid -> 他压中路
```

v0.8.1 将这些自然表达纳入 acceptable aliases，减少无意义 warning。

### 3. `benchmark-asr` 报告不再记录原始 demo 绝对路径

v0.8.0 的 `asr_benchmark.json` 中会写入：

```text
D:\agent_workspace\cs2demos\xxx.dem.zst
```

虽然这不是 feedback 包内部泄漏，但用户很可能会把 benchmark 报告发给开发者，因此 v0.8.1 改为只记录 demo 文件名：

```text
xxx.dem.zst
```

## 保持不变

v0.8.1 继续保留 v0.8.0 的功能：

```text
Whisper 模型管理
转录质量档位
ASR benchmark
global CS2 通用术语词典 pilot
Mirage 地图词典试点
```

## 验证结果

开发环境验证：

```text
73 passed
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov models recommend
```

同时用反馈包中的 warning 样本做了回归验证，确认这些句子不再产生错误的 `global_nade` warning。
