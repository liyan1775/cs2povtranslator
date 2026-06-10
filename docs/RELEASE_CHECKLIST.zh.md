# 发布检查清单

每次打包给用户或发布 GitHub release 前，按此清单检查。

## 代码检查

```powershell
pytest -q
python -m compileall -q src scripts
cs2pov --help
cs2pov setup-check
cs2pov doctor
```

## 版本号检查

确认这些地方一致：

- `pyproject.toml`
- `src/cs2pov/__init__.py`
- `README.zh.md`
- `Start_CS2_POV_Translator.bat`
- `Install_CS2_POV_Translator.bat`
- `cs2pov-wizard` banner
- `.bat` launcher banner

## 文档检查

- README.zh.md 是否说明当前版本定位。
- README.md 是否给英文用户入口。
- CHANGELOG.md 是否记录本版本。
- ROADMAP.md 是否说明下一步。
- docs/INSTALL_WINDOWS.zh.md 是否仍可用。
- docs/OUTPUT_FILES.zh.md 是否与当前输出一致。
- docs/FAQ.zh.md 是否覆盖常见问题。
- docs/SECURITY_AND_PRIVACY.zh.md 是否说明反馈包脱敏。

## 真实 demo smoke

```powershell
cs2pov run "D:\demos\match.dem.zst" `
  --output output_release_smoke `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 3 `
  --dry-run-translation
```

检查：

- `final/*.bilingual.srt` 存在。
- `progress.log` 完整。
- `manifest.json` 无 `sk-`。
- `cs2pov feedback output_release_smoke` 生成反馈包。
- 反馈包不包含 demo/WAV/API key/绝对路径。

## 压缩包检查

发布压缩包不应包含：

- `.venv/`
- `output/`
- `*.dem` / `*.dem.zst`
- `*.wav`
- `cs2pov_feedback_*.zip`
- 真实 API key
