# v0.1.7 反馈核查与修复报告

## 反馈包核查结论

本轮反馈包包含：

- `README.md`
- `manifest_v016.json`
- `coverage_v016.json`
- `progress_v016.log`
- `srt_v016.srt`

我没有直接采信本地 agent 报告，而是核查了真实产物。

### 已确认通过

1. `manifest_v016.json` 没有出现 `sk-` 明文 API key。
2. `llm_api_key` 已写成 `[已配置-已隐藏]`。
3. `llm_api_key_configured` 为 `true`，既保留“已配置”状态，又不泄露密钥。
4. `coverage_v016.json` 已包含 postprocess 前后字段。
5. 默认 round 模式 smoke test 输出稳定：
   - `transcript_segments = 31`
   - `coverage_ratio_before_postprocess = 0.9118`
   - `coverage_ratio_after_postprocess = 0.9118`
   - `longest_transcript_segment_seconds = 13.203`
   - `long_transcript_segments_gt_30s = 0`
6. `progress_v016.log` 显示完整 pipeline 成功结束。
7. SRT 中没有再出现 v0.1.4 级别的超长 cue，也没有本轮测试中的纯标点 hallucination。

### 新发现

`manifest_v016.json` 中的配置仍显示：

```json
"llm_model": "deepseek-chat"
```

这不是 v0.1.6 的安全问题，也没有影响 dry-run 测试结果；但考虑到后续模型兼容性，v0.1.7 做了轻量维护：不改 pipeline，不提前做词典系统，只对旧模型配置增加提示。

## v0.1.7 修复内容

### 1. 向导默认模型改为 `deepseek-v4-flash`

`cs2pov-wizard` 中首次配置 DeepSeek / OpenAI-compatible LLM 时，模型默认值从：

```text
deepseek-chat
```

改为：

```text
deepseek-v4-flash
```

### 2. `config show` 标记旧模型配置

如果本机配置仍然是：

```text
deepseek-chat
```

或：

```text
deepseek-reasoner
```

`cs2pov config show` 会显示：

```json
"llm_model_deprecated": true,
"recommended_llm_model": "deepseek-v4-flash"
```

并打印提示。

### 3. `doctor` 增加模型迁移提示

`cs2pov doctor` 会继续隐藏 API key，但如果检测到旧模型名，会额外输出：

```text
LLM warning: 模型 deepseek-chat 即将/已经不推荐继续使用，建议改为 deepseek-v4-flash。
```

### 4. 新增测试

新增 `tests/test_llm_model_maintenance.py`。

当前测试结果：

```text
23 passed
```

## 没有做的事

本轮没有提前实现词典系统。

原因：词典是重要产品质量模块，但不是当前重构阶段的技术阻塞项。v0.1.7 只做模型配置维护，主线仍然保持：

1. 稳定默认 pipeline；
2. 进入 v0.2.0 强引导 CLI 产品化；
3. 后续再做字幕质量、导出策略、词典和复跑能力。
