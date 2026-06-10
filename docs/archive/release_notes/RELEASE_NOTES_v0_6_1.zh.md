# CS2 POV Translator v0.6.1 发布说明

## 版本定位

v0.6.1 是 v0.6.0 Mirage 词典试点版的小修版本。v0.6.0 的词典机制已经通过本地真实 demo 验证；v0.6.1 不扩展词条、不改变翻译策略，只修复反馈包和 manifest 中本地绝对路径暴露的问题。

## v0.6.0 反馈核查结论

已核查本地反馈包，主要结论可信：

- `57 passed`。
- `glossary list --map de_mirage` 正常，返回 22 条试点词条。
- 真实 Mirage demo 翻译流程成功。
- `glossary_used.json` 生成，显示 22 条词条注入 prompt，其中 4 条在转录文本中命中。
- `glossary_warnings.json` 生成，warning 数量为 0。
- 双语优先导出、`explain-output`、`.bat` 词典菜单未发现回归。
- API key 仍然脱敏。

## 修复内容

### 1. manifest artifact 路径改为可分享的 Job 内相对路径

v0.6.0 中部分 artifact 路径可能写成：

```text
D:\个人项目\cs2pov_arch_project\output_v060_glossary\20260610_161929_de_mirage\final\team_2.bilingual.srt
```

v0.6.1 写入公开 `manifest.json` 时会规范成：

```text
final/team_2.bilingual.srt
```

这样反馈包更适合分享，也更跨平台。

### 2. feedback 包自动脱敏本地绝对路径

`cs2pov feedback` 现在会对以下文件做路径脱敏：

- `manifest.json`
- `artifacts/demo_info.json`
- `README_FEEDBACK.txt`

例如原始 demo 路径会变成：

```text
[已隐藏-本地路径]/match.dem.zst
```

Job 内部文件仍保留相对路径，例如：

```text
final/team_2.bilingual.srt
artifacts/glossary_used.json
```

### 3. 新增回归测试

新增测试覆盖：

- public manifest 的 artifact 路径归一化。
- feedback 包中 manifest/demo_info/README 不泄露 `D:\...` 本地绝对路径。

## 未改动内容

v0.6.1 没有改变：

- Mirage 词条内容。
- prompt 注入策略。
- `glossary_used.json` / `glossary_warnings.json` 结构。
- Whisper/DeepSeek pipeline。
- 字幕时间策略。
- 双语优先导出策略。

## 开发侧验证

```text
59 passed
python -m compileall -q src scripts
python -m cs2pov --help
python -m cs2pov glossary list --map de_mirage
```
