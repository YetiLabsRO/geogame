# Tower Rush design system — "old-world explorer"

Source of truth: Figma file `H3Q06F3tcrCNKO2MPYzrpC` (page **🧩 Components** `9:3`, screens on **Page 1** `0:1`).
Code home: `frontend/projects/shared/src/lib/theme/` (tokens) and `frontend/projects/shared/src/lib/ui/` (components).
This document is the hand-off contract used to port the Figma system to Angular; the Figma variables carry WEB
code syntax so every token below is used *verbatim* as a CSS custom property.

Aesthetic: parchment (light) / charcoal (dark), sienna brand, Playfair Display headings, Plus Jakarta Sans UI text,
pill buttons, thin line icons, warm low shadows. Bootstrap is used for **grid + utilities only** — no `btn`, `card`,
`navbar`, `form-control`, `progress`, `alert`, `modal`… in the player app.

## 1. Colour tokens (semantic, themed)

| Token | Light | Dark | Role |
|---|---|---|---|
| `--color-brand-primary` | `#974400` | `#ffb59c` | primary action fill, active nav, progress fill |
| `--color-brand-onSurface` | `#974400` | `#ffb59c` | brand-coloured text/icons on surfaces (eyebrows, secondary button labels) |
| `--color-brand-deep` | `#5a1b03` | `#5a1b03` | deep sienna (hero accents, pressed) |
| `--color-brand-tint` | `#9744000d` (rgba(151,68,0,.05)) | `#ffb59c1f` (rgba(255,181,156,.12)) | tinted fills (tinted button, chip brand, stat icon box) |
| `--color-text-onBrand` | `#ffffff` | `#5a1b03` | text on `brand-primary` |
| `--color-bg-canvas` | `#fcf9f2` | `#121416` | page background, top app bar |
| `--color-bg-raised` | `#ffffff` | `#1e2022` | cards, bottom nav, stat tiles |
| `--color-bg-inset` | `#ebe8e1` | `#333537` | wells, progress track, neutral/slate chips, avatar |
| `--color-bg-surface` | `#f1eee7` | `#1a1c1e` (derived) | secondary surface (icon gallery bg) |
| `--color-field-bg` | `#ffffff80` | `#33353780` | input background |
| `--color-text-primary` | `#321200` | `#e2e2e5` | headings, values |
| `--color-text-secondary` | `#564338` | `#d0c4bc` | body copy |
| `--color-text-muted` | `#56433899` (rgba(86,67,56,.6)) | `#6b7280` | eyebrow labels, inactive nav |
| `--color-text-placeholder` | `#5643384d` (rgba(86,67,56,.3)) | `#6b7280` | input placeholder |
| `--color-border-default` | `#8a726633` (rgba(138,114,102,.2)) | `#4d453f4d` | inputs, secondary button border |
| `--color-border-subtle` | `#8a72661a` (rgba(138,114,102,.1)) | `#4d453f4d` | card / nav hairlines |
| `--color-border-brand` | `#97440033` (rgba(151,68,0,.2)) | `#4d453f80` | tinted button / brand chip / avatar ring |
| `--color-accent-slate` | `#446279` | `#446279` | slate chip text, info accents |
| `--team-color` | *runtime* | *runtime* | set per TeamGroup on the element; never hard-code |

Status colours are not in the Figma set; derive them from the palette and keep them themed:
`--color-success` `#4e7a3a` / dark `#9ccb86`, `--color-danger` `#a33b2a` / dark `#ff9d8f`,
`--color-warning` `#c9812b` / dark `#f0b86a`, each with a matching `-tint` at ~12 % alpha.

Theme switching: Light values on `:root`; Dark under
`@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {…} }` **and** `:root[data-theme="dark"] {…}`.
`ThemeService` stores `system | light | dark` in `localStorage` (`tr.theme`) and stamps `data-theme` on `<html>`.

## 2. Scale tokens

| Token | Value |
|---|---|
| `--spacing-2xs` / `-xs` / `-sm` / `-md` / `-xl` | `4px` / `8px` / `12px` / `16px` / `24px` (add `--spacing-lg: 20px`, `--spacing-2xl: 32px`, `--spacing-3xl: 48px` for layout) |
| `--radius-md` / `-lg` / `-xl` / `-full` | `12px` / `16px` / `24px` / `9999px` |
| `--elevation-card` | `0 10px 20px -5px rgba(0,0,0,.08)` |
| `--elevation-brand-glow` | `0 10px 15px -3px rgba(151,68,0,.2), 0 4px 6px -4px rgba(151,68,0,.2)` |
| `--safe-top` / `--safe-bottom` | `env(safe-area-inset-top, 0px)` / `env(safe-area-inset-bottom, 0px)` |
| `--tap-min` | `44px` |

## 3. Typography

Fonts self-hosted via `@fontsource-variable/playfair-display` and `@fontsource-variable/plus-jakarta-sans`.
`--font-display: 'Playfair Display Variable', Georgia, serif;` `--font-ui: 'Plus Jakarta Sans Variable', system-ui, sans-serif;`

| Style | Family | Weight | Size / line | Tracking | Case | Use |
|---|---|---|---|---|---|---|
| Heading/H1 | display | 700 | 36 / 40 | -0.9px | – | screen title |
| Heading/H2 | display | 700 | 28 / 34 | -0.5px | – | hero title |
| Heading/Card Title | display | 700 | 24 / 32 | 0 | – | card title |
| Heading/H3 | display | 700 | 18 / 28 | 0 | – | section title, stat value, app-bar title |
| Button/Serif | display | 400 | 20 / 28 | 0 | – | primary button label |
| Body/Large | ui | 400 | 16 / 24 | 0 | – | inputs, lead text |
| Body/Medium | ui | 400 | 14 / 20 | 0 | – | body copy |
| Body/Italic | ui | 400 italic | 14 / 20 | 0.2px | – | challenge prompt quote |
| Button/Label | ui | 600 | 14 / 20 | 0.5px | UPPER | secondary/tinted button label |
| Label/Eyebrow | ui | 600 | 11 / 16.5 | 1.1px | UPPER | eyebrows, chips, stat labels |
| Label/Field | ui | 700 | 11 / 16.5 | 0.55px | UPPER | input floating label, meter row |
| Meta/Tiny | ui | 600 | 10 / 15 | 2px | UPPER | bottom nav labels |

Expose as `--text-h1-size/-line/-tracking` … or as SCSS mixins `@mixin text-h1` etc. (mixins preferred; keep the
font-family tokens as CSS variables).

## 4. Icons

16 line icons at 24×24, stroke 1.75, `currentColor` (already normalised in `shared/src/lib/ui/icons/*.svg`):
`chevron-left, arrow-right, compass, clock, star, camera, sparkle, lightbulb, bell, target, map, users, book,
id-card, castle, key`. `ui-icon` inlines them (`[name]`, `[size]` default 24) and inherits colour from the parent.
Bootstrap Icons (`bi bi-*`) stay available for the long tail; prefer `ui-icon` where a design icon exists.

## 5. Components (measurements from Figma)

**Button** `ui-button` — height 56, padding-inline 24, gap 8, radius `--radius-xl`, icon slot 20px on the right.
- `primary`: bg `brand-primary`, label Button/Serif in `text-onBrand`, shadow `--elevation-brand-glow`.
- `secondary`: transparent, 1.5px border `border-default`, label Button/Label in `brand-onSurface`.
- `tinted`: bg `brand-tint`, 1px border `border-brand`, label Button/Label in `brand-onSurface`.
- sizes `sm` (40, px 16, label 12/16) · `md` (48) · `lg` (56, default); `block` = width 100 %; `loading` swaps the icon
  slot for a spinner and disables; disabled = 45 % opacity; focus ring 2px `brand-primary` at 2px offset.

**Chip** `ui-chip` — padding 4×12, radius full, Label/Eyebrow.
- `brand`: bg `brand-tint` + 1px `border-brand`, text `brand-onSurface`. `solid`: bg `brand-primary`, text `text-onBrand`.
- `slate`: bg `bg-inset`, text `accent-slate`. `neutral`: bg `bg-inset`, text `text-muted`.
- `[teamColor]`: bg = `color-mix(in srgb, var(--team-color) 15%, transparent)`, 1px border + text in `--team-color`.

**Input** `ui-field` + `uiInput` — control height 52, radius `--radius-xl`, bg `field-bg`, 1px `border-default`,
padding-inline 16, gap 8, optional leading 18px icon, text Body/Large, placeholder `text-placeholder`.
Floating label: Label/Field in `brand-onSurface`, on a `bg-canvas` chip (padding-inline 6) positioned
top -9px / left 11px over the border. Focus: border `brand-primary`. Error: border + label `--color-danger`, help text
below in Body/Medium `text-secondary` or danger. Works for `<input>`, `<select>`, `<textarea>` (auto height).

**Card** `ui-card` — bg `bg-raised`, 1px `border-subtle`, radius `--radius-lg`, padding 24, column gap 12,
`--elevation-card`; optional `[title]` (Heading/Card Title, `text-primary`) then projected body (Body/Medium,
`text-secondary`). Variant `flat` (no shadow) and `padding="sm"` (16/18).

**StatTile** `ui-stat-tile` — bg `bg-raised`, 1px `border-subtle`, radius lg, padding 12×16, row gap 12;
icon box 40×40 radius md bg `brand-tint` with a 20px icon in `brand-onSurface`; column: label Label/Eyebrow
`text-muted` + value Heading/H3 `text-primary`. Inputs: `icon`, `label`, `value` (or projected).

**ProgressMeter** `ui-progress-meter` — column gap 8; header row Label/Field: left text `text-secondary`, right text
`brand-onSurface`; track height 8 radius full bg `bg-inset`; fill `brand-primary` (tone `team` uses `--team-color`,
`danger`/`success` use status colours). Inputs: `label`, `valueLabel`, `value`, `max`, `tone`.

**Avatar** `ui-avatar` — 56px circle (sizes 32/40/56), bg `bg-inset`, 1px `border-brand`; shows an image, initials
(Heading/H3) or the `users` icon at 26px in `brand-onSurface`; `[teamColor]` turns the ring into `--team-color`.

**TopAppBar** `ui-top-app-bar` — height 56 + `--safe-top` padding, bg `bg-canvas`, padding-inline 24;
left: 30px `brand-primary` circle with a 17px `compass` icon in `text-onBrand` (or a back `chevron-left` button when
`[back]`), title Heading/H3 in `brand-onSurface`; right: projected actions (22px icons, 44px tap area).

**BottomNav** `ui-bottom-nav` — height 78 + `--safe-bottom`, bg `bg-raised`, 1px top `border-subtle`,
padding 12 8 0; four equal tabs (column, gap 6, padding-block 8): 24px icon + Meta/Tiny label; active colour
`brand-onSurface`, inactive `text-muted`. Input `items: {label, icon, route, exact?}[]`; active when the URL starts
with `route` (exact for `/`).

**Toast** `ui-toast` + `ToastService.show(message, {tone, actionLabel})` — bottom-anchored above the nav, bg
`bg-raised`, border-subtle, radius lg, elevation card, Body/Medium; tones brand/success/danger/neutral (left 3px bar).

**EmptyState** `ui-empty-state` — centred column: 48px icon in `text-muted` inside a 96px `bg-inset` circle,
Heading/H3 title, Body/Medium `text-secondary`, optional projected action.

## 6. Screens (Page 1) — reference screenshots

Screenshots were exported to the session scratchpad `design/` folder during the port (Figma stays the source):
`01-welcome.png` (1:3), `02-city-discovery-map.png` (1:341), `03-your-society-team.png` (1:427),
`04-live-chronicle-scoreboard.png` (1:773), `05-login.png` (1:932), `06-great-library-menu.png` (1:1390),
`07-tower-challenge-dark.png` (21:97). The Tower Challenge (Trial) light screen (18:2) is fully specified:

- TopAppBar (session title, bell).
- Body: padding 24 (top 8), column gap 16.
- **Tower hero** 180px, radius lg, warm gradient `linear-gradient(142deg, #f3ece0 0%, #e7cca3 37%, #c99e73 67%)`
  with a 150px `castle` watermark (bottom-right, low opacity), a `brand` chip top-left ("ACTIVE TRIAL"), a `slate`
  chip bottom-left (zone name) and the tower name Heading/H2 bottom-right. Dark: gradient of `bg-inset → #3a2a20`.
- **Title block**: eyebrow Label/Eyebrow `brand-onSurface` ("TRIAL III · …") + Heading/H1 challenge title.
- **Meta stats**: two `ui-stat-tile` side by side (clock "Time left" → cooldown/distance; star "Reward" → points).
- **Challenge prompt** card (padding 18/20/20): row "YOUR TASK" eyebrow + 18px `sparkle` icon; Heading/H3
  challenge name; Body/Italic quoted prompt.
- **Answer** input with floating label "YOUR ANSWER" (or the photo capture control for photo challenges).
- **Actions**: primary block button "Submit Trial" (+ arrow-right) — disabled when out of range; secondary block
  button "Request a hint" (+ lightbulb). Cooldown replaces the primary button with a countdown stat.
- BottomNav.
