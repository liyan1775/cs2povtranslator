# CS2 POV Translator v0.5.1 发布说明

v0.5.1 是 v0.5.0 的偏好校正版：功能主线已经通过测试，因此本版不改 Whisper / DeepSeek / demo 解析，只把字幕导出的默认心智调整为**双语优先**。

## 背景

v0.5.0 反馈包显示：

- `editing/review/debug/compact` 预设均可正常导出；
- `compact/zh_clean/debug` 新格式可用；
- `.bat` 菜单和 `explain-output` 正常；
- 但用户明确表示个人更偏好双语字幕。

因此 v0.5.1 做的是产品定位校正：默认推荐不再暗示“纯中文是最终首选”，而是把**原文 + 中文对照**作为 POV 视频剪辑的首选形态。

## 主要改动

### 1. 默认导出预设改为 editing

新默认：

```text
subtitle_export_preset = editing
subtitle_overlap_policy = shift
```

含义：默认更偏向剪辑使用场景，生成双语、紧凑双语和中文兜底文件，并轻微错开重叠字幕。

### 2. `.bat` 菜单文案改为双语优先

菜单中的导出说明更新为：

```text
preset editing  推荐：双语 + 紧凑双语 + 中文兜底，尽量减少重叠
format bilingual 双语（最推荐先看）
format compact   紧凑双语（剪辑优先）
format zh        只中文（可选）
zh_clean         极简可选
```

### 3. `explain-output` 推荐语更新

现在解释输出文件时，会把：

```text
final/team_2.bilingual.srt
```

标为首选双语字幕，建议先导入剪映 / Premiere 检查。

### 4. 测试补充

新增测试确认：

- 默认配置为 `editing + shift`；
- editing 预设始终保留 `bilingual_srt`；
- 双语 SRT 仍包含原文和 `[中文]` 翻译行。

## 未改动

本版没有改：

- demo 解析；
- Whisper 转录；
- DeepSeek 翻译；
- subtitle cue 时长策略；
- feedback 包逻辑；
- resume / retranslate / inspect-job。

所以本版不需要大规模重新跑完整 demo，重点测试导出默认配置和菜单说明即可。
