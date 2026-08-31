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

现在不要求普通用户先 import 才能运行：新建 `run` 或向导 Job 会自动导入并复用
当前工作区中的 DemoAsset。新 Job 的 `input/` 不放 Demo；旧 Job 仍保留自己的
`input/`，不会自动迁移。

## 导入 Demo 后可以删除原文件吗？

可以。导入成功后，程序已经把持久源保存到当前工作区的
`library/demos/<asset_id>/`，外部原文件可以删除。不要手工删除或改写这个持久源。
`cache/decompressed_demos/` 是可重建缓存，删掉后下次需要 Demo 的阶段会自动恢复。

## 为什么换了工作区后 resume 找不到 Demo？

DemoAsset 属于导入它的工作区。受管 Job 切换到另一个没有该资产的工作区后，需要
Demo 的 resume 会提前失败并提示回到原工作区；程序不会从 Job/input 或其他目录猜
素材。只执行翻译、导出等不需要 Demo 的后段 resume 不会因此阻塞。

## `--output` 会把素材复制到外部目录吗？

不会。它只是旧版兼容选项，用来把新 Job 放到指定外部目录；素材仍归当前工作区，
外部 Job 的 `input/` 也不会出现 Demo 副本。

## 我担心 API key 泄露怎么办？

`manifest.json` 和反馈包会脱敏 API key。仍然建议上传反馈包前自己搜索一次 `sk-`。

## 词典功能什么时候做？

词典和“理解翻译”都很关键，但不属于 01E-A 素材库。当前素材管理完成的是可靠输入、去重、检查与缓存边界；人工复核案例库和理解翻译会在后续独立阶段实现。
