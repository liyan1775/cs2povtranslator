# v0.1.8 测试计划

## 测试目标

v0.1.8 只验证两个问题：

1. 幻觉过滤是否能清掉 v0.1.7 SRT 中残留的逗号/标点噪声。
2. `doctor.txt` / `config_show.txt` 是否变为 UTF-8，不再在反馈包里乱码。

不需要大规模重测所有 ASR 模式。

---

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
25 passed
cs2pov doctor 能正常显示中文
cs2pov config show 能正常显示中文，API key 不显示明文
```

---

## 1. 检查重定向文件编码

请运行：

```powershell
cs2pov doctor > doctor_v018.txt
cs2pov config show > config_show_v018.txt
```

然后用 VS Code 或记事本打开两个文件。

预期：

```text
doctor_v018.txt 中文正常
config_show_v018.txt 中文正常
不是乱码
API key 仍然隐藏
```

如果你打包反馈，请把这两个 txt 放入反馈包。

---

## 2. 默认 smoke test

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v018_default `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

重点检查：

```text
output_v018_default\...\final\team_2.bilingual.srt
output_v018_default\...\artifacts\transcription_coverage.json
output_v018_default\...\manifest.json
```

预期：

```text
SRT 不再出现纯逗号 cue
SRT 不再出现 “끝,,,,,,,,,,,,” 这类标点尾巴
manifest.json 不出现 sk-
coverage 中出现 filtered_hallucination_segments_after_rebase 字段
long_transcript_segments_gt_30s = 0
```

---

## 3. 对照测试：关闭幻觉过滤

可选，用来确认过滤确实生效：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v018_no_filter `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3 `
  --no-filter-hallucinations
```

预期：

```text
关闭过滤后，SRT 可能重新出现标点噪声。
这不是 bug，只用于对照验证。
```

---

## 反馈包建议包含

```text
doctor_v018.txt
config_show_v018.txt
manifest.json
progress.log
transcription_coverage.json
team_2.bilingual.srt
本地 agent 的测试报告（如果有）
```

这版通过后，可以停止 v0.1.x 小修，进入 v0.2.0 的强引导 CLI。
