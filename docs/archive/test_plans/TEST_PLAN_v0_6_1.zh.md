# CS2 POV Translator v0.6.1 测试计划

## 测试目标

v0.6.1 是 v0.6.0 的小修版，重点验证：

1. v0.6.0 的 Mirage 词典功能没有回归。
2. `manifest.json` 不再保存本地绝对路径作为 artifact 路径。
3. `cs2pov feedback` 生成的反馈包不泄露 `D:\...` 这类本地路径。
4. v0.5.1 的双语优先设置仍然保持。

不需要重新大规模比较 ASR/字幕策略。

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov doctor
cs2pov config show
```

预期：

```text
59 passed
地图术语词典: ON（试点: de_mirage）
API key 不显示明文
subtitle_export_preset = editing
subtitle_overlap_policy = shift
```

## 2. 词典命令回归

```powershell
cs2pov glossary list --map de_mirage
cs2pov glossary list --map de_mirage --json
```

预期：

```text
仍然显示 22 条 Mirage 试点词条
包含英文 / 俄语 / 中文 / confidence / note / sources 等字段
```

## 3. 复用已有 Job 生成 feedback 包

可以直接用 v0.6.0 生成过的 Job：

```powershell
cs2pov feedback output_v060_glossary
```

或者指定具体 Job：

```powershell
cs2pov feedback "output_v060_glossary\20260610_161929_de_mirage"
```

预期：

```text
生成 cs2pov_feedback_*.zip
不包含 artifacts/voice/
不包含 artifacts/temp_audio/
不包含原始 demo
manifest.json 中不出现 sk-
manifest.json 中不出现 D:\个人项目\... 这类本地路径
artifacts/demo_info.json 中 input_path 被脱敏
README_FEEDBACK.txt 中 job_dir 被脱敏
```

## 4. 小范围真实翻译 smoke（可选）

如果想确认 v0.6.1 对真实 pipeline 没回归，可以跑：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v061_glossary `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 3
```

重点检查：

```text
artifacts/glossary_used.json 存在
artifacts/glossary_warnings.json 存在
final/team_2.bilingual.srt 存在
manifest.json 的 artifacts 路径是 final/...、artifacts/... 这种相对路径
```

## 5. 本轮反馈包建议包含

如果测试失败，请用新版本命令打包：

```powershell
cs2pov feedback output_v061_glossary
```

并额外附上：

```text
pytest 输出
cs2pov doctor 输出
cs2pov glossary list --map de_mirage --json 输出
```
