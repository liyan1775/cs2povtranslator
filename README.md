# CS2 POV Translator (cs2tl)

将 CS2 Faceit 演示文件中的队伍语音通讯提取、转录、并用中文电竞术语翻译为 SRT 字幕文件。

## 快速开始

### 1. 安装

```bash
pip install cs2povtranslator
```

### 2. 初始化配置

```bash
cs2tl config init
```

### 3. 更新术语词典

```bash
cs2tl dictionary update
```

### 4. 翻译演示文件

```bash
cs2tl translate your_demo.dem --map de_dust2
```

### 5. 查看字幕

字幕文件在 `./subtitles/` 目录下：
- `your_demo.team_T.srt`（T阵营）
- `your_demo.team_CT.srt`（CT阵营）

导入剪映/PR 即可使用。

## 依赖

- [csgo-voice-extractor](https://github.com/akiver/csgo-voice-extractor) — Go 二进制，需手动安装并加入 PATH
- faster-whisper — 本地语音转录
- LLM API (OpenAI / Anthropic) — 术语感知翻译

运行 `cs2tl doctor` 检查所有依赖是否就绪。

## 命令行参考

```
cs2tl translate <demo.dem> [--map <map>] [--source auto] [--to zh]
    [--from <stage>] [--to-stage <stage>] [--no-dictionary]
    [--dry-run] [--verbose] [--quiet]

cs2tl dictionary update | list | show <map>
cs2tl config   init | show
cs2tl doctor
```

## 配置文件

```yaml
# ~/.cs2tl/config.yml
llm:
  provider: openai
  api_key: sk-...     # 或使用环境变量 OPENAI_API_KEY
  model: gpt-4o

whisper:
  model: base
  device: auto

dictionaries:
  repo_url: https://github.com/<user>/cs2-callout-dictionary
  auto_update: true
```

配置优先级：`--config` > `$CS2TL_CONFIG` > `./.cs2tl.yml` > `~/.cs2tl/config.yml`

## 词典

词典是一个独立的 Git 仓库，存放各地图的报点术语（中英文别名对照）。

---
Built with ♥ for the CS2 community.
