# v0.4.0 测试计划

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov setup-check
cs2pov doctor
cs2pov config show
```

预期：

- 单元测试通过；
- `setup-check` 能输出普通用户检查表；
- `doctor/config show` 中文不乱码；
- API key 不显示明文。

## 2. `.bat` 菜单测试

双击：

```text
Start_CS2_POV_Translator.bat
```

重点测试：

- 菜单显示 v0.4.0；
- 选项 2：setup-check；
- 选项 4：explain-output；
- 选项 10：安装 / 首次使用教程；
- 子菜单输入 `0/q/back/返回` 能返回主菜单。

## 3. 安装脚本测试

在干净目录或删除 `.venv` 后双击：

```text
Install_CS2_POV_Translator.bat
```

预期：

- 显示 `[1/4]` 到 `[4/4]`；
- 自动创建 `.venv`；
- 自动安装依赖；
- 最后运行 `cs2pov setup-check`。

## 4. 输出解释测试

用已有 Job：

```powershell
cs2pov explain-output output
```

预期：

- 明确推荐 `final/*.bilingual.srt` / `final/*.zh.srt`；
- 解释 `review/ debug/ artifacts/`；
- 给出 export/retranslate/feedback 下一步命令。

## 5. 验收脚本测试

```powershell
powershell -ExecutionPolicy Bypass -File scripts\acceptance_smoke.ps1 `
  -Demo "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  -Output output_acceptance `
  -WhisperModel tiny `
  -Team 2 `
  -MaxRounds 3
```

预期：

- dry-run pipeline 成功；
- inspect-job 成功；
- export 成功；
- feedback 包生成；
- feedback 包不包含原始 demo / artifacts/voice / artifacts/temp_audio / sk-。

## 6. 非目标

v0.4.0 不要求重新大规模比较 ASR 模式，也不要求测试词典或 UI。
