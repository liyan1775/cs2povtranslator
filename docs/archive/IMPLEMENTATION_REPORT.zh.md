# CS2 POV Translator Next 实现报告

## 这次交付的内容

本次没有在旧项目上继续打补丁，而是在 `cs2pov_arch_project/` 中从零建立了一个新骨架。核心目标是把项目从“功能堆叠脚本”升级为“可恢复、可验收、可扩展的本地字幕生产 pipeline”。

## 已实现模块

- 强引导 CLI：`cs2pov-wizard`
- 专家 CLI：`cs2pov run ...`
- 环境诊断：`cs2pov doctor`
- LLM 配置：`cs2pov config show/set`
- Job/Manifest：每次运行创建独立 job 目录，保存阶段状态和产物路径
- PipelineEngine：统一管理 9 个阶段
- ArtifactStore：统一管理输入、artifacts、final、review、debug 目录
- demoparser2 adapter：负责 demo 解压、header/player 读取、parse_voice、round event 尝试解析
- PyOgg Opus adapter：通过 `pyogg.opus.libopus` + ctypes 解码，避免 PyOgg 版本导出差异
- faster-whisper adapter：转录每个玩家的 compact WAV，并映射回 demo 时间轴
- round translation：按回合组织上下文后翻译
- OpenAI-compatible LLM adapter：DeepSeek/OpenRouter/OpenAI 复用同一接口
- 字幕导出：双语、原文、中文、voice activity SRT
- 地图术语表：Mirage/Dust2/Inferno/Nuke/Ancient/Anubis/Vertigo 的第一批术语
- 纯单元测试：6 个测试全部通过

## Pipeline 阶段

1. `prepare_input`：复制 `.dem` 或解压 `.dem.zst`
2. `inspect_demo`：读取地图、server、玩家
3. `extract_voice`：解析语音包并解码成每个玩家的 compact WAV
4. `build_voice_activity`：根据 packet 时间戳生成语音活动时间轴
5. `parse_rounds`：解析回合边界，失败则降级为单回合
6. `transcribe`：Whisper 自动语言转录
7. `build_round_contexts`：把选中队伍的转录片段归入回合
8. `translate`：按 round 调 LLM 翻译
9. `export_subtitles`：导出 SRT

## 已验证

在沙盒中执行：

```bash
PYTHONPATH=src pytest -q
PYTHONPATH=src python -m cs2pov --help
PYTHONPATH=src python -m cs2pov config show
PYTHONPATH=src python -m cs2pov doctor
```

结果：

- 6 个纯单元测试通过。
- CLI help 正常。
- config show 正常。
- doctor 能正确报告沙盒缺少 demoparser2/zstandard/pyogg/faster-whisper。

## 当前没有在沙盒中完整跑通的原因

当前沙盒没有安装这些可选依赖：

- demoparser2
- zstandard
- pyogg
- faster-whisper

因此这次交付重点是架构和代码实现，而不是在沙盒里再次完整跑真实 demo。你本机已经有 Whisper tiny/base/small，并且可以安装依赖，所以应该由你本机执行真实验收。

## 你本机建议执行

```powershell
cd D:\agent_workspace\cs2pov_arch_project
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
cs2pov doctor
cs2pov-wizard
```

或者用专家验收脚本：

```powershell
python scripts\run_acceptance.py `
  --demo D:\path\to\match.dem.zst `
  --output output `
  --whisper-model tiny `
  --skip-translation `
  --max-rounds 1
```

第一轮建议先 `--skip-translation`，确认 demo→voice→transcript→original srt 能跑通后，再配置 DeepSeek 进行翻译。

## 需要你反馈的中间结果

如果你本机运行失败，优先把这些文件发回来：

- `manifest.json`
- `progress.log`
- `errors.log`
- `artifacts/demo_info.json`
- `artifacts/voice/manifest.json`

如果转录成功但翻译差，把这些发回来：

- `artifacts/transcript_segments.jsonl`
- `artifacts/round_contexts.jsonl`
- `artifacts/translated_segments.jsonl`
- `final/*.srt`

## 我认为下一轮要做的事

1. 用你的真实 Windows 环境跑 `cs2pov doctor` 和 `cs2pov-wizard`。
2. 根据真实错误修 adapter 兼容性，尤其是 demoparser2 round event API。
3. 确认 compact WAV 转录后的时间轴映射效果。
4. 确认按 team 导出的双语 SRT 是否符合 POV 剪辑需求。
5. 再补 resume 命令和更完整的 acceptance test。
