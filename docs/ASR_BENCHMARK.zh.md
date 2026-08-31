# ASR 模型对比实验

v0.8.0 新增 `benchmark-asr`，用于在同一个真实 demo 的前 N 个含语音回合上比较多个 Whisper 模型。

示例：

```powershell
cs2pov workspace init "D:\cs2pov-workspace"
cs2pov benchmark-asr "D:\demos\match.dem.zst" `
  --team 2 `
  --max-rounds 3 `
  --models base,small,medium
```

输出：

```text
jobs/asr_benchmark_<timestamp>.json
```

每个模型都是当前工作区 `jobs/` 下的顶层 Job。显式 `--output` 仅用于临时
旧版外部输出兼容分支，会显示警告；模型缓存和临时音频仍跟随当前工作区。

请不要只看耗时，也要打开各个 benchmark Job 的 `final/*.srt` 对比字幕质量、术语识别、幻觉过滤和时间轴。

推荐流程：

1. 先用 `base,small` 对比。
2. 如果 small 已经明显更好且耗时可接受，将 `quality` 档作为日常剪辑配置。
3. 再用 `medium` 对比前 3 回合，判断是否值得下载和等待。
