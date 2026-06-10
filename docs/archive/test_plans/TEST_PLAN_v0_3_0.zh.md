# v0.3.0 测试计划

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

- `pytest` 显示 `35 passed` 或更多。
- `doctor/config show` 中文不乱码。
- `config show` 不显示明文 API key。

## 1. 测试 `.bat` 菜单

双击：

```text
Start_CS2_POV_Translator.bat
```

预期：

- 进入 v0.3.0 主菜单，而不是直接进入向导。
- 菜单能看到 `inspect/export/retranslate/resume/feedback/doctor`。
- 每个菜单项都有用途说明。

建议先选：

```text
2. 查看已有工程状态
```

直接回车使用默认 `output`。

## 2. 测试 inspect-job

```powershell
cs2pov inspect-job output
cs2pov inspect-job output --json > inspect_v030.json
```

预期：

- 能自动选择最新 Job。
- 能看到阶段状态、转录条数、翻译条数、SRT 文件列表。
- `inspect_v030.json` 中不能出现 `sk-`。

## 3. 测试 export 不重新转录

```powershell
cs2pov export output --format all
cs2pov export output --format zh
cs2pov export output --format bilingual --bilingual-format arrow
cs2pov export output --format original
cs2pov export output --format voice
```

预期：

- 不会调用 Whisper。
- 不会调用 LLM。
- 能生成或刷新：
  - `final\team_2.bilingual.srt`
  - `final\team_2.zh.srt`
  - `review\team_2.original.srt`
  - `debug\team_2.voice_activity.srt`

## 4. 测试 retranslate dry-run

```powershell
cs2pov retranslate output --dry-run
```

预期：

- 不重新转录。
- `artifacts\translated_segments.jsonl` 被刷新。
- `final\team_2.bilingual.srt` 中出现 `[演示翻译]`。

如果要测试真实 LLM：

```powershell
cs2pov retranslate output --model deepseek-v4-flash
```

预期：

- 不重新转录。
- 使用已有 round contexts 重新调用 LLM。

## 5. 测试 resume 只重跑导出

```powershell
cs2pov resume output --from-stage export_subtitles
```

预期：

- 不重新解压 demo。
- 不重新转录。
- 只刷新 SRT 输出。
- 运行后 `cs2pov inspect-job output` 阶段仍为 completed。

## 6. 测试反馈包

```powershell
cs2pov feedback output
```

预期：

- 生成 `cs2pov_feedback_*.zip`。
- 不包含：
  - `artifacts/voice/*.wav`
  - `artifacts/temp_audio/*.wav`
  - 原始 `.dem` / `.dem.zst`
- `manifest.json` 中不出现 `sk-`。

## 7. 如果测试失败，反馈包建议包含

直接运行：

```powershell
cs2pov feedback output
```

并额外说明：

- 你是从 `.bat` 菜单运行，还是从 PowerShell 命令运行。
- 选择了哪个菜单项。
- 最后一屏报错内容。
