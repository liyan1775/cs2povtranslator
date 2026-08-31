# CS2 POV Translator v0.9.8

**CS2 POV Translator** 是一个本地优先的 CS2 POV 队内通讯理解与双语字幕工程工具。

它面向 CS2 视频作者、玩家和复盘使用者：读取 `.dem` / `.dem.zst`，提取队伍语音，使用 faster-whisper 转录，按回合组织上下文并调用 LLM 翻译，最终导出可导入剪映 / Premiere 的 SRT 字幕，以及可在剪映中叠加到 POV 画面上的按回合双语 Comms Overlay 通讯流素材。

> 当前推荐形态：强引导 CLI + 菜单式 `.bat` 启动器。  
> 当前不优先：GUI、云端 SaaS、全地图词典、战术复盘。

---

## 现在能做什么

- 处理 CS2 / FACEIT demo：支持 `.dem` 和 `.dem.zst`。
- 提取队伍语音：按玩家、队伍和回合组织语音片段。
- 转录语音：通过 faster-whisper 支持 `tiny / base / small / medium` 等本地模型，并提供质量档位与模型管理。
- 按回合翻译：比逐句翻译更适合 CS2 队内语音。
- 生成 Comms Overlay：v0.9.8 起这是默认主功能；按回合导出可人工校对的 `review/comms_rounds/round_XX.yaml`，再渲染右侧贴边的半透明双语浮动卡片素材，方便放入剪映叠到 POV 视频上。
- 导出双语字幕：SRT 作为可选剪辑资产保留，纯中文/原文/debug 版本可选；v0.8.8 起剪辑预设采用 stack：同屏最多2条字幕，第三条替代最早条，避免半屏大段字幕。
- 管理字幕工程：支持 `inspect-job / players / export / retranslate / resume / feedback`。
- 反馈包脱敏：不会打包原始 demo、WAV、大音频、API key 和本地绝对路径。
- 玩家识别：用 K-D-A、语音时长和队伍帮助确认职业选手小号/临时昵称，并可设置 `Ebule -> donk` 这样的字幕显示名。
- 模型管理：查看 Hugging Face/Whisper 缓存目录、已下载模型、模型近似大小，并可把模型缓存放到 D 盘。
- Mirage / Dust2 / Anubis + 通用词典试点：`de_mirage`、`de_dust2`、`de_anubis` 报点和 push/trade/AWP 等通用术语可注入翻译 prompt，并输出 glossary 报告。

---

## 快速开始：普通用户

推荐在 Windows 上使用 `.bat`。v0.9.8 起请先确认你是在**全新 clean-room 目录**里启动，不要把新版覆盖解压到旧项目目录。v0.9.8 的 .bat 文件保持 ASCII-only，中文菜单由 Python 输出，以避免中文 Windows 的 GBK/UTF-8 批处理乱码问题。

```text
README_FIRST_READ_ME_FIRST.txt
Install_CS2_POV_Translator.bat
START_HERE_DOUBLE_CLICK.bat
Start_CS2_POV_Translator.bat
```

首次使用建议顺序：

```text
1. 把 zip 解压到全新目录，例如 cs2pov_arch_project_v0_9_8
2. 打开 README_FIRST_READ_ME_FIRST.txt，确认没有打开旧目录
3. 双击 Install_CS2_POV_Translator.bat 安装本地虚拟环境
4. 双击 START_HERE_DOUBLE_CLICK.bat 或 Start_CS2_POV_Translator.bat 打开菜单
5. 启动页应显示 CS2 POV Translator v0.9.8 和当前运行目录
6. 先选择「启动前检查 setup-check」
7. 再选择「新建 POV 通讯流工程」
8. 第一次建议只跑前 3 个含语音回合
9. 工程完成后会自动生成 `review/comms_rounds/round_XX.yaml` 与 `final/comms_feed/`
10. 人工校对 YAML 后，在主菜单选择「2. 渲染 Comms Overlay」渲染剪映 overlay
```

如果启动后看到 v0.8.x / v0.9.1 / v0.9.2 文案，几乎一定是打开了旧目录或旧快捷方式。请关闭窗口，回到新解压的 v0.9.8 文件夹再启动。

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

01D-A/01D-B 的工作区 runtime 已接入默认流程。先初始化或选择工作区，
再运行 demo；正常 Job 自动写入当前工作区的 `jobs/`，模型缓存和临时音频
也跟随该工作区：

```powershell
cs2pov workspace init "D:\cs2pov-workspace"
cs2pov run "D:\demos\match.dem.zst"
```

普通用户不需要选择输出根。`--output` 只用于显式的旧版外部输出兼容模式，
会显示警告；它不会自动迁移已有 Job。旧 Job 可以原地查看和修改，但任何
写操作都要求当前工作区健康。

处理一个 demo：

```powershell
cs2pov run "D:\demos\match.dem.zst" `
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
cs2pov inspect-job
```

解释输出文件：

```powershell
cs2pov explain-output
```

确认玩家身份并设置字幕显示名：

```powershell
cs2pov players list
cs2pov players alias --name Ebule --as donk
cs2pov export --preset editing
```

重新导出字幕，不重新转录/翻译：

```powershell
cs2pov export --preset editing
cs2pov export --preset review
cs2pov export --format bilingual
cs2pov export --format zh_clean
```

生成按回合 Comms Overlay 通讯流素材：

```powershell
# 1. 先从已有 Job 的翻译结果生成可编辑中间产物
#    POV 通常只需要某一队 5 个人，建议显式写 --team 2/3。
cs2pov comms build-review --rounds 1-3 --team 2 --export-scope pov_team

# 2. 人工检查/修改 review/comms_rounds/round_XX.yaml

# 3. 只渲染指定回合的剪映素材
#    v0.9.8 默认：右侧贴边、无大面板、浮动消息卡片、轻量淡入。
cs2pov comms render --rounds 1-3 --formats preview,green

# 可选：同时尝试透明通道 MOV，需本地测试剪映兼容性
cs2pov comms render --rounds 1 --formats preview,green,alpha

# 如果想回到 v0.9.0 的大外层面板，可加：--classic-panel
```

重新翻译，不重新跑 Whisper：

```powershell
cs2pov retranslate
cs2pov retranslate --dry-run
```

从失败阶段恢复：

```powershell
cs2pov resume --from-stage translate
cs2pov resume --from-stage export_subtitles
```

打反馈包：

```powershell
cs2pov feedback
```

查看词典：

```powershell
cs2pov models recommend
cs2pov models list

cs2pov glossary list --map de_mirage --scope all
cs2pov glossary list --map de_dust2 --scope all
cs2pov glossary list --map de_anubis --scope all
cs2pov glossary check
```

---

## 输出目录怎么理解

一个 Job 大致长这样：

```text
jobs/
  20260610_161929_de_mirage/
    final/       # 最推荐给剪辑软件使用：SRT、Comms Feed、overlay 素材
    review/      # 校对 ASR / 翻译 / Comms YAML 用
    debug/       # 开发者排查用
    artifacts/   # resume / retranslate / export / comms 依赖的中间产物
    manifest.json
    progress.log
    errors.log
```

最常用文件：

```text
final/team_2.bilingual.srt                 # 首选双语字幕
final/team_2.compact.srt                   # 紧凑双语字幕，适合剪辑
final/team_2.zh.srt                        # 只中文，保留玩家名
final/comms_feed/comms_feed.html           # 静态通讯流报告
review/comms_rounds/round_01.yaml          # 可人工修改的回合通讯流
final/comms_overlay/round_01_overlay_green.mp4    # 绿幕兜底 overlay
final/comms_overlay/round_01_overlay_preview.mp4  # 排版/错字预览
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
v0.9.x  Comms Overlay：按回合通讯流、人工校对中间产物、剪映 overlay 素材 🚧
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

### v0.9.8：默认不展示回合倒计时

不同平台、不同 demo，甚至同一平台的不同回合，准备/冻结时间都可能不一致；而 POV 视频作者剪辑后的素材也不一定保留 demo 内部的精确回合边界。因此 v0.9.8 默认不再把 `1:55` / `准备 0:03` 这类时间展示到画面上，只显示 `Round + 选手 + 中文 + 原文`。

内部仍保留 `show_at_seconds`，用于控制每条通讯在 overlay 第几秒出现。需要实验显示时间时可以手动打开：

```powershell
cs2pov comms render --rounds 1 --time-display elapsed
cs2pov comms render --rounds 1 --time-display round-clock --freeze-seconds 5
```
