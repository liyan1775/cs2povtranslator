# v0.3.1 测试计划

v0.3.1 是 v0.3.0 的菜单体验修复版。重点测试 `.bat`/launcher 子菜单是否可以顺利返回主菜单，同时确认 v0.3.0 已通过的工程命令没有回归。

## 1. 基础检查

```powershell
cd D:\个人项目\cs2pov_arch_project
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
pytest -q
cs2pov doctor
cs2pov config show
```

预期：

```text
39 passed
API key 不显示明文
doctor/config show 中文不乱码
```

## 2. `.bat` 主菜单检查

双击：

```text
Start_CS2_POV_Translator.bat
```

预期：

- banner 显示 v0.3.1；
- 能看到 8 项主菜单功能；
- 顶部提示“子菜单中输入 0、q、back 或 返回，可随时回到主菜单”。

## 3. 子菜单返回测试

逐项进入以下菜单，然后输入 `0` 返回：

```text
3. 重新导出字幕 export
4. 重新翻译 retranslate
5. 从某阶段恢复 resume
6. 打包反馈包 feedback
```

预期：

- 不会报错；
- 不会要求完成整个流程；
- 会显示“已返回主菜单”；
- 可以继续选择其他菜单项。

也建议额外测试 `q`、`back`、`返回` 三种取消输入。

## 4. 工程命令轻量回归

用已有 Job 测试：

```powershell
cs2pov inspect-job output
cs2pov export output --format zh
cs2pov retranslate output --dry-run
cs2pov resume output --from-stage export_subtitles
cs2pov feedback output
```

预期：

- `inspect-job` 能显示 Job 状态和推荐下一步；
- `export` 不重新转录/翻译；
- `retranslate --dry-run` 不调用真实 LLM；
- `resume --from-stage export_subtitles` 只重跑导出阶段；
- `feedback` zip 不包含 `artifacts/voice/`、`artifacts/temp_audio/`、原始 `.dem/.dem.zst` 或 `sk-`。

## 5. 不需要重复测试的内容

除非你想做完整回归，本版不要求重新跑真实 demo 的完整 Whisper/LLM pipeline。v0.3.1 没有修改这些底层模块。

## 6. 如果还有问题，请打包

```powershell
cs2pov feedback output
```

同时附上：

- 你在 `.bat` 菜单里选择了哪个编号；
- 你输入的是 `0`、`q`、`back` 还是 `返回`；
- 终端显示的错误信息截图或文本。
