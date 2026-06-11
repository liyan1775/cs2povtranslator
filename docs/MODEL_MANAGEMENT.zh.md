# Whisper 模型管理

CS2 POV Translator 使用 `faster-whisper` 进行语音转录。模型通常来自 Hugging Face 缓存，Windows 用户很容易遇到 C 盘空间不足的问题。

v0.8.0 新增模型管理命令：

```powershell
cs2pov models info
cs2pov models list
cs2pov models recommend
cs2pov models set-cache "D:\AIModels\huggingface"
cs2pov models test --model small --local-only
```

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

推荐将模型缓存放到 D 盘，例如：

```powershell
cs2pov models set-cache "D:\AIModels\huggingface"
```

这个设置是项目级配置，不会悄悄修改系统全局环境变量。
