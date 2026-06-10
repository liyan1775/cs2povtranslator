# v0.7.0 发布说明：GitHub 仓库落地 / 作品集发布整理版

v0.7.0 不新增 ASR、LLM、demo 解析或字幕时间策略。它的目标是把已经验证过的 CLI 工具整理成可以放到 GitHub 上展示、维护和发布的项目。

## 新增/更新

- 重写 `README.zh.md`，明确项目定位、快速开始、常用命令、输出目录和路线图。
- 新增英文 `README.md`，方便 GitHub 首页被非中文读者快速理解。
- 新增 `CHANGELOG.md`，整理 v0.1.x 到 v0.7.0 的版本演进。
- 新增 `ROADMAP.md`，说明下一阶段建议和暂缓事项。
- 新增 `CONTRIBUTING.md`，约束贡献方向、测试方式和词典贡献原则。
- 新增 `LICENSE` 与 `.gitignore`。
- 新增文档：
  - `docs/TESTING_GUIDE.zh.md`
  - `docs/SECURITY_AND_PRIVACY.zh.md`
  - `docs/RELEASE_CHECKLIST.zh.md`
  - `docs/DEVELOPMENT_WORKFLOW.zh.md`
  - `docs/SHOWCASE.zh.md`
- 扩展 `docs/ARCHITECTURE.zh.md`，把 Pipeline / Job / Manifest / Artifact / Adapter 讲清楚。
- 版本号更新到 `0.7.0`，`.bat` 和 CLI banner 同步。
- 新增仓库就绪度测试，确保关键文档和版本标记存在。

## 没有改动

- 没有改 Whisper / faster-whisper 调用逻辑。
- 没有改 DeepSeek / LLM 翻译逻辑。
- 没有改字幕 cue 时长策略。
- 没有新增地图词典。
- 没有新增 UI。

## 本版本目标

让项目从“压缩包迭代项目”进一步变成：

```text
别人打开 GitHub 仓库后，能理解它是什么、怎么安装、怎么测试、怎么反馈、架构为什么这样设计。
```

## 建议验收重点

- 文档是否清楚。
- 版本号是否一致。
- `.bat` 是否仍能进入菜单。
- 旧功能是否没有回归。
- release zip 是否不包含 output/demo/WAV/API key。
