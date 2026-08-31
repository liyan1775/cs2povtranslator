# 常见问题

## 我应该从哪里开始？

先双击 `Install_CS2_POV_Translator.bat`，安装完成后双击 `Start_CS2_POV_Translator.bat`，进入菜单后选择 `2. 启动前检查`。

## 哪个字幕文件导入剪映 / Premiere？

优先看 `final/`：

- `team_2.bilingual.srt`：双语对照。
- `team_2.zh.srt`：只中文字幕。

也可以在已选择工作区后运行（路径可省略）：

```powershell
cs2pov explain-output
```

## 程序失败了怎么办？

先运行：

```powershell
cs2pov inspect-job
```

再根据提示选择：

```powershell
cs2pov resume --from-stage translate
cs2pov feedback
```

## Demo 素材怎么管理？缓存能删吗？

先选择健康工作区，然后运行：

```powershell
cs2pov demos import "D:\demos\match.dem.zst"
cs2pov demos list
cs2pov demos inspect <素材ID>
```

`library/demos/<asset_id>/` 是持久素材，不要手工删除或改写；
`cache/decompressed_demos/` 是可重建缓存，可以在程序未运行时清理。
`demos inspect` 本身不会修复或写文件；再次 import 才会按需重建缓存。

目前不要求普通用户先 import 才能运行。01E-A 尚未把素材库自动接入 Pipeline，
现有 Job 仍有自己的 `input/` 副本，自动引用会在 01E-B 实现。

## 我担心 API key 泄露怎么办？

`manifest.json` 和反馈包会脱敏 API key。仍然建议上传反馈包前自己搜索一次 `sk-`。

## 词典功能什么时候做？

词典和“理解翻译”都很关键，但不属于 01E-A 素材库。当前素材管理完成的是可靠输入、去重、检查与缓存边界；人工复核案例库和理解翻译会在后续独立阶段实现。
