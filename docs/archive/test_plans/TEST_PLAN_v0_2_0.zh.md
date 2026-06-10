# v0.2.0 测试计划

这版重点不是重新穷举 ASR 参数，而是验证 **强引导 CLI 产品体验** 和 **反馈包命令**。v0.1.8 未测的小项也并入这里一起测。

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
28 passed
API key 不显示明文
config show / doctor 中文不乱码
默认模型建议为 deepseek-v4-flash
```

## 1. 测试双击启动

双击：

```text
Start_CS2_POV_Translator.bat
```

预期：

- 能进入 8 步向导
- 中文不乱码
- 找不到 `.venv` 时能给出安装步骤，而不是 `ModuleNotFoundError`

## 2. 测试强引导向导快速流程

建议先用快速测试：

```powershell
cs2pov-wizard --quick
```

按提示输入：

1. demo 文件路径
2. 输出目录默认回车
3. 地图确认 Y
4. 选择一个 POV 玩家
5. 默认导出该玩家所在队伍
6. Whisper 模型先选 tiny
7. ASR 语言 auto
8. 转录模式 round
9. 运行范围快速测试前 3 回合
10. 翻译方式先选 dry-run

预期：

- 向导按 `[1/8]` 到 `[8/8]` 展示
- 玩家表格能显示 Team、玩家名、语音时长、包数
- 最后能生成 `final/*.bilingual.srt`
- 完成时提示 `cs2pov feedback <job_dir>`

## 3. 测试专家命令默认 smoke

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v020_smoke `
  --whisper-model tiny `
  --team 2 `
  --dry-run-translation `
  --max-rounds 3
```

重点看：

```text
manifest.json
artifacts\transcription_coverage.json
final\team_2.bilingual.srt
```

预期：

- manifest 不出现 `sk-`
- coverage 有 before/after 字段
- SRT 不出现 30s+ 超长 cue
- SRT 不出现纯逗号或 `끝,,,,,` 标点幻觉

## 4. 测试反馈包命令

对向导或专家命令生成的 job 运行：

```powershell
cs2pov feedback output_v020_smoke
```

或者传具体 job 目录：

```powershell
cs2pov feedback "output_v020_smoke\20260610_xxxxxx_de_mirage"
```

预期：

- 生成 `cs2pov_feedback_*.zip`
- zip 内包含 manifest/progress/errors/artifacts/final/review/debug 文本产物
- zip 内不包含 `artifacts/voice/*.wav`
- zip 内不包含 `artifacts/temp_audio/*.wav`
- manifest 中 API key 仍然脱敏

## 5. 可选：真实 LLM 小范围测试

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v020_llm `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 1
```

预期：

- 使用 deepseek-v4-flash
- `translated_segments.jsonl` 中中文不再是 dry-run 占位
- SRT 能正常导出

## 6. 如果失败，发这些

优先直接运行：

```powershell
cs2pov feedback <job目录或output目录>
```

然后把生成的 zip 发给我。

如果向导在创建 job 前就失败，手动发：

```text
终端完整输出截图或复制文本
cs2pov doctor > doctor_v020.txt
cs2pov config show > config_show_v020.txt
```
