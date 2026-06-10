# v0.7.0 测试计划

v0.7.0 是仓库整理版，重点测试文档、版本号和旧功能回归。不需要大规模重新跑真实 demo。

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov --help
cs2pov setup-check
cs2pov doctor
cs2pov config show
```

预期：

```text
pytest 通过
API key 不显示明文
setup-check / doctor 中文不乱码
```

## 2. 版本号检查

检查这些地方是否显示 v0.7.0：

```text
pyproject.toml
src/cs2pov/__init__.py
README.zh.md
Start_CS2_POV_Translator.bat
cs2pov-wizard banner
.bat launcher banner
```

## 3. 文档检查

确认以下文件存在且内容能读：

```text
README.zh.md
README.md
CHANGELOG.md
ROADMAP.md
CONTRIBUTING.md
LICENSE
docs/ARCHITECTURE.zh.md
docs/TESTING_GUIDE.zh.md
docs/SECURITY_AND_PRIVACY.zh.md
docs/RELEASE_CHECKLIST.zh.md
docs/DEVELOPMENT_WORKFLOW.zh.md
docs/SHOWCASE.zh.md
```

重点看：

- README 是否能让新用户理解项目。
- SECURITY 是否说明 API key / demo / feedback 脱敏。
- ROADMAP 是否没有过度承诺 UI / 全地图词典。
- CONTRIBUTING 是否提醒不要提交 demo/WAV/API key。

## 4. `.bat` 菜单回归

双击：

```text
Start_CS2_POV_Translator.bat
```

预期：

- 显示 v0.7.0。
- 主菜单仍有 setup-check / inspect / explain-output / export / retranslate / resume / feedback / glossary。
- 输入 `0/q/back/返回` 仍能从子菜单返回。

## 5. 复用已有 Job 的轻量回归

不需要重新跑完整 demo：

```powershell
cs2pov inspect-job output
cs2pov explain-output output
cs2pov export output --preset editing
cs2pov glossary check output
cs2pov feedback output
```

预期：

- `export` 能重新生成双语优先字幕。
- `feedback` 包不包含 demo/WAV/API key/本地绝对路径。
- `glossary check` 对 Mirage Job 能显示 glossary 报告。

## 6. 可选真实 demo smoke

如果想确认完整链路无回归：

```powershell
cs2pov run "D:\demos\match.dem.zst" `
  --output output_v070_smoke `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 3 `
  --dry-run-translation
```

这不是 v0.7.0 的必测项，因为本版本没有改 pipeline。
