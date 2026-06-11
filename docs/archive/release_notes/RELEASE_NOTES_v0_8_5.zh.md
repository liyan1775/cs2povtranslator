# v0.8.5 - 中文社区报点校准

这是 v0.8.x 词典试点阶段的小修版，目标是根据真实 POV 样片制作前的中文社区反馈，修正 Mirage / Anubis 中几个容易被直译误导的报点。

## 修复内容

### Mirage

- `ninja -> 忍者位`
- `bench -> 沙发`
  - 不再推荐“长椅 / 长凳 / 板凳”。
  - 这里指 Mirage B 区包点附近的 Bench，中文 POV 字幕优先写“沙发”。
- `ladder / ladder room -> 黑屋`
  - 不再推荐“梯子房 / 梯子”。

### Anubis

- `stairs / water stairs / canal stairs -> 匪口`
  - 不使用“警口”。
  - 不推荐直译“楼梯 / 台阶”。

## 影响范围

- 只更新术语词典、prompt 约束、warning 校验和文档。
- 不改 demo 解析、语音提取、Whisper 转录、LLM 翻译主流程。
- 不改 `.bat` 主菜单结构。

## 使用建议

如果要制作 12 回合 Anubis 对比样片，建议使用 v0.8.5：

```powershell
cs2pov config set --transcription-profile quality

cs2pov run "你的anubis demo.dem.zst" `
  --output output_v085_anubis_12r `
  --map de_anubis `
  --team 2 `
  --max-rounds 12

cs2pov glossary check output_v085_anubis_12r
cs2pov export output_v085_anubis_12r --preset editing
```

重点检查：

```text
cave -> 黑屋
stairs -> 匪口
trade -> 补枪
push -> 前压 / 压
```
