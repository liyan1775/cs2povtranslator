# v0.7.1 测试计划

v0.7.1 是 feedback 脱敏小修版，不需要重新跑完整 demo。重点测试 feedback 包中的 `progress.log` 是否还包含本地绝对路径。

## 1. 基础检查

```powershell
pip install -e ".[all]"
pytest -q
cs2pov --help
cs2pov doctor
```

预期：

```text
pytest 通过
CLI 正常显示 v0.7.1
API key 不显示明文
```

## 2. 用已有 Job 生成 feedback 包

```powershell
cs2pov feedback output
```

或者指定某个 Job：

```powershell
cs2pov feedback "output\20260610_141449_de_mirage"
```

## 3. 解压 feedback 包并检查

重点检查：

```text
progress.log
manifest.json
artifacts/demo_info.json
README_FEEDBACK.txt
```

不应该出现：

```text
D:\
C:\
/Users/
/home/
个人项目
agent_workspace
sk-
```

仍然应该保留有用的相对路径，例如：

```text
final/team_2.bilingual.srt
artifacts/glossary_used.json
```

## 4. 旧功能轻量回归

```powershell
cs2pov inspect-job output
cs2pov explain-output output
cs2pov export output --preset editing
cs2pov glossary check output
```

预期：旧功能无回归。
