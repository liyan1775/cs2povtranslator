# v0.1.8 反馈修复报告

## 反馈来源

本版本基于 `feedback_v0_1_7.zip` 进行核查。反馈包内本地 agent 报告显示 v0.1.7 验收通过；我进一步检查了真实产物，包括：

- `manifest.json`
- `progress.log`
- `transcription_coverage.json`
- `team_2.bilingual.srt`
- `config_show.txt`
- `doctor.txt`

## 核查结论

v0.1.7 的目标整体通过：

- `manifest.json` 未发现 `sk-` 明文 API key。
- `llm_model` 已迁移为 `deepseek-v4-flash`。
- 默认 smoke test 仍然保持 13.2s 最长 cue，没有 30s+ 超长 cue。
- round 模式、VAD ON、长 cue 重贴等默认策略没有回归。

但核查真实产物时发现两个新的小问题。

## 问题 1：幻觉过滤漏掉重贴后的标点尾巴

`team_2.bilingual.srt` 中仍出现类似：

```text
끝,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,,
```

原因不是 v0.1.5 的过滤完全失效，而是处理顺序问题：

1. 先过滤原始 ASR segment。
2. 再把过长 cue 重贴/切分到 voice activity 簇。
3. 切分后产生的标点尾巴没有再次过滤。

v0.1.8 修复：

- 在长 cue 重贴后，再运行一次幻觉过滤。
- 加强 `is_probable_whisper_hallucination()`，现在可以识别“少量有效字符 + 大量标点”的 Whisper 噪声。
- 新增统计字段：`filtered_hallucination_segments_after_rebase`。

过滤仍然保持保守策略，会保留：

- `go`
- `A`
- `B?`
- `one!`
- `警家一个`
- `да`
- `끝`

只过滤纯标点或标点占绝大多数的明显噪声。

## 问题 2：config_show / doctor 输出为 GBK，反馈包里显示乱码

反馈包里的 `progress.log` 是 UTF-8，显示正常；但 `config_show.txt` 和 `doctor.txt` 是 GBK/ANSI 编码，在非 Windows 环境或部分工具中会显示为乱码。

原因是用户直接运行 `cs2pov doctor` / `cs2pov config show` 时，如果没有通过 `.bat` 设置 UTF-8，Windows Python 可能使用本地代码页输出。

v0.1.8 修复：

- 新增 `cs2pov.cli.encoding.configure_utf8_stdio()`。
- `cs2pov` 和 `cs2pov-wizard` 启动时强制 stdout/stderr 使用 UTF-8。
- 后续重定向出的 `doctor.txt` / `config_show.txt` 应该能被 UTF-8 正常读取。

## 验证情况

沙盒内已验证：

```text
25 passed
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov doctor
```

其中 `doctor` 输出已确认是 UTF-8 可解码文本。

## 本版本定位

v0.1.8 是 v0.1.x 的小维护版，不进入 v0.2 的大改。若 v0.1.8 通过，后续建议正式切入：

```text
v0.2.0：强引导 CLI 产品化
```
