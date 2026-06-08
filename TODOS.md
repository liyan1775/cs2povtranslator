# TODOs

## Completed

- **D1: 创建 DESIGN.md** — DESIGN.md 已创建，含颜色 token、字体栈、间距、响应式断点、禁止模式。 **Completed:** v0.3.0 (2026-06-08)
- **D2: 交互状态表** — 7 功能 × 5 态已实现（加载/空/错误/成功/局部），glossary 和 preview 空状态含引导文案。 **Completed:** v0.3.0 (2026-06-08)
- **D3: 响应式断点策略 + a11y 清单** — DESIGN.md 定义 3 断点策略，Pico.css 原生 a11y 支持。 **Completed:** v0.3.0 (2026-06-08)
- **D5: Pico.css 品牌变量覆盖值** — 12 个自定义 CSS 属性覆盖在 base.html.j2 中定义。 **Completed:** v0.3.0 (2026-06-08)

## Pending

- **D4: Dust2 minimap 图片 + zone 坐标数据** — 延迟到 Phase 2（地图术语卡片浏览器需要 minimap 缩略图）。
  - **Priority:** P3
  - **Depends on:** Phase 2 地图术语浏览器

## ✅ D1: 创建 DESIGN.md

**Status:** 完成 (2026-06-08)
**What:** 创建项目设计规范文件，记录 CSS 变量系统、字体栈、间距体系、颜色 token。
**Result:** `DESIGN.md` 已创建，包含颜色 token、字体、间距、响应式断点、组件模式、禁止模式。

---

## ✅ D2: 交互状态表

**Status:** 完成 (2026-06-08)
**What:** 为 7 个 UI 功能定义交互状态表（加载/空/错误/成功/局部五态）。
**Result:** 所有模板已实现五态：
- 空状态有温暖提示语 + 下一步引导
- 错误状态使用 `[CS2TL-EX-NNNN]` 格式错误码
- 加载状态使用 `aria-busy="true"` 属性

---

## ✅ D3: 响应式断点策略 + a11y 清单

**Status:** 完成 (2026-06-08)
**What:** 定义 3 个关键页面的响应式断点行为和可访问性检查清单。
**Result:** 
- 断点: ≥1024px (桌面单栏 1400px)、768-1023px (平板全宽)、<768px (手机)
- a11y: 44px min touch target、focus-visible outlines、ARIA landmarks (role="tablist"/"log")
- 模态编辑在移动端全屏

---

## ⏳ D4: minimap 图片 + zone 坐标数据

**Status:** 延迟至 Phase 2（地图浏览器）
**What:** 获取 7 张地图的 minimap 图片资源，为每张地图的术语 zone 补充归一化坐标数据。
**Depends on:** 内置词典数据完成。

---

## ✅ D5: Pico.css 品牌变量覆盖值

**Status:** 完成 (2026-06-08)
**What:** 定义 Pico.css CSS 自定义属性覆盖值。
**Result:** 已实施 9 个覆盖变量（`--pico-primary`, `--pico-primary-hover`, `--pico-primary-focus`, `--pico-background-color`, `--pico-font-family`, `--pico-border-radius`, `--pico-form-element-spacing-*`, `--pico-nav-background-color`, `--pico-primary-inverse`）。禁止模式（无卡片、无渐变、无圆形图标）已遵守。
