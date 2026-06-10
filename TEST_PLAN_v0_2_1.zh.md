# v0.2.1 测试计划

## 0. 安装与基础检查

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
31 passed
API key 不显示明文
doctor/config show 中文不乱码
双语字幕格式显示 label
```

## 1. 向导主流程 smoke

```powershell
cs2pov-wizard --quick
```

建议选择：

```text
Whisper: small 或 tiny
ASR: auto
转录模式: round
运行范围: 前 3 或 5 个含语音回合
翻译方式: dry-run 或真实翻译
```

重点观察：

```text
转录阶段是否持续输出“转录中... Round x，玩家 y”
翻译阶段是否持续输出“翻译中... Round x”
完成后是否提示 final/ 字幕路径和 cs2pov feedback 命令
```

## 2. 重点验证：round 模式不再拆碎完整句子

用与 v0.2.0 相同配置运行：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v021_user_run `
  --whisper-model small `
  --team 2 `
  --max-rounds 5
```

重点检查：

```text
final\team_2.bilingual.srt
artifacts\transcription_coverage.json
artifacts\translated_segments.jsonl
progress.log
```

预期：

```text
不再出现 “Ben” + “ch.” 这种拆词
不再把一句话拆成 Hello, we / got a ticket / sir. Speak / ... 多个碎片
coverage 中出现 long_segments_clamped_without_text_split 字段
没有 30s+ 超长 cue
```

## 3. 验证 LLM 失败文案

如果真实翻译中某个 round 失败，SRT 应显示：

```text
[未翻译：LLM 调用失败，请稍后重试该回合]
```

而不是旧的：

```text
[未翻译：未配置或调用 LLM 失败]
```

## 4. 验证双语字幕格式

默认 SRT 应为：

```text
[玩家] original
[中文] translation
```

对照旧格式：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v021_arrow `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3 `
  --bilingual-format arrow
```

预期：

```text
output_v021_arrow 中仍可生成 “→” 旧格式
默认 output_v021_user_run 使用 [中文] 标签格式
```

## 5. 反馈包命令

```powershell
cs2pov feedback output_v021_user_run
```

预期：

```text
生成 cs2pov_feedback_*.zip
不包含 artifacts/voice/*.wav
不包含 artifacts/temp_audio/*.wav
manifest.json 不包含 sk-
```

## 6. 需要发回的文件

如果还有问题，请优先上传 `cs2pov feedback` 生成的 zip。若手动整理，至少包含：

```text
manifest.json
progress.log
errors.log
artifacts\transcription_coverage.json
artifacts\transcript_segments.jsonl
artifacts\translated_segments.jsonl
artifacts\round_contexts.jsonl
final\*.srt
review\*.srt
```
