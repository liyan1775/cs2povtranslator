# v0.8.0 发布说明：模型管理与通用术语试点

v0.8.0 的目标是解决发布后第一批真实用户会遇到的两个问题：

1. Whisper 模型应该怎么选、放在哪里、到底值不值得下载。
2. 地图报点之外，push / trade / AWP / flash 等 CS2 通用术语需要更稳定的中文表达。

本版本不扩全地图词典，不默认 CUDA，不自动删除模型。

## 新增功能

### 1. Whisper 模型管理

新增命令：

```powershell
cs2pov models info
cs2pov models list
cs2pov models recommend
cs2pov models set-cache "D:\AIModels\huggingface"
cs2pov models test --model small --local-only
```

`.bat` 主菜单新增：

```text
11. Whisper 模型管理 models
```

用于查看缓存目录、已下载模型、模型近似大小、质量档位和模型可加载性。

### 2. 转录质量档位

新增配置：

```text
fast          tiny / cpu / int8
balanced      base / cpu / int8
quality       small / cpu / int8
medium_cpu    medium / cpu / int8
cuda_quality  small / cuda / float16
```

向导中会用“快速预览 / 平衡质量 / 高质量 CPU / 实验高质量 CPU / CUDA 高质量”的方式解释，不要求普通用户理解底层参数。

### 3. ASR benchmark

新增：

```powershell
cs2pov benchmark-asr "D:\demos\match.dem.zst" `
  --output output_asr_benchmark `
  --team 2 `
  --max-rounds 3 `
  --models base,small,medium
```

它会生成：

```text
output_asr_benchmark/asr_benchmark.json
```

建议用于比较 base / small / medium 在真实 demo 上的耗时和字幕质量。

### 4. Global CS2 通用术语词典 pilot

v0.8.0 新增小规模通用术语词典，覆盖：

```text
AWP, flash, smoke, molly, nade, kit
push, peek, hold, rotate, trade, save, drop, swing, clear
fake, retake, default, split, rush, contact, lurk, entry, crossfire
boost, stack, eco, force, full buy, half buy, bonus
```

词典仍然只用于：

```text
prompt 约束
术语使用报告
术语 warning
```

不会硬替换字幕文本。

`glossary_used.json` 现在区分：

```text
global_terms
map_terms
matched_global_term_count
matched_map_term_count
```

## 兼容性说明

- 现有 Job 仍可 inspect/export/retranslate/resume。
- 旧的 Mirage 词典机制继续保留。
- `manifest.json` 中的 API key 和本地模型缓存路径仍会脱敏。
- 默认仍是本地 CLI，不是 GUI。

## 推荐测试

1. `pytest -q`
2. `cs2pov models recommend`
3. `cs2pov models list`
4. `cs2pov models set-cache "D:\AIModels\huggingface_test"`
5. `cs2pov glossary list --map de_mirage --scope global`
6. `cs2pov benchmark-asr <demo> --models base,small --max-rounds 3`
