# v0.8.1 测试计划

v0.8.1 是小修版本，重点验证术语 warning 降噪和 benchmark 隐私修复。

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov --help
cs2pov models recommend
```

预期：

```text
73 passed
help 正常
models recommend 正常
```

## 2. 模型管理回归

```powershell
cs2pov models info
cs2pov models list
cs2pov models recommend
cs2pov models test --model small --local-only
```

预期：

```text
模型缓存目录显示正常
已下载模型显示正常
small 本地可用时 test 成功
local-only 缺模型时给出可读失败信息
```

## 3. Global 词典回归

```powershell
cs2pov glossary list --map de_mirage --scope global
cs2pov glossary list --map de_mirage --scope all
```

预期：

```text
global 词典仍存在
Mirage 地图词典仍存在
scope all 同时包含 global + map
```

## 4. 真实翻译 smoke

建议复用 v0.8.0 的 3 回合 smoke：

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v081_glossary `
  --transcription-profile quality `
  --team 2 `
  --max-rounds 3
```

检查：

```text
artifacts/glossary_used.json
artifacts/glossary_warnings.json
final/team_2.bilingual.srt
```

重点预期：

```text
普通英文代词 he 不应触发 global_nade warning
I kill if he push mid / Could he push Palace 不应误报 nade
请架我上中路 这类 boost 自然译法不应误报 boost
他压中路 这类 push 自然译法不应误报 push
```

## 5. ASR benchmark 隐私检查

```powershell
cs2pov benchmark-asr "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v081_benchmark `
  --team 2 `
  --max-rounds 3 `
  --models base,small
```

检查：

```powershell
Get-Content output_v081_benchmark\asr_benchmark.json
```

预期不应出现：

```text
D:\
C:\
agent_workspace
个人项目
```

预期仍应出现 demo 文件名：

```text
1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst
```

## 6. feedback 包

```powershell
cs2pov feedback output_v081_glossary
```

预期反馈包不包含：

```text
sk-
D:\个人项目
D:\AIModels
真实 demo
WAV
```

仍应包含：

```text
artifacts/glossary_used.json
artifacts/glossary_warnings.json
artifacts/transcription_coverage.json
final/*.srt
```

## 7. medium 实验（可选）

这不是 v0.8.1 必测项，但建议后续补测：

```powershell
cs2pov benchmark-asr "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v081_benchmark_medium `
  --team 2 `
  --max-rounds 3 `
  --models small,medium
```

比较：

```text
耗时
转录片段数量
术语识别准确性
是否减少 ASR 错词
是否增加幻觉字幕
```
