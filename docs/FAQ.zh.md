# 常见问题

## 我应该从哪里开始？

先双击 `Install_CS2_POV_Translator.bat`，安装完成后双击 `Start_CS2_POV_Translator.bat`，进入菜单后选择 `2. 启动前检查`。

## 哪个字幕文件导入剪映 / Premiere？

优先看 `final/`：

- `team_2.bilingual.srt`：双语对照。
- `team_2.zh.srt`：只中文字幕。

也可以运行：

```powershell
cs2pov explain-output output
```

## 程序失败了怎么办？

先运行：

```powershell
cs2pov inspect-job output
```

再根据提示选择：

```powershell
cs2pov resume output --from-stage translate
cs2pov feedback output
```

## 我担心 API key 泄露怎么办？

`manifest.json` 和反馈包会脱敏 API key。仍然建议上传反馈包前自己搜索一次 `sk-`。

## 词典功能什么时候做？

词典很关键，但它属于翻译质量增强，不是当前技术阻塞。当前优先级是让普通用户能安装、启动、理解输出和提交反馈。
