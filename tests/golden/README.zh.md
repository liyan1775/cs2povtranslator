# 金标准夹具

`manifest.json` 固定 v0.9.8 可信基线的输入、聚合预期、理解翻译案例、旧字幕输出和已知缺陷。

素材分为两层：

1. `checked-in`：只包含很小的确定性 JSON 合成配方、结构化时间线和期望字幕，可在 GitHub CI 稳定重放；
2. `local-only`：真实 Demo 和旧字幕不进入 Git，只登记匿名夹具 ID、字节数、SHA-256 和不含身份信息的聚合预期。

本目录不得加入 Demo、音视频、模型、SteamID、API Key 或本机绝对路径。真实素材由后续统一工作区按哈希定位。

校验清单：

```powershell
python scripts/check_golden_baseline.py
```

同时重放选定的旧版本行为测试：

```powershell
python scripts/check_golden_baseline.py --replay
```

在本机确认一份真实 Demo 是否匹配已登记夹具（可以重复传入）：

```powershell
python scripts/check_golden_baseline.py --local-fixture "authorized-demo-anubis-local-v1=D:\你的目录\demo.dem"
```

校验器只输出匿名夹具 ID，不回显文件路径或哈希；它也不会复制、移动或修改 Demo。

`be be be → B, B, B` 当前只是金标准候选，不能改写 v0.9.8 原始 ASR。阶段 5 才会实现“原始转录 / 理解文本 / 中文翻译 / 证据 / 置信度”的正式契约。

`structured_timeline_v1.json` 仍是冻结的 v0.9.8 基线；`new_domain_contract_v1.json`
校验当前版本的新领域契约。后者不是旧版输出等价性的证明，不得作为 legacy
输出等价来介绍。
