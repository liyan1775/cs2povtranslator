# CS2 POV Translator v0.8.5

**CS2 POV Translator** 是一个本地优先的 CS2 POV 双语字幕工程工具。

它面向 CS2 视频作者、玩家和复盘使用者：读取 `.dem` / `.dem.zst`，提取队伍语音，使用 faster-whisper 转录，按回合组织上下文并调用 LLM 翻译，最终导出可导入剪映 / Premiere 的 SRT 字幕。

> 当前推荐形态：强引导 CLI + 菜单式 `.bat` 启动器。  
> 当前不优先：GUI、云端 SaaS、全地图词典、战术复盘。

---

## 现在能做什么

- 处理 CS2 / FACEIT demo：支持 `.dem` 和 `.dem.zst`。
- 提取队伍语音：按玩家、队伍和回合组织语音片段。
- 转录语音：通过 faster-whisper 支持 `tiny / base / small / medium` 等本地模型，并提供质量档位与模型管理。
- 按回合翻译：比逐句翻译更适合 CS2 队内语音。
- 导出双语字幕：默认推荐双语 SRT，纯中文/原文/debug 版本可选。
- 管理字幕工程：支持 `inspect-job / export / retranslate / resume / feedback`。
- 反馈包脱敏：不会打包原始 demo、WAV、大音频、API key 和本地绝对路径。
- 模型管理：查看 Hugging Face/Whisper 缓存目录、已下载模型、模型近似大小，并可把模型缓存放到 D 盘。
- Mirage / Dust2 / Anubis + 通用词典试点：`de_mirage`、`de_dust2`、`de_anubis` 报点和 push/trade/AWP 等通用术语可注入翻译 prompt，并输出 glossary 报告。

---

## 快速开始：普通用户

推荐在 Windows 上使用 `.bat`：

```text
Install_CS2_POV_Translator.bat
Start_CS2_POV_Translator.bat
```

首次使用建议顺序：

```text
1. 双击 Install_CS2_POV_Translator.bat 安装本地虚拟环境
2. 双击 Start_CS2_POV_Translator.bat 打开菜单
3. 先选择「启动前检查 setup-check」
4. 再选择「新建字幕工程」
5. 第一次建议只跑前 3 个含语音回合
```

---

## 快速开始：专家命令

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[all]"
pytest -q
cs2pov setup-check
cs2pov-wizard
```

处理一个 demo：

```powershell
cs2pov run "D:\demos\match.dem.zst" `
  --output output `
  --whisper-model tiny `
  --team 2 `
  --max-rounds 3 `
  --dry-run-translation
```

真实翻译前先配置 LLM：

```powershell
cs2pov config set `
  --base-url https://api.deepseek.com `
  --api-key sk-你的key `
  --model deepseek-v4-flash
```

---

## 常用命令

检查环境：

```powershell
cs2pov setup-check
cs2pov doctor
```

查看工程状态：

```powershell
cs2pov inspect-job output
```

解释输出文件：

```powershell
cs2pov explain-output output
```

重新导出字幕，不重新转录/翻译：

```powershell
cs2pov export output --preset editing
cs2pov export output --preset review
cs2pov export output --format bilingual
cs2pov export output --format zh_clean
```

重新翻译，不重新跑 Whisper：

```powershell
cs2pov retranslate output
cs2pov retranslate output --dry-run
```

从失败阶段恢复：

```powershell
cs2pov resume output --from-stage translate
cs2pov resume output --from-stage export_subtitles
```

打反馈包：

```powershell
cs2pov feedback output
```

查看词典：

```powershell
cs2pov models recommend
cs2pov models list
cs2pov models set-cache "D:\AIModels\huggingface"

cs2pov glossary list --map de_mirage --scope all
cs2pov glossary list --map de_dust2 --scope all
cs2pov glossary list --map de_anubis --scope all
cs2pov glossary check output
```

---

## 输出目录怎么理解

一个 Job 大致长这样：

```text
output/
  20260610_161929_de_mirage/
    final/       # 最推荐给剪辑软件使用
    review/      # 校对 ASR / 翻译用
    debug/       # 开发者排查用
    artifacts/   # resume / retranslate / export 依赖的中间产物
    manifest.json
    progress.log
    errors.log
```

最常用文件：

```text
final/team_2.bilingual.srt  # 首选双语字幕
final/team_2.compact.srt    # 紧凑双语字幕，适合剪辑
final/team_2.zh.srt         # 只中文，保留玩家名
```

---

## 当前路线图位置

```text
v0.1.x  Pipeline 主链路稳定 ✅
v0.2.x  强引导 CLI 产品化 ✅
v0.3.x  字幕工程工具化 ✅
v0.4.x  发布准备 / 普通用户可用性 ✅
v0.5.x  字幕格式与剪辑体验 ✅
v0.6.x  Mirage 词典试点机制 ✅
v0.7.x  GitHub 仓库落地 / 作品集发布整理 ✅
v0.8.x  模型管理 / 通用术语 / Dust2/Anubis 词典试点 ✅
```

下一阶段建议见 [ROADMAP.md](ROADMAP.md)。

---

## 文档入口

- [安装教程](docs/INSTALL_WINDOWS.zh.md)
- [输出文件说明](docs/OUTPUT_FILES.zh.md)
- [架构说明](docs/ARCHITECTURE.zh.md)
- [测试与反馈流程](docs/TESTING_GUIDE.zh.md)
- [隐私与安全说明](docs/SECURITY_AND_PRIVACY.zh.md)
- [Mirage 词典试点](docs/GLOSSARY_MIRAGE_PILOT.zh.md)
- [Dust2 词典试点](docs/GLOSSARY_DUST2_PILOT.zh.md)
- [Anubis 词典试点](docs/GLOSSARY_ANUBIS_PILOT.zh.md)
- [推广样片制作流程](docs/SHOWCASE_SAMPLE_WORKFLOW.zh.md)
- [发布检查清单](docs/RELEASE_CHECKLIST.zh.md)
- [路线图](ROADMAP.md)
- [更新日志](CHANGELOG.md)
- [贡献指南](CONTRIBUTING.md)

---

## 项目边界

当前项目是本地工具，不是云端 SaaS。默认不会上传 demo、语音或字幕。LLM 翻译阶段只会把待翻译文本发送到你配置的 API 服务；不配置 API key 时也能生成原文 / dry-run / 占位字幕。
