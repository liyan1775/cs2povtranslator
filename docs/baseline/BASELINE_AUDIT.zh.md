# CS2 POV Translator 可信源码基线审计

- 审计日期：2026-08-30
- 审计性质：只读比较；未修改旧源码、Demo、反馈包、发布包或历史 Job
- 用户确认的 canonical remote：<https://github.com/liyan1775/cs2povtranslator>
- canonical commit：`7f26212dc46b4a0a710ffef2fd69902f5e80bb5d`
- canonical tag：`v0.9.8`
- canonical branch：`master`

## 1. 结论

以 GitHub `master` 上带 `v0.9.8` 标签的提交作为唯一可信源码基线。

不要在原先混放源码、压缩包、反馈包、Demo、WAV、输出和密钥的目录中执行 `git init`。旧目录只作为历史材料和本地验收素材来源；新开发从干净 Git clone 和隔离 worktree 开始。

## 2. 候选源码

| 候选 | 版本 | Git 状态 | 测试结果 | 结论 |
|---|---:|---|---|---|
| 原工作目录外层源码 | 0.8.8 | 非 Git 仓库 | 101 项中 2 项失败 | 旧版本，不作为基线 |
| 原工作目录嵌套源码 | 0.9.2 | 非 Git 仓库 | 111 项通过 | 与 v0.9.2 发布包相符，但不是最新版 |
| `cs2pov_arch_project_v0_9_8.zip` | 0.9.8 | 发布快照 | 120 项通过 | 内容候选通过 |
| GitHub `master` / `v0.9.8` | 0.9.8 | 有完整历史和标签 | 120 项通过 | 选为 canonical source |

三个关键发布包的 SHA-256：

| 发布包 | SHA-256 |
|---|---|
| `cs2pov_arch_project_v0_8_8(1).zip` | `9A24786997B56F3A1565D70C37F539C4052EFF5A48BF1EAA4DA95A6EEBB4BAF7` |
| `cs2pov_arch_project_v0_9_2.zip` | `A3D30D37125002CEC66441E1783AF4B696D223C145364D68D9E71D416F77DA8E` |
| `cs2pov_arch_project_v0_9_8.zip` | `96215A51E80DC39F6B68D15A43B9434F04180084FF33AB331BF06813E20BF341` |

## 3. GitHub 与发布包一致性

GitHub `v0.9.8` 和解压后的 v0.9.8 发布包具有相同的 173 个非 Git 文件：

- 171 个文件在统一换行符后内容完全相同；
- `RELEASE_NOTES_v0_9_1.zh.md` 和 `TEST_PLAN_v0_9_1.zh.md` 仅有末尾空行差异；
- 没有 GitHub-only 或 release-only 文件；
- 因此应保留 GitHub 历史，而不是从 ZIP 重新初始化仓库。

## 4. 验证证据

在干净 clone 中使用 `.[dev,comms]` 依赖执行：

```text
120 tests collected
120 passed
launch_sanity_check.py exit 0
version: 0.9.8
source: canonical/src/cs2pov/__init__.py
```

隔离 worktree 创建后再次运行相同 120 项基线测试，结果仍全部通过。

## 5. 安全边界

审计确认远程当前提交和全部可达历史中：

- 没有名为 `apikey.txt` 或 `.env` 的历史提交；
- 没有发现形似真实 OpenAI/GitHub Token 的长 Token；
- 没有跟踪 Demo、WAV、视频、模型权重或大型生成物；
- 最大的已跟踪文件约 60 KiB。

原工作目录存在本地 `apikey.txt`，但没有读取其内容，也没有复制到 canonical clone。该文件不等于已发生远程泄露；后续仍应迁移至正式 SecretStore，并在确认历史使用情况后决定是否轮换。

## 6. 需要修复的基线问题

1. 原 `.gitignore` 没有明确排除 `apikey.txt`、workspace、模型、视频、压缩发布包等文件。
2. 仓库没有 GitHub Actions，测试通过依赖人工运行。
3. `RELEASE_NOTES_v0_9_6.zh.md` 和 `TEST_PLAN_v0_9_6.zh.md` 的标题误写为 v0.9.7；v0.9.5 只有 changelog 条目，没有独立发布说明和测试计划。
4. `config_store.py` 把 LLM API Key 明文保存在用户目录配置中。
5. Whisper 未显式配置时回退到用户主目录下的 Hugging Face 缓存，通常位于系统盘。
6. 词典数据硬编码在约 1050 行的 Python 模块中，不适合非程序员管理。
7. 回合翻译当前串行执行，没有并发上限、独立检查点或部分失败恢复。
8. 当前测试主要是单元/轻集成测试；真实浏览器 E2E 尚未建立。

这些问题按实施计划渐进解决，不在可信基线批次中顺便重写业务算法。

## 7. 可复用的旧分支资产

远程 `feature/user-friendly-dict-and-fixes` 与当前架构分叉较早，不能直接合并，但包含可作为行为参考的实现：

- TSV 词典覆盖和编辑命令；
- 内置七张地图词典；
- FastAPI、Jinja2、HTMX 风格本地 Web 流程；
- JobStore、任务进度、字幕预览、人工编辑、词典 CRUD 和设置页；
- 对应 dictionary、job store 和 web route 测试。

后续应复用需求和交互经验，不应把旧 `cs2tl` 包直接合并进当前 `cs2pov` 包。

## 8. 中文路径开发环境发现

在 `D:\个人项目\...` 下使用官方 CPython 3.12.3 创建虚拟环境并执行 editable install 时，Python 启动会因 `.pth` 文件被 CP936 解码而失败。证据链：

- Hatchling 生成的 `.pth` 是 UTF-8，内容为包含中文的源码路径；
- 官方 CPython 3.12.3 的 `site.py` 只按 locale 读取 `.pth`；
- 本机 Anaconda Python 3.12.4 的 `site.py` 先按 UTF-8 读取，再回退 locale；
- 用 Anaconda 3.12.4 重建同一路径虚拟环境后，editable install 和 120 项测试通过。

这属于 Python 运行时版本差异，不是项目源码或 Pillow 故障。当前本地 canonical 环境使用已验证的 Anaconda Python 3.12.4；CI 使用 GitHub Hosted Runner 的最新 Python 补丁版本。

## 9. 回滚与保留策略

- 原工作目录和发布包保持不变；
- `v0.9.8` 标签继续唯一定位原始基线提交；
- 新基础设施只在 `chore/phase-0-trusted-baseline` 分支提交；
- 禁止 force push；
- 若 CI 或审查发现问题，可直接放弃该分支，不影响 `master` 和旧材料。
