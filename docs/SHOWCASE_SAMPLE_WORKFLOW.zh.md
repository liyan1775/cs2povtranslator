# 推广样片制作流程：平台机翻 vs CS2 POV Translator

这份文档用于制作 60~120 秒短视频样片，目标是向 CS2 POV UP 主、玩家和潜在贡献者展示：为什么普通平台机翻不适合 CS2 POV，而本工具的双语字幕更懂 CS2 语境。

## 目标

不是做完整搬运，也不是攻击某个 UP 主。目标是：

```text
平台机翻不懂 CS2 术语；
本工具通过 ASR、回合上下文、global 术语和地图词典，让字幕更接近真实 CS2 报点。
```

## 推荐素材长度

公开样片建议控制在：

```text
60~120 秒
3~5 个短片段
每个片段 5~12 秒
```

私信给 UP 主时，可以附更完整的小样；公开发布时建议克制，避免让对方觉得是在重新分发他的内容。

## 选片原则

优先选择这些片段：

1. 语音密度高。
2. 出现 CS2 通用术语：`trade / push / peek / hold / rotate / save / force / eco`。
3. 出现地图报点：Mirage 的 `Palace / Connector / Ticket`，Dust2 的 `Long / Short / Cat / Pit / Tunnels / Xbox`，Anubis 的 `Canal / Bridge / A Main / B Long / Temple / Cave`。
4. 平台机翻明显错误，且本工具能明显改善。
5. 不涉及敏感争议、辱骂或隐私内容。

## 建议流程

### 1. 用 small CPU 档生成字幕

```powershell
cs2pov config set --transcription-profile quality
cs2pov run "D:\demos\sample.dem.zst" `
  --output output_showcase `
  --map de_anubis `
  --team 2 `
  --max-rounds 3
```

当前办公本推荐：

```text
quality / small / cpu / int8
```

medium 目前只适合实验，不建议普通 CPU 用户日常使用。

### 2. 确认玩家身份并设置字幕显示名

如果 demo 里显示的是临时昵称，例如 `Ebule`，先用 K-D-A 和语音时长确认谁是谁：

```powershell
cs2pov players list output_showcase
```

确认 `Ebule = donk` 后设置字幕显示名：

```powershell
cs2pov players alias output_showcase --name Ebule --as donk
```

这样最终字幕会显示 `[donk]`，而不是 `[Ebule]`。重新导出即可生效，不需要重跑 Whisper/LLM。

### 3. 导出剪辑友好字幕

```powershell
cs2pov export output_showcase --preset editing
```

优先使用：

```text
final/team_*.bilingual.srt
final/team_*.compact.srt
```

### 4. 人工微调展示版

样片用于展示时，可以人工微调少量字幕，但要保留“工具生成”的主体效果。

建议标注：

```text
字幕由 CS2 POV Translator 生成，展示版经过少量人工校对。
```

这样诚实，也避免别人误以为工具已经做到完全无人校对。

### 5. 选择对比例子

每个对比例子只展示一个重点：

```text
平台机翻：trade -> 交易
本工具：trade -> 补枪

平台机翻：push mid -> 推动中间
本工具：push mid -> 压中 / 前压中路

平台机翻：short / cat -> 短的 / 猫
本工具：A小 / 小道

平台机翻：xbox -> Xbox 游戏机
本工具：Xbox箱 / 中路箱

平台机翻：canal / water -> 运河 / 水
本工具：Canal/水道

平台机翻：temple -> 寺庙
本工具：Temple/神庙
```

### 6. 视频结构建议

```text
0:00  问题：平台机翻看不懂 CS2 报点
0:10  对比 1：通用术语 trade / push
0:30  对比 2：地图报点 Long / Short / Pit / Tunnels
0:55  展示工具流程：.bat 菜单、模型档位、双语 SRT
1:15  说明开源免费，不收费，欢迎反馈/贡献词典
1:30  GitHub 链接与邀请
```

## 联系 UP 主时的姿态

不要说“商业合作”。推荐表达为：

```text
我做了一个免费开源的 CS2 POV 字幕工具，主要想帮助做 POV 内容的玩家和 UP 主。
看到平台机翻在 CS2 术语和地图报点上效果不太稳定，我做了一个短样片对比。
如果你觉得有用，欢迎试试或提建议；如果以后方便在简介里带一下 GitHub 链接，我就很感谢了。
```

核心姿态：

```text
免费开源
帮助社区
邀请反馈
不增加对方负担
不要求商业合作
```

## 注意事项

1. 不要公开做过长搬运。
2. 不要攻击 UP 主本人，问题是平台机翻不懂 CS2。
3. 不要承诺 100% 无需人工校对。
4. 不要上传 demo、WAV、API key 或反馈包。
5. 如果使用他人视频片段，公开样片要短，并尽量注明原视频来源。
