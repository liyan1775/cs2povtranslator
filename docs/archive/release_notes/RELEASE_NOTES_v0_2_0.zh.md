# CS2 POV Translator v0.2.0 发布说明

## 版本定位

v0.2.0 不是继续修 v0.1.x 的小问题，而是进入 **强引导 CLI 产品化** 阶段。

这一版的目标是让用户双击启动脚本或运行 `cs2pov-wizard` 后，能够被一步步带着完成：

1. 选择 demo 文件
2. 确认地图
3. 选择 POV 主角
4. 选择 Whisper 转录配置
5. 选择快速测试或完整处理
6. 配置翻译方式
7. 确认任务并运行
8. 查看输出与反馈包指引

## 主要新增

### 1. 重写强引导向导

`cs2pov-wizard` 现在不再只是简单询问几个参数，而是明确拆成 8 个步骤，并在每一步解释当前在做什么、推荐选什么、输出会在哪里。

新增体验包括：

- 清晰的 8 步流程提示
- demo 文件拖入提示
- 输出目录自动创建
- 地图确认
- POV 玩家列表表格
- 默认推荐语音最多的玩家
- 默认导出 POV 玩家所在队伍的全部语音
- Whisper tiny/base/small 选择说明
- ASR auto/en/ru/zh 选择说明
- round/activity/player 转录模式说明
- 快速测试前 3 回合 / 完整处理 / 自定义回合数
- 真实翻译 / dry-run / 跳过翻译 / 配置 LLM
- 运行前任务摘要
- 完成后输出目录与反馈包命令提示

### 2. 新增反馈包命令

新增：

```powershell
cs2pov feedback <job目录或output根目录>
```

它会生成一个 zip，包含排查问题需要的文本产物：

- manifest.json
- progress.log
- errors.log
- demo_info.json
- rounds_raw.json / rounds.json
- voice_activity.jsonl
- transcript_segments.jsonl
- round_contexts.jsonl
- translated_segments.jsonl
- transcription_coverage.json
- final / review / debug 下的 SRT 和文本产物

它会排除：

- artifacts/voice/
- artifacts/temp_audio/
- 原始 demo 文件

这样反馈包不会动辄几十 MB，也不会包含大音频缓存。

### 3. 保留 v0.1.x 的稳定默认路线

v0.2.0 没有破坏 v0.1.8 的默认 pipeline：

- 默认转录模式：round
- 默认 Whisper VAD：ON
- 默认幻觉过滤：ON
- 默认长 cue 重贴阈值：15s
- 默认 DeepSeek 模型：deepseek-v4-flash
- manifest 继续隐藏 API key

## 没有做什么

- 没有提前做完整词典系统
- 没有做 UI
- 没有做 resume/export/retranslate 子命令
- 没有大改 ASR 默认策略

这些仍然属于后续阶段。

## 开发侧验证

在沙盒中完成：

```text
28 passed
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov feedback --help
python -m cs2pov doctor > doctor.txt
```

真实 demo、Whisper、demoparser2 仍需在你的 Windows 本机测试。
