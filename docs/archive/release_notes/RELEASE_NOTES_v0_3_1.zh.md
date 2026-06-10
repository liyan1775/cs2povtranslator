# v0.3.1 发布说明：菜单返回与产品体验修复

v0.3.1 基于 v0.3.0 的真实反馈包开发。v0.3.0 的新增工程命令已经通过本地真实测试：`inspect-job`、`export`、`retranslate`、`resume`、`feedback` 和 `.bat` 主菜单均可用。本版不修改 pipeline，不调整 ASR/字幕参数，只修复一个影响普通用户体验的问题：子菜单缺少返回主菜单选项。

## 核查到的 v0.3.0 结果

- `35 passed`，新增工程命令测试通过。
- `.bat` 菜单可显示 8 项功能说明。
- `inspect-job` 可查看已完成/未完成 Job，并给出推荐下一步。
- `export` 可秒级重新导出多种字幕格式，不调用 Whisper/LLM。
- `retranslate` 可 dry-run 或真实调用 LLM，不重新转录。
- `resume --from-stage export_subtitles` 只重跑导出阶段。
- `feedback` 反馈包不包含 WAV、临时音频、原始 demo 或明文 API key。
- 新鲜 smoke pipeline 可跑通 9 个阶段。

## 修复内容

### 1. 子菜单支持返回主菜单

以下场景现在都可以输入 `0`、`q`、`back` 或 `返回` 取消当前操作：

- 输入 Job 路径时；
- export 选择导出格式时；
- export 选择双语格式时；
- retranslate 选择翻译方式时；
- retranslate 临时输入模型名时；
- resume 选择恢复阶段时；
- resume 需要输入 demo 路径时；
- feedback 输入 Job 路径时。

这样用户不小心进错菜单时，不需要完成整个流程，也不需要按 Ctrl+C。

### 2. `.bat` 启动说明更明确

启动 banner 新增说明：

```text
在子菜单中输入 0、q、back 或 返回，可随时回到主菜单。
```

帮助页也补充了同样的说明。

### 3. 新增菜单导航测试

新增测试覆盖：

- export 子菜单返回；
- retranslate 子菜单返回；
- resume 子菜单返回；
- feedback 子菜单返回。

## 已验证

```text
39 passed
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov.cli.launcher --once
```

## 不包含的改动

v0.3.1 不改动：

- demo 解析；
- 语音提取；
- Whisper 转录；
- LLM 翻译；
- 字幕 cue 时长策略；
- `inspect-job/export/retranslate/resume` 的核心行为。

如果 v0.3.1 验收通过，下一步可以继续在 v0.3.x 做更完整的 Job 工程能力，例如 `inspect-job` 更丰富的诊断、`export` 字幕模板增强、`resume` 更清晰的失败阶段建议。
