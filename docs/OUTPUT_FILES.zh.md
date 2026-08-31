# 输出文件说明

每次处理 demo 都会生成一个 Job 目录，例如：

```text
jobs/20260610_141449_de_mirage/
```

v0.9.0 以后，最常用的文件仍在 `final/`，默认推荐双语字幕；如果要做 POV 通讯增强视频，还会使用 `review/comms_rounds/` 和 `final/comms_overlay/`。

## 工作区素材与 Job 输入的区别

- `library/demos/<asset_id>/`：01E 的持久 Demo 素材；包含 `asset.json` 和首次导入的一个 `source.dem` 或 `source.dem.zst`。新建 Pipeline Job 只引用它，不复制它。
- `cache/decompressed_demos/<asset_id>.dem`：可清理、可重建的解压缓存，不是最终产物。
- `jobs/<job>/input/`：legacy Job 的输入副本；受管 Job 通常为空，Demo 路径由素材库服务在内存中解析。

可用 `cs2pov demos import/list/inspect` 管理和诊断前两项；`run`/向导也会自动
import/reuse。当前没有 delete、独立 repair 命令或旧 Job 自动迁移，不能手工把素材
目录当作 Job 输出目录。

## final/

给剪辑软件使用的最终字幕。普通用户最应该看这里。

- `*.compact.srt`：剪辑紧凑版。显示时间更短，重叠更少，适合直接导入剪映 / Premiere。
- `*.bilingual.srt`：原文 + 中文双语字幕，适合校对和半成品剪辑。
- `*.zh.srt`：只中文字幕，保留玩家名，适合最终成片。
- `*.zh_clean.srt`：纯中文、无玩家名前缀，适合极简风格。
- `comms_feed/comms_feed.html`：按回合组织的双语通讯流静态报告，用于快速检查“谁在什么时候说了什么”。
- `comms_overlay/round_XX_overlay_preview.mp4`：每回合 overlay 排版/错字预览，不建议作为最终叠加素材。
- `comms_overlay/round_XX_overlay_green.mp4`：绿幕背景兜底素材，适合在剪映里尝试色度抠图。
- `comms_overlay/round_XX_overlay_alpha.mov`：透明通道素材，需本地测试剪映兼容性。

推荐命令：

```powershell
cs2pov export --preset editing
```

Comms Overlay 工作流：

```powershell
cs2pov comms build-review --rounds 1-3
# 人工修改 review/comms_rounds/round_XX.yaml
cs2pov comms render --rounds 1-3 --formats preview,green
```

## review/

校对用文件。

- `*.original.srt`：只看 Whisper 识别出来的原文。
- `*.zh.srt`：中文校对副本。
- `comms_rounds/round_XX.yaml`：v0.9.0 的关键中间产物。可人工修改 `show_at`、`speaker`、`zh`、`source`、`enabled`，然后只重渲染这一回合 overlay。

推荐命令：

```powershell
cs2pov export --preset review
```

## debug/

开发者排查用文件。

- `*.debug.srt`：带 round/team/player 信息的调试字幕。
- `*.voice_activity.srt`：只有语音活动时间轴，不是转录文字。

推荐命令：

```powershell
cs2pov export --preset debug
```

## artifacts/

中间产物。不要随便删除，`resume / retranslate / export / comms build-review` 会用到它们。

- `transcript_segments.jsonl`：转录片段。
- `round_contexts.jsonl`：按回合组织的上下文。
- `translated_segments.jsonl`：翻译片段。
- `transcription_coverage.json`：转录覆盖诊断。

也可以运行：

```powershell
cs2pov explain-output
```
