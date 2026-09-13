# 02D-5 当前 Job 验收说明

本阶段验证当前 Job 的持久化流程与旧版字幕结果之间的兼容关系。验收脚本使用合成输入，
不会读取真实 Demo、不会调用线上模型，也不会要求 GPU 或 CS2 环境。

## 验收命令

```powershell
py -3.12 scripts/check_current_job_pipeline_e2e.py
py -3.12 scripts/check_current_job_output_equivalence.py
py -3.12 -m pytest -o addopts= tests/test_current_job_pipeline_e2e.py tests/test_current_job_output_equivalence_v1.py tests/test_translation_provider_boundary_v1.py -q
```

`check_current_job_pipeline_e2e.py` 会在独立 Python 子进程中依次创建 Job、重新打开语言
图、恢复 Draft、聚合当前语言数据并导出字幕。它检查整场和逐回合文件是否存在，以及文件
内容的 SHA-256 是否与 `FinalArtifactEntry` 一致。

`check_current_job_output_equivalence.py` 将旧版 v0.9.8 golden 的 cue、回合序号、玩家、
队伍、Demo 微秒、原文和译文转换为规范行，与当前 Draft 适配结果逐项比较，并逐字节比较
旧版双语 SRT。文件路径、目录布局和内部对象名称不属于兼容性字段。

## provider 边界

`OpenAICompatibleTranslationProvider` 在应用边界持有访问令牌；Job、任务请求、调用记录
和领域错误只保存 provider 类型、端点配置标识、模型名称及其他模型配置快照字段。超时
参数必须为 1 至 600 秒，并且从当前 Job 的配置快照读取。

网络与服务错误由翻译 worker 转换为稳定的任务错误：HTTP 429 和 5xx 属于可重试的
`provider_busy`，网络故障属于可重试的 `provider_unavailable`，401、403、404 属于不
可重试的配置错误，非法 JSON 属于不可重试的返回格式错误。自动化测试使用 fake client
覆盖这些分类，不输出密钥或原始异常细节。

真实账号额度、线上限流、模型翻译质量、真实 Demo 解析、视频成片和旧 Job 自动迁移不在
本阶段自动门禁内，应在目标部署环境执行受控 smoke。
