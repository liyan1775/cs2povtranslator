# CONTRIBUTING

欢迎贡献，但本项目当前仍处于本地优先的作品集/工具孵化阶段。请优先围绕真实用户路径提交改动。

## 开发环境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
pytest -q
cs2pov setup-check
```

## 提交前检查

```powershell
pytest -q
python -m compileall -q src scripts
cs2pov doctor
cs2pov config show
```

不要提交：

- `.venv/`
- `output/`
- 原始 `.dem` / `.dem.zst`
- `artifacts/voice/` 或 `artifacts/temp_audio/`
- API key、私有路径、真实反馈包中的敏感内容

## 贡献优先级

优先接受：

- 修复真实 demo 反馈暴露的问题。
- 改善 CLI 文案和错误提示。
- 改善 feedback 包脱敏和诊断信息。
- 增加不依赖真实 demo 的单元测试。
- 改善 README / docs / FAQ。

谨慎接受：

- 大规模重构。
- 新增模型后端。
- 新地图词典。
- 改变默认 ASR / 字幕策略。

暂不建议：

- GUI。
- 云端服务。
- 一次性全地图词典。
- 与字幕主链路无关的炫技功能。

## 词典贡献原则

词典必须保守推进。每个术语建议包含：

- map：地图名
- canonical_en：英文主词
- aliases_en：英文别名
- aliases_ru：俄语/音译可能说法
- zh：中文推荐说法
- confidence：置信度
- note：争议或备注

不要为了“完整”提交没有复核的词条。
