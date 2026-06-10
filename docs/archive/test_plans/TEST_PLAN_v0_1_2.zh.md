# v0.1.2 测试计划

每次拿到新版压缩包后，建议按下面顺序测试。不要一上来就开真实 LLM 翻译，先验证 pipeline、round、队伍导出。

## 0. 重新安装

```powershell
cd D:\个人项目\cs2pov_arch_project
.venv\Scripts\Activate.ps1
pip install -e ".[all]"
pytest -q
cs2pov doctor
```

预期：

```text
pytest 显示 11 passed
cs2pov doctor 中 demoparser2 / zstandard / pyogg / faster_whisper 均为 OK
```

## 1. 测试 bat 入口是否乱码

双击：

```text
Start_CS2_POV_Translator.bat
```

预期：

```text
终端能正常打开
没有乱码导致的命令错误
能进入 cs2pov-wizard 或显示可读提示
```

如果中文文件名脚本仍乱码，先只用英文脚本。

## 2. 完整 round mapping 验收（不调用 LLM）

```powershell
python scripts\run_acceptance.py `
  --demo "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output `
  --whisper-model tiny `
  --skip-translation `
  --max-rounds 0
```

重点检查：

```text
output\*_de_mirage\artifacts\rounds_raw.json      应该保存原始 round_start 候选
output\*_de_mirage\artifacts\rounds.json          应该保存清洗后有效回合
output\*_de_mirage\artifacts\round_contexts.jsonl 应该按有效回合组织
output\*_de_mirage\progress.log                   parse_rounds 日志应提到清洗阈值
```

这份 demo 的参考预期：

```text
rounds_raw.json: 约 33 条
rounds.json:     约 30 条
```

## 3. 队伍导出烟测（不调用真实 LLM）

先测 Team 2：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_team2 `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

再测 Team 3：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_team3 `
  --whisper-model tiny `
  --team 3 `
  --dry-run-translation `
  --max-rounds 3
```

预期：

```text
final\team_2.bilingual.srt 或 final\team_3.bilingual.srt 存在
review\team_2.original.srt 或 review\team_3.original.srt 存在
字幕中只出现对应队伍玩家名
```

## 4. 小范围真实 LLM 翻译

确认 DeepSeek 配置：

```powershell
cs2pov config show
```

如果未配置：

```powershell
cs2pov config set `
  --base-url https://api.deepseek.com `
  --api-key sk-你的key `
  --model deepseek-chat
```

只翻译前 1 个有效回合，避免成本过高：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_llm_smoke `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 1
```

预期：

```text
translated_segments.jsonl 中 translated_text 不再等于 original_text
final\team_2.bilingual.srt 中第二行是中文翻译
没有把 1000 多条 transcript 一次性塞给 LLM
```

## 5. 反馈包请包含这些文件

如果仍有问题，请打包对应 job 目录中的：

```text
manifest.json
progress.log
errors.log
artifacts\demo_info.json
artifacts\rounds_raw.json
artifacts\rounds.json
artifacts\round_contexts.jsonl
artifacts\transcript_segments.jsonl
artifacts\translated_segments.jsonl
final\*.srt
review\*.srt
```

如果问题与语音提取有关，再额外包含：

```text
artifacts\voice\manifest.json
```
