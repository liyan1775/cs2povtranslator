# 版本化闭环开发工作流

本项目采用的协作节奏：

```text
讨论架构与边界
→ 实现一个明确版本
→ 给出 Release Notes 和 Test Plan
→ 本地真实环境测试
→ 打反馈包
→ 独立核查真实产物
→ 推送批次分支并等待 GitHub CI
→ 代码审查和用户验收
→ 小修或冻结
→ 进入下一阶段
```

## 核心原则

1. 不盲信本地 agent 报告，必须核查真实产物。
2. 小问题可以小修，但不要无限微调参数。
3. 每个版本都有明确主题。
4. 如果当前阶段目标已经达成，就冻结并进入下一阶段。
5. 真实 demo 验收优先于 mock 测试自嗨。
6. 日常改动从独立分支/worktree 开始，不直接在 `master` 上开发。
7. 不 force push，不把 Demo、音视频、模型、工作区、输出或密钥提交到 Git。
8. 每个已验收批次必须推送 GitHub；合入 `master` 前 CI 必须通过。

## 分支与自动化

- `master`：已验收、可定位、可回滚的主线。
- `feature/*`、`fix/*`、`chore/*`：单一目的的实施批次。
- `.github/workflows/ci.yml`：在 Linux/Python 3.11–3.13 和 Windows/Python 3.12 上运行仓库安全扫描、测试、编译和启动自检。
- `.github/workflows/release.yml`：只在推送 `v*.*.*` 标签时运行；核对标签与包版本、构建 wheel/sdist、生成 SHA-256 并同步 GitHub Release。
- `scripts/check_repository_hygiene.py`：本地提交前和 CI 中共同使用的敏感文件/大型资产守卫。
- `scripts/check_golden_baseline.py --replay`：校验金标准哈希并重放选定的 v0.9.8 行为测试。

金标准清单位于 `tests/golden/manifest.json`。CI 只重放可入库的确定性合成夹具；真实 Demo 和旧媒体文件保持在本地，只登记匿名 ID、SHA-256、大小和聚合预期，禁止记录绝对路径、SteamID 或秘密。

Playwright 浏览器 E2E 会在稳定本地 Web 主流程出现后加入同一 CI；阶段 0 不放置只会启动空页面的伪 E2E。

## 版本阶段示例

- v0.1.x：主链路稳定。
- v0.2.x：强引导 CLI。
- v0.3.x：字幕工程命令。
- v0.4.x：普通用户可用性。
- v0.5.x：字幕剪辑体验。
- v0.6.x：词典机制试点。
- v0.7.x：仓库落地与文档发布。

## 反馈包审阅重点

- SRT 是否真的符合预期。
- coverage 是否被正确解释。
- manifest 是否泄露 key 或路径。
- progress/errors 是否与报告一致。
- feedback zip 是否排除了大文件。
