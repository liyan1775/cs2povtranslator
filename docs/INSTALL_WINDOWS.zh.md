# Windows 安装与首次启动

推荐新用户直接双击：

```text
Install_CS2_POV_Translator.bat
```

它会按顺序执行：

1. 检查 Python 是否可用。
2. 创建本地虚拟环境 `.venv`。
3. 安装依赖：`pip install -e ".[all]"`。
4. 运行 `cs2pov setup-check`，用普通用户能看懂的方式告诉你是否可以开始处理 demo。

安装完成后，双击：

```text
Start_CS2_POV_Translator.bat
```

第一次进入菜单后，建议先选：

```text
2. 启动前检查 setup-check
1. 新建字幕工程
```

## 手动安装方式

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
cs2pov setup-check
```

## 首次模型下载

faster-whisper 第一次使用某个模型时可能需要下载模型文件。`tiny` 最快，`base` 较稳，`small` 质量更好但更慢。办公本 CPU 推荐先用 `tiny` 跑前三个回合确认流程。
