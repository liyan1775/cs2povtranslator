# v0.2.2 测试计划

本版重点不是重新验证所有主链路，而是确认 v0.2.1 通过的基础上，字幕挂屏时间更适合剪辑。

## 0. 安装和基础检查

```powershell
cd D:\个人项目\cs2pov_arch_project
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
pytest -q
cs2pov doctor
cs2pov config show
```

预期：

```text
32 passed
API key 不显示明文
默认模型为 deepseek-v4-flash
最长字幕重贴阈值显示为 10.0s
```

## 1. 跑 v0.2.1 同款真实配置

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v022_user_run `
  --whisper-model small `
  --team 2 `
  --max-rounds 5
```

重点看：

```text
final\team_2.bilingual.srt
artifacts\transcription_coverage.json
progress.log
manifest.json
```

预期：

```text
1. SRT 不出现 Ben/ch. 拆词回归
2. SRT 仍为 [中文] label 格式
3. 最长 cue 应小于或等于 10s
4. 不应大量出现精确 15.0s 的挂屏字幕
5. manifest.json 不出现 sk-
6. progress.log 仍有转录/翻译进度
```

## 2. 对照 v0.2.1 行为

如果你想验证是否确实是阈值导致，可以显式传回旧阈值：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v022_legacy_15s `
  --whisper-model small `
  --team 2 `
  --max-rounds 5 `
  --max-subtitle-segment-seconds 15
```

预期：

```text
legacy_15s 可能更接近 v0.2.1；默认 v0.2.2 应更少长时间挂屏。
```

## 3. 生成反馈包

```powershell
cs2pov feedback output_v022_user_run
```

请上传生成的 zip。优先包含：

```text
manifest.json
progress.log
transcription_coverage.json
final/team_2.bilingual.srt
review/team_2.original.srt
```

不要手动加入 voice 或 temp_audio。
