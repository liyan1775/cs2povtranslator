# v0.8.2 发布说明：Dust2 词典试点与推广样片流程

v0.8.2 是 v0.8.x 的小版本增强，目标是服务下一阶段推广样片：用真实 Dust2/Mirage POV 片段证明本工具比平台机翻更懂 CS2 术语和地图报点。

本版本不新增大 pipeline，不改变默认 ASR 模型策略，不默认 CUDA。

## 1. 新增 Dust2 地图词典 pilot

新增 `de_dust2` 地图词典，第一批覆盖 31 个高频点位：

```text
A大 / A大门 / 大坑 / 大坑边 / 蓝箱 / A车 / A斜坡 / A包点 / 鹅位
A小 / 小道楼梯 / 中路 / 中远 / 中门 / Xbox箱 / 自杀位 / 警中
B洞 / 上洞 / 下洞 / 暗位 / B包点 / B门 / B窗 / B车 / B平台 / 后平台 / 铁网
匪家 / 警家 / 默认包位
```

命令：

```powershell
cs2pov glossary list --map de_dust2
cs2pov glossary list --map de_dust2 --scope map
cs2pov glossary list --map de_dust2 --scope global
```

词典仍然只用于：

```text
1. 翻译 prompt 约束
2. glossary_used.json
3. glossary_warnings.json
```

不会硬替换字幕文本。

## 2. Mirage / Dust2 双地图试点

更新了以下入口文案：

```text
README.zh.md
README.md
setup-check
.bat glossary 菜单
wizard 提示
commands help
```

现在地图词典试点从：

```text
de_mirage
```

扩展为：

```text
de_mirage
de_dust2
```

其他地图仍然只使用 global 通用术语。

## 3. 新增 Dust2 词典说明文档

新增：

```text
docs/GLOSSARY_DUST2_PILOT.zh.md
```

说明：

```text
1. Dust2 第一批词条范围
2. 高风险歧义词：doors / car / window / short / long
3. 推荐中文译法与可接受别名
4. 词典来源标签
5. 后续如何根据真实样片修正
```

## 4. 新增推广样片流程文档

新增：

```text
docs/SHOWCASE_SAMPLE_WORKFLOW.zh.md
```

用于指导制作 60~120 秒短视频样片：

```text
平台机翻 vs CS2 POV Translator
```

核心定位：

```text
免费开源
帮助 CS2 POV 内容作者
邀请 UP 主和玩家反馈/贡献词典
不做商业合作导向
```

## 5. 测试情况

本地验证：

```text
78 passed
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov glossary list --map de_dust2
python -m cs2pov glossary list --map de_dust2 --scope map --json
python -m cs2pov setup-check --json
python -m cs2pov.cli.launcher --once
```

## 6. 建议测试重点

v0.8.2 的重点不是完整 demo 性能，而是 Dust2 词典与样片准备：

```powershell
pytest -q
cs2pov glossary list --map de_dust2
cs2pov glossary list --map de_dust2 --scope map --json
cs2pov setup-check
Start_CS2_POV_Translator.bat
```

如果本地有 Dust2 demo，建议跑前 3 回合：

```powershell
cs2pov config set --transcription-profile quality
cs2pov run "D:\demos\dust2_sample.dem.zst" `
  --output output_v082_dust2 `
  --map de_dust2 `
  --team 2 `
  --max-rounds 3
cs2pov glossary check output_v082_dust2
```
