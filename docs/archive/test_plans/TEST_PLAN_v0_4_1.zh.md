# CS2 POV Translator v0.4.1 测试计划

本版只修复 Windows 路径兼容问题，重点测试 `explain-output`。

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov setup-check
cs2pov doctor
```

预期：测试通过，中文不乱码，API key 不显示明文。

## 2. 复用已有 Job 测试 explain-output

```powershell
cs2pov explain-output output_acceptance
```

或指定具体 Job：

```powershell
cs2pov explain-output "output_acceptance\20260610_150453_de_mirage"
```

预期：

- “你最可能需要的文件”下面能看到 `final/team_2.bilingual.srt` 和 `final/team_2.zh.srt`。
- `final/`、`review/`、`debug/` 都不再错误显示“暂无相关文件”。
- 输出路径统一使用 `/`，例如 `final/team_2.bilingual.srt`。

## 3. 菜单测试

双击 `Start_CS2_POV_Translator.bat`，选择“解释输出文件”。

预期：输入已有 output 或 Job 目录后，能正确显示 final/review/debug/artifacts 文件说明，并可用 0/q/back/返回 回到主菜单。

## 4. 不需要重测的内容

本版不改 pipeline，不需要重新跑完整 demo、DeepSeek 翻译或 Whisper 模型对比。
