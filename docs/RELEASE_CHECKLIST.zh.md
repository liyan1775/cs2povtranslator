# 发布检查清单

每次打包给用户或发布 GitHub release 前，按此清单检查。

## 代码检查

```powershell
python scripts/check_repository_hygiene.py --root .
python -m pytest -q -p no:cacheprovider
python scripts/check_workspace_cli_e2e.py
python scripts/check_workspace_model_runtime_e2e.py
python scripts/check_workspace_job_runtime_e2e.py
python scripts/check_workspace_demo_asset_e2e.py
python scripts/check_workspace_pipeline_demo_asset_e2e.py
python -m compileall -q src tests scripts
python scripts/launch_sanity_check.py
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

创建标签前运行：

```powershell
python scripts/check_release_version.py "vX.Y.Z" --root .
```

标签必须指向已验收提交，禁止移动或覆盖已发布标签。

## 文档检查

- README.zh.md 是否说明当前版本定位。
- README.md 是否给英文用户入口。
- CHANGELOG.md 是否记录本版本。
- ROADMAP.md 是否说明下一步。
- docs/INSTALL_WINDOWS.zh.md 是否仍可用。
- docs/OUTPUT_FILES.zh.md 是否与当前输出一致。
- docs/FAQ.zh.md 是否覆盖常见问题。
- docs/SECURITY_AND_PRIVACY.zh.md 是否说明反馈包脱敏。
- DemoAsset 文档是否明确 `library/demos` 持久、解压 cache 可清、新 Job 不复制 Demo、旧 Job 不自动迁移。

## 真实 demo smoke

先初始化/选择工作区；默认 Job 写入当前工作区 `jobs/`。`--output` 仅应在
专门验证旧版外部输出兼容分支时显式使用，并确认警告与 manifest 标志。

```powershell
cs2pov workspace init "D:\cs2pov-workspace"
cs2pov run "D:\demos\match.dem.zst" `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 3 `
  --dry-run-translation
```

检查：

- `final/*.bilingual.srt` 存在。
- `progress.log` 完整。
- `manifest.json` 无 `sk-`。
- `cs2pov feedback` 生成反馈包。
- 反馈包不包含 demo/WAV/API key/绝对路径。

## 压缩包检查

发布压缩包不应包含：

- `.venv/`
- `output/`
- `jobs/`
- `*.dem` / `*.dem.zst`
- 工作区 `library/demos/`、`cache/decompressed_demos/` 或真实素材 manifest/hash
- `*.wav`
- `cs2pov_feedback_*.zip`
- 真实 API key

## GitHub 检查

- 批次分支已推送并通过 `.github/workflows/ci.yml` 的全部 Linux/Windows 任务。
- Pull Request 的 diff 只含本批次源码、测试、配置和文档。
- 不使用 force push 覆盖远程历史。
- 推送 `vX.Y.Z` 标签后，Release workflow 必须通过。
- GitHub Release 中 wheel、sdist 和 `SHA256SUMS.txt` 与该标签唯一对应。
- Release workflow 发现同标签 Release 已存在时必须失败，禁止自动覆盖既有资产。
- 原始 Demo、大型视频和硬件 E2E 原始素材默认不作为 Release 资产上传。
