# v0.8.2 测试计划

v0.8.2 重点验证 Dust2 词典试点、样片流程文档、CLI/.bat 入口文案和现有 v0.8.x 功能无回归。

## 1. 基础测试

```powershell
pip install -e ".[all]"
pytest -q
```

预期：

```text
78 passed
```

如果测试数略有变化，以实际 pytest 结果为准，但不能有 failed。

## 2. 版本号检查

```powershell
python -c "import cs2pov; print(cs2pov.__version__)"
```

预期：

```text
0.8.2
```

检查：

```text
pyproject.toml
src/cs2pov/__init__.py
README.zh.md
Start_CS2_POV_Translator.bat
```

都应显示 v0.8.2。

## 3. Dust2 词典命令

```powershell
cs2pov glossary list --map de_dust2
cs2pov glossary list --map de_dust2 --scope map
cs2pov glossary list --map de_dust2 --scope global
cs2pov glossary list --map de_dust2 --scope map --json
```

预期：

```text
1. de_dust2 被识别为 supported map
2. map scope 中能看到 dust2_a_long / dust2_short / dust2_b_tunnels / dust2_xbox
3. global scope 中仍能看到 push / trade / awp / smoke 等通用术语
4. JSON 输出合法
```

## 4. setup-check 检查

```powershell
cs2pov setup-check
cs2pov setup-check --json
```

预期：

```text
地图术语词典试点包含 de_dust2 与 de_mirage
中文不乱码
API key 不显示明文
```

## 5. .bat 菜单检查

双击或运行：

```powershell
.\Start_CS2_POV_Translator.bat
```

检查：

```text
1. 顶部显示 v0.8.2
2. 主菜单 glossary 文案提到 Mirage/Dust2
3. glossary 子菜单可以查看 de_mirage
4. glossary 子菜单可以查看 de_dust2
5. 0 / q / back / 返回 可以回到主菜单
```

## 6. Dust2 真实 demo 小样测试，可选但推荐

如果本机有 Dust2 demo：

```powershell
cs2pov config set --transcription-profile quality
cs2pov run "D:\demos\dust2_sample.dem.zst" `
  --output output_v082_dust2 `
  --map de_dust2 `
  --team 2 `
  --max-rounds 3
```

然后检查：

```powershell
cs2pov glossary check output_v082_dust2
cs2pov export output_v082_dust2 --preset editing
```

重点看：

```text
final/team_*.bilingual.srt
artifacts/glossary_used.json
artifacts/glossary_warnings.json
```

希望看到：

```text
long -> A大
short / cat -> A小 / 小道
pit -> 大坑
tunnels -> B洞
xbox -> Xbox箱
trade -> 补枪
push -> 前压 / 压
```

## 7. 推广样片文档检查

确认文件存在：

```text
docs/GLOSSARY_DUST2_PILOT.zh.md
docs/SHOWCASE_SAMPLE_WORKFLOW.zh.md
```

并确认 README / docs/INDEX.zh.md 有链接。

## 8. 反馈包检查

如跑了真实 Dust2 job，请打反馈包：

```powershell
cs2pov feedback output_v082_dust2
```

反馈包不应包含：

```text
.dem
.dem.zst
.wav
.mp3
.mp4
API key
D:\ 本地绝对路径
C:\ 本地绝对路径
```

## 9. 通过标准

```text
1. pytest 通过
2. v0.8.2 版本号一致
3. de_dust2 词典可列出
4. setup-check / .bat 文案正确
5. 现有模型管理功能无回归
6. 真实 Dust2 小样如果执行，能生成字幕和 glossary 报告
```
