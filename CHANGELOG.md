# Changelog

## v0.3.1 (2026-06-09)

### Added
- TSV 词典系统：每张地图独立 `.tsv` 文件（Tab 分隔），用记事本即可编辑
- `cs2tl dictionary edit <map>` — 用默认编辑器打开词典文件
- `cs2tl dictionary init` — 一键导出全部 7 张地图为 TSV 文件
- `cs2tl wizard` — 交互式翻译向导（4 步引导：环境检查 → 选文件 → 确认参数 → 执行）
- 时间戳对齐：Whisper WAV 时间戳自动修正为 demo 实际时间

### Changed
- SRT 输出格式改为 `[EN]` / `[中]` 双语对照标签
- `cs2tl dictionary list` 显示 TSV/内置来源
- `start-cs2tl.bat` 改为启动交互式向导（不再启动 Web 服务）

### Fixed
- `doctor.py` 移除已废弃的 csgove 检查和自动下载逻辑
- `doctor.py` 修复 Windows GBK 终端 Rich 渲染崩溃（自动 UTF-8 包装）
- `doctor.py` 修复 `*_()` 笔误为 `*()`
- `dict_update` 帮助文案更新为 TSV 操作指引

### Removed
- `doctor.py` 中 `_check_csgove()` 函数及交互式下载逻辑
- `DictionaryManager.load_all()` 中对旧 YAML 子目录的合并逻辑（改为 TSV 覆盖）
- `web/routes.py` 中重复的 `_align_transcriber_timestamps`（移至 `extractor.py`）

## v0.3.0 (2026-06-08)

### Added
- 存储路径迁移：默认 `./cs2tl-data/`，支持 `CS2TL_DATA_DIR` 环境变量覆盖，copy-then-verify 迁移旧数据
- Pico.css v2.1.1 内联替换手写 CSS，暗色主题 + CS2 品牌色覆盖
- 管线主页单栏渐进式布局 + `<dialog>` 模态编辑面板
- Rich 终端进度条（7 阶段：提取/转写/词典/回合/球员/翻译/字幕）
- 内置三语词典（俄/英/中），975 行 YAML，7 张服役地图术语库
- `CalloutTerm` 新增 `russian_aliases` 字段
- 词典页面卡片列表 + 客户端三语 substring 搜索
- `cs2tl doctor` 自动下载 csgove 二进制（OS/架构检测 + GitHub Releases）
- `DESIGN.md` 设计系统文档
- 交互状态表（7 功能 × 5 态：加载/空/错误/成功/局部）
- `doc/prompt.md` 实施指南（供新会话参考）

### Changed
- `dictionary.py` 删除 git clone/pull 逻辑，内置词典随 wheel 发布
- `config.py` 新增 `_find_project_root()`、`default_data_dir()`、`migrate_old_data()`
- `HF_HOME` 在 CLI 入口点设置（import faster_whisper 之前）
- 预览页预览/edit 交互改为 Team select + 模态对话框
- 词典「RAG」命名改为「术语增强 / CS2 术语库」

### Removed
- `cs2tl dictionary update` 命令（git pull 已移除）
- DictionaryManager 的全部 git 操作代码
- 300 行手写 CSS（替换为内联 Pico.css + 品牌覆盖）

### Tests
- 22 个新测试（russian_aliases、内置词典加载、config 路径解析、progress 模块）
- 总计 191 测试全部通过
