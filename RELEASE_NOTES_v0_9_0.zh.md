# CS2 POV Translator v0.9.0 Release Notes

## 版本主题

**Comms Overlay MVP：从“生成字幕”扩展到“生成 POV 通讯增强层”。**

v0.9.0 不再只围绕 SRT 字幕优化，而是新增一条面向真实视频制作的工作流：把 demo 中的队内语音整理成按回合组织、可人工校对、可在剪映中叠加的右侧半透明双语通讯流素材。

## 新增功能

### 1. `cs2pov comms build-review`

从已有 Job 的 `artifacts/translated_segments.jsonl` 生成 Comms Feed 产物：

```powershell
cs2pov comms build-review output --rounds 1-3
```

输出：

```text
final/comms_feed/comms_feed.json
final/comms_feed/comms_feed.md
final/comms_feed/comms_feed.html
review/comms_rounds/round_01.yaml
review/comms_rounds/round_02.yaml
...
review/comms_rounds/README_COMMS_REVIEW.md
```

### 2. 每回合可编辑 YAML 中间产物

`review/comms_rounds/round_XX.yaml` 是本版本的核心中间产物。人工可以修改：

```text
show_at   回合内显示时间，例如 1:32
speaker   显示选手名
zh        中文主视觉文本
source    英文/原文辅助核对文本
enabled   false 表示不渲染该条
note      人工备注
```

翻译错了、玩家名错了、某句话不想显示时，不需要重跑 Whisper / LLM，只改 YAML，再重新渲染对应回合。

### 3. `cs2pov comms render`

从人工校对后的 YAML 渲染每回合 overlay 素材：

```powershell
cs2pov comms render output --rounds 1-3 --formats preview,green
```

支持格式：

```text
preview  带深色背景的预览 MP4，用于检查排版和错字
green    绿幕背景 MP4，剪映可尝试色度抠图
alpha    透明通道 MOV，需本地测试剪映兼容性
png      单帧排版截图，用于无 ffmpeg 环境下快速检查
```

默认展示形态：

```text
1920×1080 画布
POV 视频不缩小、不裁切
通讯面板位于右侧中部
中文为主视觉，英文弱化显示
同屏最多显示最近 4 条消息
```

### 4. 按回合独立渲染

本版本不做全局 `video_alignment.csv`，也不自动合成整场视频。每回合单独输出素材，例如：

```text
final/comms_overlay/round_01_overlay_preview.mp4
final/comms_overlay/round_01_overlay_green.mp4
final/comms_overlay/round_01_overlay_alpha.mov
```

这样符合真实剪辑工作流：用户在剪映中把 `round_01` overlay 拖到第 1 回合 POV 视频片段上方即可。某回合翻译修正后，也只需要重新渲染该回合。

## 顺手修复

- 版本号更新为 `0.9.0`。
- `.bat` / launcher 文案更新为 v0.9.0。
- 修正 launcher 中 `editing` 预设仍写“默认合并重叠”的误导文案，改为默认 `stack`。
- 反馈包会包含 Comms Feed 的 JSON/HTML/Markdown/YAML 文本产物，但不会打包体积较大的 overlay 视频。
- `inspect-job` 与 `explain-output` 会展示 Comms Feed / Comms Overlay 文件。
- README、CHANGELOG、ROADMAP、输出文件说明更新。

## 依赖说明

基础 demo → SRT 链路仍使用原有依赖。

Comms Overlay 渲染需要：

```text
Pillow     绘制中文/英文通讯面板
PyYAML     读取/写入人工可编辑 YAML
ffmpeg     把 PNG 状态帧编码成 MP4/MOV
```

`pip install -e ".[all]"` 已包含 Pillow / PyYAML；ffmpeg 是外部程序，需要本机 PATH 能找到 `ffmpeg`。

如果没有 ffmpeg，可以先使用：

```powershell
cs2pov comms render output --rounds 1 --formats png
```

检查单帧排版。

## 建议剪映工作流

```text
1. 跑 demo pipeline，生成翻译结果。
2. 运行 cs2pov comms build-review output --rounds 1-3。
3. 打开 review/comms_rounds/round_XX.yaml，人工修正翻译/玩家名/显示时间。
4. 运行 cs2pov comms render output --rounds 1-3 --formats preview,green。
5. 在剪映中导入 lim 的 POV 视频。
6. 把 round_XX_overlay_green.mp4 放到对应回合视频上方轨道。
7. 用色度抠图去掉绿色背景；如果 alpha.mov 兼容，则可改用 alpha.mov。
8. 最后加片头、说明、音量调整并导出。
```

## 不做的事情

v0.9.0 明确不做：

- 不做 GUI。
- 不做所见即所得编辑器。
- 不自动识别 lim 视频的回合边界。
- 不做整场视频自动合成。
- 不引入 `video_alignment.csv`。
- 不把 Comms Overlay 直接塞入原 SRT 导出阶段。

## 验收重点

本版本重点不是 ASR 或翻译质量，而是验证新的创作工作流是否成立：

```text
翻译结果 → 可编辑 YAML → 单回合 overlay → 剪映叠加 → 成片预览
```
