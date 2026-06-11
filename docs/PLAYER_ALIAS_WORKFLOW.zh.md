# 玩家识别与字幕显示名映射

v0.8.6 新增玩家识别和字幕显示名功能，用来解决 CS2 POV demo 里的常见问题：

- demo 里显示的是 FACEIT / Steam 临时昵称，而不是职业 ID；
- 用户不知道谁是 donk、m0NESY、phzy；
- 最终字幕里显示 `[Ebule]` 这类昵称不适合视频成片；
- 后期手动改 SRT 容易漏改，且每次重新导出都会丢失。

## 推荐流程

处理 demo 到生成 Job 后，先查看玩家列表：

```powershell
cs2pov players list output
```

输出会展示：

```text
Team
Demo 昵称
字幕显示名
K-D-A
语音时长
语音包数
```

K-D-A 只用于帮助确认身份。比如视频标题写 `donk 30-11`，而列表里 `Ebule` 的 K-D-A 是 `30-11-x`，就可以确认：

```text
Ebule = donk
```

设置字幕显示名：

```powershell
cs2pov players alias output --name Ebule --as donk
```

重新导出字幕即可生效：

```powershell
cs2pov export output --preset editing
```

不需要重跑 Whisper，也不需要重新调用 LLM。

## 精确匹配 SteamID

如果 demo 里有重名，建议用 SteamID：

```powershell
cs2pov players alias output --steamid 7656119xxxxxxxxxx --as donk
```

## 清除别名

清除单个玩家：

```powershell
cs2pov players clear-alias output --name Ebule
```

清除全部：

```powershell
cs2pov players clear-alias output --all
```

## 成片字幕效果

设置前：

```text
[Ebule] Care cave, care cave.
[中文] 小心黑屋，小心黑屋。
```

设置后：

```text
[donk] Care cave, care cave.
[中文] 小心黑屋，小心黑屋。
```

## 设计原则

- 别名是 Job 级配置，不是全局配置；同一个临时昵称在不同 demo 里可能不是同一个人。
- 别名只影响导出的字幕显示名，不改写原始 transcript / translation 产物。
- K-D-A 解析依赖 demo 的 `player_death` 事件。如果 parser 或 demo 不提供相关字段，会显示 `?-?-?`，此时仍可用语音时长、队伍和视频画面人工确认。
