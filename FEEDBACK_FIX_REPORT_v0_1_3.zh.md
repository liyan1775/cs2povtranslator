# v0.1.3 反馈修复报告

基于用户提供的 `feedback_v0_1_2.zip`，本版主要处理两个问题：

1. Windows 双击 `.bat` 时误用系统 Python，导致 `ModuleNotFoundError: No module named 'cs2pov'`。
2. Whisper tiny 对 CS2 超短 PTT 报点的转录覆盖率偏低，需要给用户可控的对照测试手段和可审计的覆盖率产物。

## 一、反馈包验证结论

v0.1.2 的核心重构方向已通过真实 demo 验证：

- 单元测试：`11 passed`
- `.dem.zst` 解压：成功
- 地图识别：`de_mirage`
- 语音提取：成功，9 名玩家有语音
- Opus 解码：0 丢包
- round 清洗：`rounds_raw.json` 33 条，`rounds_cleaned.json` 30 条
- round mapping：30 个有效回合 + 1 个 orphan，转录归入回合质量明显改善
- Team 2 / Team 3 dry-run 字幕导出：成功
- DeepSeek LLM 小范围翻译：成功

本轮新问题集中在启动脚本和 ASR 覆盖率，不是 PipelineEngine 或回合清洗失败。

## 二、修复 1：Bat 启动脚本改用项目虚拟环境

### 问题

v0.1.2 的启动脚本使用：

```bat
py -3 -X utf8 -m cs2pov.cli.wizard
```

这会调用系统 Python。但用户是把包安装在项目 `.venv` 里，所以双击脚本会报：

```text
ModuleNotFoundError: No module named 'cs2pov'
```

### v0.1.3 修复

两个脚本都已改为优先调用：

```bat
.venv\Scripts\python.exe -X utf8 -m cs2pov.cli.wizard
```

如果 `.venv` 不存在，脚本不会再直接失败，而是输出明确安装步骤：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
cs2pov doctor
```

涉及文件：

- `Start_CS2_POV_Translator.bat`
- `启动 CS2 POV Translator.bat`

## 三、修复 2：Whisper VAD 默认关闭，减少短报点漏检

### 问题

反馈包显示：

- voice activity：1847 条
- transcript：1085 条
- 小于 1 秒的 voice activity：约 1006 条，占 54%

CS2 PTT 语音经常是极短报点，例如 `go`、`one`、`A short`、`jungle`。v0.1.2 使用 faster-whisper 时默认 `vad_filter=True`，这可能会进一步丢掉超短语音。

### v0.1.3 修复

`FasterWhisperAdapter` 默认改为：

```python
vad_filter=False
```

并新增 CLI 参数：

```powershell
--whisper-vad
--no-whisper-vad
```

默认不启用 VAD。用户可以手动开启做对比实验。

涉及文件：

- `src/cs2pov/adapters/whisper_adapter.py`
- `src/cs2pov/domain/models.py`
- `src/cs2pov/cli/commands.py`
- `scripts/run_acceptance.py`

## 四、增强：新增 transcription_coverage.json

v0.1.3 会生成：

```text
artifacts/transcription_coverage.json
```

它记录：

- 当前 team 的 voice activity 数量
- 转录片段数量
- 大于阈值的 voice activity 数量
- 与 transcript 有重叠的 voice activity 数量
- 未匹配的 voice activity 数量
- 估算覆盖率

注意：这是启发式统计。因为当前语音处理使用 compact WAV，一个 ASR 片段可能覆盖多个短 PTT burst，所以它不是严格的“准确率”，但很适合做 tiny/base/small、VAD 开关的横向对比。

## 五、增强：可选补 `[未识别语音]` 占位

新增参数：

```powershell
--include-unrecognized-voice
--unrecognized-min-duration 0.35
```

启用后，如果某条 voice activity 大于阈值但没有匹配到同一玩家的 transcript，系统会在 transcript 中补一条：

```text
[未识别语音]
```

这样可以保留时间轴位置，方便用户检查漏识别。

默认不开启，避免字幕里出现大量占位内容。

## 六、测试结果

沙盒中已验证：

```text
13 passed
```

包含新增测试：

- `tests/test_transcription_coverage.py`
- `tests/test_launcher_scripts.py`

同时验证：

```text
PYTHONPATH=src python -m cs2pov --help
PYTHONPATH=src python -m cs2pov doctor
PYTHONPATH=src python -m cs2pov run --help
```

## 七、仍需用户本机验证

我这里无法用 faster-whisper + 真实 demo 完整验证 v0.1.3 的转录数量变化。因此本版最重要的用户测试是：

1. 双击 `.bat` 是否能进入向导；
2. tiny 默认关闭 VAD 后，转录数是否高于 v0.1.2；
3. small 模型是否显著提升短语音识别；
4. `transcription_coverage.json` 是否能辅助判断漏识别。
