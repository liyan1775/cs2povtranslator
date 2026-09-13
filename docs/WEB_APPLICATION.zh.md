# 本地管理界面（02E-1、02E-2）

02E-1 提供当前版本 Job 的本地只读管理界面和 JSON 查询接口。02E-2 增加按 Cue 组织的复核查询投影、只读复核页面和持久音频媒体预览。它们复用当前版本工作区、DemoAsset 和 Job 仓储，因此页面显示的阶段、运行状态、回合进度和诊断与文件系统中的 Job 保持一致。

## 启动

先安装项目及测试所需依赖：

```powershell
py -3.12 -m pip install -e ".[dev,comms]"
```

为避免在未选择工作区时写入系统目录，启动命令必须显式提供工作区绝对路径：

```powershell
cs2pov-web --workspace "D:\cs2pov-workspace"
```

默认地址为 `http://127.0.0.1:8765/`，服务默认只监听本机回环地址。页面打开后显示工作区健康状态和当前版本 Job 列表，列表会在手动刷新或每 3 秒自动刷新时重新读取仓储。

## 查询接口

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/v1/health` | 服务和工作区健康状态 |
| GET | `/api/v1/workspace` | 工作区诊断 |
| GET | `/api/v1/demos` | 当前工作区 DemoAsset 列表 |
| GET | `/api/v1/jobs` | 当前版本 Job 列表 |
| GET | `/api/v1/jobs/<job_id>` | Job 清单、来源、事件和诊断摘要 |
| GET | `/api/v1/jobs/<job_id>/events` | Job 事件日志 |
| GET | `/api/v1/jobs/<job_id>/rounds/<round_id>` | 回合、ASR、理解翻译和 Draft 数据 |
| GET | `/api/v1/jobs/<job_id>/rounds/<round_id>/review` | 按 Cue 汇总原始 ASR、理解翻译、依据和当前复核决定 |
| GET | `/api/v1/jobs/<job_id>/media/<media_id>` | 返回当前 Job 清单中登记的 WAV 音频，支持单字节范围请求 |

成功响应为 JSON；失败响应统一包含：

```json
{
  "ok": false,
  "error": {
    "code": "job_not_found",
    "message_zh": "找不到当前版本 Job。",
    "suggestion_zh": "请从 Job 列表重新选择。"
  }
}
```

Job 列表沿用仓储的确定性排序。损坏的当前版本 Job 会保留在列表中并显示诊断；没有 `repository.json` 的旧版目录不会被接口发现。回合查询按 Demo 微秒和稳定 Cue ID 排序，响应只包含领域允许的 ID、文本和时间数据，不包含 API Key、Demo 原始内容或工作区绝对路径。

复核页面地址为 `/jobs/<job_id>/rounds/<round_id>/review`。页面使用稳定的 `data-testid` 和 ARIA 文本状态，逐条展示时间、原始 ASR、解释、翻译、依据和复核状态；如果当前 Cue 有持久音频引用，页面会提供对应的音频控件并按 Cue 时间范围播放。页面当前不写入 Job。

## 当前边界

本版本用于验证框架可测试性和当前 Job 查询链路，已经提供只读复核和受控音频播放；仍暂不提供复核写入、任务启动/取消、模型 API 配置或字幕导出按钮。音频随当前 Job 写入 `voice/audio/`，并由 `voice/media.json` 清单登记；Web 只接受清单中的媒体 ID，不提供通用静态文件访问。后续子阶段会继续复用同一查询层和当前应用服务，并为写操作增加 writer claim、manifest CAS 和领域校验。
