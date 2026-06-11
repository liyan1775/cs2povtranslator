# v0.8.0 测试计划

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov --help
cs2pov setup-check
cs2pov doctor
cs2pov config show
```

预期：

```text
68 passed
API key 不显示明文
setup-check / doctor 中文不乱码
help 中出现 models / benchmark-asr
```

## 2. 模型管理命令

```powershell
cs2pov models info
cs2pov models list
cs2pov models recommend
```

预期：

```text
info 显示项目级缓存目录、HF_HOME、HF_HUB_CACHE、当前 profile/model/device/compute_type
list 显示已下载模型；没有模型时给出友好提示
recommend 显示 fast/balanced/quality/medium_cpu/cuda_quality 和 tiny/base/small/medium 等近似大小
```

## 3. 设置模型缓存目录

建议使用临时测试目录：

```powershell
cs2pov models set-cache "D:\AIModels\huggingface_test"
cs2pov config show
cs2pov models info
```

预期：

```text
config show 中 whisper_cache_dir 被保存
models info 中候选缓存目录包含 D:\AIModels\huggingface_test\hub 或对应项目级目录
```

注意：本命令不应修改系统全局环境变量。

## 4. 模型加载测试

如果本地已有 small：

```powershell
cs2pov models test --model small --local-only
```

如果想允许下载：

```powershell
cs2pov models test --model small
```

预期：

```text
已有模型时 OK
缺模型且 local-only 时应给出可读失败信息
```

## 5. 转录质量档位配置

```powershell
cs2pov config set --transcription-profile quality
cs2pov config show
```

预期：

```text
transcription_profile = quality
whisper_model = small
whisper_device = cpu
whisper_compute_type = int8
```

再恢复平衡档：

```powershell
cs2pov config set --transcription-profile balanced
```

## 6. .bat 菜单

双击：

```text
Start_CS2_POV_Translator.bat
```

重点测试：

```text
11. Whisper 模型管理 models
```

预期：

```text
能查看缓存信息
能列出模型
能看到推荐档位
能设置缓存目录
能返回主菜单
```

## 7. Global 词典

```powershell
cs2pov glossary list --map de_mirage --scope global
cs2pov glossary list --map de_mirage --scope all
```

预期：

```text
scope global 中能看到 AWP / flash / smoke / push / trade / eco 等通用术语
scope all 中同时包含 global 通用术语和 Mirage 地图报点
```

## 8. 真实 demo 小范围 benchmark

```powershell
cs2pov benchmark-asr "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v080_benchmark `
  --team 2 `
  --max-rounds 3 `
  --models base,small
```

预期：

```text
生成 output_v080_benchmark/asr_benchmark.json
每个模型都有单独 Job 目录
报告中包含 elapsed_seconds、transcript_segments、longest_transcript_segment_seconds 等字段
```

## 9. 真实翻译 smoke

```powershell
cs2pov run "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output_v080_glossary `
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

预期：

```text
glossary_used.json 中包含 global_terms 和 map_terms
matched_global_term_count / matched_map_term_count 可读
manifest.json 不出现 API key 或本地模型缓存路径
```

## 10. 反馈包

```powershell
cs2pov feedback output_v080_glossary
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
