# CS2 POV Translator v0.5.0 测试计划

本版本重点测试字幕导出预设，不需要重新大规模测试 Whisper/DeepSeek。

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov doctor
cs2pov config show
```

预期：

```text
50 passed
API key 不显示明文
doctor/config show 中文不乱码
```

## 2. 复用已有 Job 测试导出预设

推荐使用 v0.4.1 或 v0.2.2 生成过的真实 Job：

```powershell
cs2pov export output --preset editing
cs2pov export output --preset review
cs2pov export output --preset debug
cs2pov export output --preset compact
```

预期：

```text
editing 生成 final/*.compact.srt / final/*.zh.srt / final/*.bilingual.srt
review 生成 final/*.bilingual.srt / review/*.original.srt / debug/*.debug.srt
debug 生成 debug/*.debug.srt / debug/*.voice_activity.srt / review/*.original.srt
compact 生成 final/*.compact.srt
```

## 3. 单独格式测试

```powershell
cs2pov export output --format compact
cs2pov export output --format zh_clean
cs2pov export output --format debug
```

重点检查：

```text
compact.srt 不应过长或大量重叠
zh_clean.srt 不应出现 [玩家名] 前缀
debug.srt 应出现 [R回合][T队伍][玩家名]
```

## 4. `.bat` 菜单测试

双击：

```text
Start_CS2_POV_Translator.bat
```

选择菜单 5 “重新导出字幕”。

重点确认：

```text
能看到 editing/review/debug/compact 的用途说明
能选择双语格式 label/arrow
能选择重叠策略 allow/shift/compact
输入 0/q/back/返回 能回主菜单
```

## 5. 输出解释测试

```powershell
cs2pov explain-output output
```

预期：

```text
能解释 compact / bilingual / zh / zh_clean / debug 各自用途
推荐 editing 作为剪辑安全导出
```

## 6. 反馈包

```powershell
cs2pov feedback output
```

预期：

```text
反馈包不包含 artifacts/voice
反馈包不包含 artifacts/temp_audio
反馈包不包含原始 demo
manifest.json 不出现 sk-
```
