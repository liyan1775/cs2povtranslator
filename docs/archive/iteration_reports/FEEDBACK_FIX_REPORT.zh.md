# v0.1.1 反馈修复报告

根据 `feedback_for_dev.zip` 做了第一轮真实环境反馈修复。

## 反馈结论

用户在 Windows 11 + Python 3.12 环境中成功跑通：

- `.dem.zst` 解压
- demo header / 地图 / 玩家识别
- 语音提取与 Opus 解码
- voice activity 构建
- round_start 回合边界解析
- faster-whisper tiny 转录
- 原文 / 双语占位 / 中文占位 / voice activity SRT 导出

这说明 v0.1 的核心 pipeline 方向成立。

## 本版修复

### 1. 修复 pyogg 依赖安装

`pyproject.toml` 中：

```toml
pyogg>=0.6
```

改为：

```toml
pyogg>=0.6.1a1
```

原因：PyPI 上 0.6.x 系列当前是 pre-release，pip 默认不会用 `>=0.6` 匹配 alpha 版本。

### 2. 修复 Windows `.bat` 乱码风险

新增并推荐：

```text
Start_CS2_POV_Translator.bat
```

批处理文件内容改成 ASCII-only，同时设置：

```bat
chcp 65001
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python -X utf8 ...
```

中文文件名的 `启动 CS2 POV Translator.bat` 也保留，但内容同步改为英文，减少 Windows cmd 编码问题。

### 3. 修复 Job 目录名 `unknown_map`

v0.1 在 inspect 前创建 Job，所以目录名是：

```text
20260609_200002_unknown_map
```

v0.1.1 会在 `inspect_demo` 识别到地图后，把自动创建的目录重命名为：

```text
20260609_200002_de_mirage
```

自定义 `job_id` 不会被自动改名。

### 4. 修正 parse_rounds 日志

原日志容易误解成“parser 失败所以降级”。现在改为：

- 开始：说明只有缺少 `round_start` 时才降级。
- 成功：显示 round 数量和来源，例如 `demoparser2:round_start`。
- winner_team 为空时：提示当前只用了 round_start，未来可接入 round_end / kill / bomb 事件增强。

### 5. 修复 `--max-rounds` 逻辑缺陷

v0.1 有一个重要问题：

```text
--max-rounds 1
```

会先构建第一个回合 context，但又把后续所有未分配转录追加成 `round_number=0` 的 orphan context。这样可能导致 LLM 仍然处理大量文本，违背限制初衷。

v0.1.1 改为：

- 设置 `max_rounds` 时，只构建前 N 个含语音的 round contexts。
- 不再把限制外的转录追加为 orphan context。
- 只有完整运行时，才保留真正无法归入任何回合的 orphan context。

### 6. 验收脚本增加提示

`run_acceptance.py` 现在会明确打印：

- `--max-rounds` 限制正在生效。
- `--skip-translation` 会让中文字幕使用原文占位。
- `--max-rounds 0` 表示不限制 round contexts。

### 7. 测试补充

新增/更新测试：

- `test_artifact_store.py`：验证 `unknown_map` 目录可重命名为地图名。
- `test_round_context.py`：验证 `max_rounds=1` 不会额外添加 orphan context。

当前纯单元测试：

```text
8 passed
```

## 建议下一轮真实验收

推荐优先测试：

```powershell
python scripts\run_acceptance.py `
  --demo "D:\agent_workspace\cs2demos\1-8d23f222-3071-4462-bbbc-28af7f2262eb-1-1.dem.zst" `
  --output output `
  --whisper-model tiny `
  --skip-translation `
  --max-rounds 1
```

重点检查：

1. job 目录是否变为 `*_de_mirage`。
2. `round_contexts.jsonl` 是否只有 1 个 context，而不是 2 个。
3. `.bat` 打开后是否不再乱码。
4. `progress.log` 的 parse_rounds 日志是否更清楚。

如果这轮通过，下一步就应该测试：

```powershell
cs2pov run ... --team 2 --dry-run-translation --max-rounds 1
```

用于验证“按队伍导出 + 按回合翻译回填”的主产品路径。
