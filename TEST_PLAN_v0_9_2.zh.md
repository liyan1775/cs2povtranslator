# CS2 POV Translator v0.9.2 测试计划

## 本版本重点

验证 `.bat` 和 launcher 是否真正变成一眼能看懂的 Comms Overlay 主流程入口。

## 1. 基础回归

```powershell
pytest -q
python -m compileall -q src tests
```

预期：全部通过，无语法错误。

## 2. 启动脚本检查

双击：

```text
Start_CS2_POV_Translator.bat
```

预期首页应显示：

```text
CS2 POV Translator v0.9.2
主功能：CS2 POV 通讯流 Overlay
```

不应再出现：

```text
v0.8.3 Release-ready local-first bilingual subtitle toolkit
v0.8.8 玩家识别与别名映射
新建字幕工程
13. Comms Overlay
```

## 3. 主菜单检查

预期主菜单只有核心 6 项：

```text
1. 新建 POV 通讯流工程
2. 渲染 Comms Overlay
3. 查看工程 / 输出说明
4. 打包反馈包
5. 启动前检查
6. 设置与高级工具
0. 退出
```

## 4. 高级工具检查

选择 6，应能看到模型、玩家别名、词典、SRT、重翻译、恢复、doctor、帮助等入口。

## 5. 真实工作流 smoke test

使用已有 Job：

```powershell
cs2pov comms build-review output --rounds 1 --team 2 --export-scope pov_team
cs2pov comms render output --rounds 1 --formats png,preview,green
```

预期：仍能生成 YAML、preview、green，不影响 v0.9.1 的 overlay 功能。

## 失败时请反馈

若 `.bat` 仍显示旧版本，请打包并截图：

- 当前文件夹路径
- `Start_CS2_POV_Translator.bat` 前 30 行内容
- `.venv\pyvenv.cfg`
- 终端完整输出
- `cs2pov feedback output` 生成的反馈包
