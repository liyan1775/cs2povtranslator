# CS2 POV Translator — Design System

> 最后更新: 2026-06-08

---

## Color Tokens

| Token | Value | Usage |
|-------|-------|-------|
| `--pico-primary` | `#e94560` | CS2 accent red — buttons, links, active states |
| `--pico-primary-hover` | `#c03a50` | Button hover, focus ring |
| `--pico-primary-focus` | `rgba(233, 69, 96, 0.25)` | Focus ring glow |
| `--pico-primary-inverse` | `#ffffff` | Text on primary backgrounds |
| `--pico-background-color` | `#1a1a2e` | Page background |
| `--pico-color` | `#eaeaea` (implicit) | Primary text |
| `--pico-muted-color` | `#a0a0b0` | Secondary / muted text |
| `--pico-nav-background-color` | `#16213e` | Navigation bar |

## Typography

| Token | Value |
|-------|-------|
| Body | `'Microsoft YaHei UI', 'PingFang SC', 'Noto Sans SC', sans-serif` |
| Mono | `'Cascadia Code', 'Fira Code', 'Consolas', monospace` |
| Base size | 16px |
| Line height | 1.6 (Pico.css default) |

## Spacing Scale

| Name | Value |
|------|-------|
| `--pico-spacing` (sm) | ~8px |
| md | ~16px |
| lg | ~24px |
| xl | ~32px |

## Border Radius

| Name | Value |
|------|-------|
| `--pico-border-radius` (sm) | 4px |

## Component Patterns

### Navigation
- Top tab bar using `<nav class="tabs">` with `<ul>` + `<a>` elements
- Active tab: red underline (`--pico-primary`)
- Disabled tabs: 40% opacity, no pointer events
- Max width 1400px, centered

### Forms
- Pico.css form elements with custom border color `#2a2a4a`
- Min touch target 44px (Pico.css default)
- Focus ring: `--pico-primary` colored outline
- Upload zone: dashed border, hover highlights red

### Empty States
- Warm message + primary action + context
- **Never** show "No items found."
- Always include a suggested next step

### Errors
- Format: `[CS2TL-EX-NNNN]` structured error codes
- Three-part: Code + Cause + Fix
- Never expose raw stack traces

### Loading States
- Pico.css `aria-busy="true"` for indeterminate loading
- Rich progress bar (7-stage checklist) for pipeline
- HTMX `hx-indicator` for inline spinners

### Responsive Breakpoints

| Width | Layout |
|-------|--------|
| ≥1024px | Desktop: single column, max-width 1400px |
| 768–1023px | Tablet: full width, reduced spacing |
| <768px | Mobile: full-width, modal dialogs become full-screen panels |

## Forbidden Patterns

- ❌ Card grids (use semantic HTML, not `<article>` wrapper as default layout)
- ❌ Gradient backgrounds
- ❌ Circular icon decorations
- ❌ Emoji as design elements
- ❌ Centered-everything layouts

## CSS Architecture

- **Pico.css v2.x** — base design system, ~83KB inline in `base.html.j2`
- **Brand overrides** — ~50 lines of CSS custom properties after Pico.css
- **Component styles** — ~100 lines for app-specific components (chat messages, glossary cards, progress stages)
- **No CDN dependency** — Pico.css loaded from `pico.min.css` on disk, injected via Jinja2 global
