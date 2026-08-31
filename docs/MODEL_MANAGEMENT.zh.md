# Whisper 模型管理

CS2 POV Translator 使用 `faster-whisper` 进行语音转录。模型通常来自 Hugging Face 缓存，Windows 用户很容易遇到 C 盘空间不足的问题。

v0.8.0 新增模型管理命令：

```powershell
cs2pov models info
cs2pov models list
cs2pov models recommend
cs2pov models test --model small --local-only
```

模型缓存跟随已选择的工作区。旧 `models set-cache`、`models test --cache-dir`
和 `config set --whisper-cache-dir` 已弃用，只返回迁移说明和非零退出码，不会创建目录或保存配置。

## 推荐档位

| 档位 | 模型 | 设备 | 适合场景 |
|---|---|---|---|
| fast | tiny | CPU | 快速验证流程 |
| balanced | base | CPU | 保守平衡默认 |
| quality | small | CPU | 办公本剪视频推荐 |
| medium_cpu | medium | CPU | 实验高质量，先短测 |
| cuda_quality | small | CUDA | NVIDIA 显卡用户 |

用户实测：办公本 CPU 使用 small 跑完整 demo 约 18 分钟，质量明显好于早期版本。

## 缓存目录

旧版本缓存只读列为迁移候选，不会自动移动、复制或删除。可运行
`python scripts/check_workspace_model_runtime_e2e.py` 验证隔离的真实子进程缓存绑定。

`run`、Job、Demo、临时音频及向导的工作区迁移仍属于 Luna-01D-B，尚未完成。
