# CS2 POV Translator v0.9.0 测试计划

## 测试目标

验证 v0.9.0 的 Comms Overlay MVP 是否能服务真实 POV 视频制作：

```text
已有 Job 翻译结果
→ 生成按回合通讯流
→ 人工修改 YAML
→ 只渲染指定回合 overlay
→ 导入剪映叠加到 lim 授权 POV 视频
```

## 本版本重点测试内容

### A. 代码层测试

开发侧已运行：

```powershell
pytest -q
python -m compileall src tests
```

重点覆盖：

- `comms build-review` 是否生成 `comms_feed.json/html/md`。
- 是否按回合生成 `review/comms_rounds/round_XX.yaml`。
- 玩家别名是否会应用到 Comms Feed，例如 `Ebule -> donk`。
- `show_at` 是否能从回合时间正确计算，例如 `1:55` 开始、23 秒后显示为 `1:32`。
- `--rounds 1,3-5` 是否正确解析。
- `comms render --formats png` 是否能生成单帧排版预览。
- 旧字幕测试是否全部继续通过。

### B. 本地真实 Job 测试

请在你本地用真实 demo 跑出一个已有 Job 后测试：

```powershell
cs2pov inspect-job output
cs2pov comms build-review output --rounds 1-3
```

预期结果：

```text
final/comms_feed/comms_feed.json
final/comms_feed/comms_feed.md
final/comms_feed/comms_feed.html
review/comms_rounds/round_01.yaml
review/comms_rounds/round_02.yaml
review/comms_rounds/round_03.yaml
review/comms_rounds/README_COMMS_REVIEW.md
```

检查点：

- 每条消息有 `show_at / speaker / zh / source / enabled`。
- 中文优先，英文保留。
- 目标队伍过滤正确。
- 玩家别名正确。
- 空回合不生成无意义 overlay YAML。

### C. 人工修改中间产物测试

打开：

```text
review/comms_rounds/round_01.yaml
```

尝试修改：

```yaml
zh: "修改后的中文"
enabled: false
speaker: donk
show_at: "1:31"
```

然后运行：

```powershell
cs2pov comms render output --rounds 1 --formats png
```

预期结果：

```text
final/comms_overlay/round_01_overlay_preview_state.png
```

检查点：

- 修改后的中文出现在图片中。
- `enabled: false` 的消息不出现。
- 玩家名修改生效。

### D. 视频渲染测试

确认本机能运行 ffmpeg：

```powershell
ffmpeg -version
```

然后运行：

```powershell
cs2pov comms render output --rounds 1-3 --formats preview,green
```

预期结果：

```text
final/comms_overlay/round_01_overlay_preview.mp4
final/comms_overlay/round_01_overlay_green.mp4
final/comms_overlay/round_02_overlay_preview.mp4
final/comms_overlay/round_02_overlay_green.mp4
...
```

检查点：

- preview 视频可播放。
- 右侧中部出现半透明通讯面板。
- 中文和英文均显示。
- 消息按回合时间逐条出现。
- 同屏消息不超过默认 4 条。
- green 视频背景为绿色，面板和文字可见。

### E. 剪映叠加测试

剪映流程：

```text
1. 导入 lim 的 POV 视频。
2. 导入 round_01_overlay_green.mp4。
3. 放到第 1 回合视频片段上方轨道。
4. 尝试使用色度抠图去掉绿色背景。
5. 观察右侧通讯流是否位置合适、字号是否可读、是否遮挡关键画面。
```

可选测试：

```powershell
cs2pov comms render output --rounds 1 --formats alpha
```

然后在剪映中测试 `round_01_overlay_alpha.mov` 是否保留透明通道。

## 如果失败，请打包哪些反馈

### build-review 失败

请提供：

```powershell
cs2pov feedback output
```

并额外说明：

```text
运行的命令
终端报错全文
你期望生成哪些回合
```

反馈包应包含：

```text
manifest.json
progress.log
errors.log
artifacts/translated_segments.jsonl
artifacts/rounds.json
artifacts/player_aliases.json
final/comms_feed/*.json/html/md（如果已生成）
review/comms_rounds/*.yaml（如果已生成）
```

### render 失败

请提供：

```text
运行的命令
ffmpeg -version 输出
对应 round_XX.yaml
终端报错全文
final/comms_overlay 中已生成的文件列表
```

如果视频生成了但画面不好，请提供：

```text
round_XX_overlay_preview.mp4 或 preview_state.png
你在剪映里的截图
你希望的位置/字号/透明度调整意见
```

### 剪映透明通道失败

请说明：

```text
剪映版本
alpha.mov 是否能导入
导入后是否有透明背景
green.mp4 色度抠图是否可用
是否需要改成 WebM alpha / PNG 序列 / 其他格式
```

## 本版本通过标准

v0.9.0 通过不要求 overlay 美术最终完美；通过标准是：

```text
1. 能从真实 Job 生成按回合 YAML。
2. 人工修改 YAML 后能只重渲染对应回合。
3. 能生成至少一种可在剪映叠加的素材：green.mp4 或 alpha.mov。
4. preview 能帮助发现翻译错字和排版问题。
5. 不破坏原有 SRT 导出和反馈包工作流。
```
