# Theme: Modern Outdoors / Topographic

This is the shared visual theme for both SPAs (`player`, `staff`). It themes stock
Bootstrap 5.3 rather than rewriting components — existing `btn`/`card`/`badge`/`alert`/
`navbar`/`form-control` markup gets the new look for free.

Source of truth: `frontend/projects/shared/src/lib/theme/`
- `_bootstrap-overrides.scss` — the palette (light + dark), as plain `$variable`s. This is
  the **only** place the hex/rgba values are written. Don't hardcode colors elsewhere —
  reference these variables (from SCSS) or the CSS custom properties below (from
  component styles).
- `_tokens.scss` — emits the `:root { --... }` / `[data-bs-theme="dark"] { --... }` custom
  property layer, self-hosts Inter (`@fontsource-variable/inter`), and provides the
  `.topo-bg`, `.tabular-nums`, and focus-visible-ring utilities.

## How it's wired up

Bootstrap is compiled from **SCSS source**, not the precompiled
`bootstrap.min.css`. Each app's `styles.scss`
(`frontend/projects/{player,staff}/src/styles.scss`) does, in order:

1. `@use '../../shared/src/lib/theme/bootstrap-overrides' as palette;`
2. `@use 'bootstrap/scss/bootstrap' with (...)` — feeds the palette into Bootstrap's own
   configurable `!default` variables ($primary, $body-bg, $border-radius,
   $font-family-base, the `*-dark` counterparts for dark mode, etc).
3. `@use '../../shared/src/lib/theme/tokens' with ($radius: ..., $radius-sm: ...,
   $radius-lg: ...)` — emits the custom-property token layer on top.

`frontend/angular.json`'s `styles` arrays no longer include
`node_modules/bootstrap/dist/css/bootstrap.min.css` (both `player` and `staff` build
targets) — only `bootstrap-icons.css`, `leaflet.css`, and the app's own `styles.scss`,
which now pulls in Bootstrap itself via `@use`. `stylePreprocessorOptions.includePaths:
["node_modules"]` was added so bare `@use 'bootstrap/scss/bootstrap'` /
`@use '@fontsource-variable/inter'` specifiers resolve.

**Staff is denser, player is more comfortable** — the only difference between the two
apps' `styles.scss` files is the radius/control-padding values passed into the two
`@use ... with (...)` calls:

| | player | staff |
|---|---|---|
| `--radius` | 10px | 8px |
| `--radius-sm` | 8px | 6px |
| `--radius-lg` | 14px | 12px |
| control padding | Bootstrap default (`.375rem .75rem`) | tighter (`.3rem .6rem`) |
| card padding | Bootstrap default | tighter (`.75rem`) |

## Token list

All tokens live under `:root` (light, default) and are re-declared under
`[data-bs-theme="dark"]`. Toggle dark mode the normal Bootstrap 5.3 way — set
`data-bs-theme="dark"` on `<html>` (or any ancestor).

### Color

| token | light | dark |
|---|---|---|
| `--bg` | `#F6F7F4` | `#10151A` |
| `--panel` | `#FFFFFF` | `#171F26` |
| `--panel-sunken` | `#EDF1EC` | `#1E2831` |
| `--ink` | `#1E2A32` | `#E6EDF0` |
| `--ink-muted` | `#5A6B73` | `#9AAAB3` |
| `--border` | `rgba(30,42,50,.12)` | `rgba(230,237,240,.14)` |
| `--primary` (trail green) | `#2F7A4F` | `#4BA574` |
| `--primary-strong` | `#256440` | `#4BA574` |
| `--secondary` (stone) | `#55636B` | `#55636B` (unchanged — stays vivid) |
| `--info` / `--accent` (lake blue) | `#2C74B3` | `#5AA0DE` |
| `--success` | `#379A5B` | `#379A5B` (unchanged — stays vivid) |
| `--warning` (blaze) | `#E07B39` | `#E8935A` |
| `--danger` (clay) | `#C0453B` | `#E06A5F` |
| `--focus` | primary @ 35% alpha | dark primary @ 35% alpha |
| `--team-color` | **runtime slot, always starts `transparent`** | same |

`--team-color` is intentionally empty — each `Game` defines its own team colors at
runtime. Set it inline where a team's color is known
(`[style.--team-color]="team.color"`) and reference `var(--team-color)` in CSS. Never
hardcode a team color in a stylesheet.

### Spacing

`--space-1` … `--space-7` = `4 / 8 / 12 / 16 / 24 / 32 / 48` px.

### Radius

`--radius`, `--radius-sm`, `--radius-lg` — see the player/staff table above. (The spec
only pinned `--radius`/`--radius-sm` explicitly; `--radius-lg` is a proportional
extrapolation: player 14px, staff 12px.)

### Shadows (soft cool-gray, same in both modes)

- `--shadow-1: 0 1px 2px rgba(16,24,32,.06)`
- `--shadow-2: 0 2px 8px rgba(16,24,32,.08)`
- `--shadow-3: 0 8px 24px rgba(16,24,32,.12)`

### Type scale (px)

`--text-xs` `--text-sm` `--text-base` `--text-md` `--text-lg` `--text-xl` `--text-2xl`
`--text-3xl` = `12 / 13 / 14 / 16 / 18 / 22 / 28 / 36`. `--text-base` (14px) is also fed
into Bootstrap as `$font-size-base: 0.875rem`, so `<body>` renders at 14px by default.

Headings get `$headings-font-weight: 650` (via Bootstrap) and `letter-spacing: -0.01em`
(no Bootstrap variable for this, so it's a plain rule in `_tokens.scss` targeting
`h1`–`h6` / `.h1`–`.h6`).

### Font

Inter, self-hosted via `@fontsource-variable/inter` (imported inside `_tokens.scss`, no
runtime CDN — works fully offline). `$font-family-base` is set to `'Inter Variable',
system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif`.

### Utilities

- `.tabular-nums` — `font-variant-numeric: tabular-nums`. Use on scoreboard/data table
  cells so digits line up.
- `.topo-bg` — faint concentric-contour-line SVG background (tan/green, low opacity),
  theme-aware (the pattern itself swaps to a slightly brighter variant in dark mode via
  `--topo-bg`). Good for page headers, empty states, hero areas. `app-page-header`
  exposes it as a `topoBg` input.
- Focus-visible ring — plain interactive elements get a `2px solid var(--focus)` outline
  on `:focus-visible`. Bootstrap's own form controls/buttons already render a themed
  box-shadow ring (`$focus-ring-color`, same palette), so the outline is suppressed
  there to avoid a doubled-up ring.

## Dark mode — what does and doesn't follow automatically

Bootstrap 5.3's dark mode is **not** a single global remap; it's driven by a parallel
set of `$*-dark` variables (`$body-bg-dark`, `$border-color-dark`,
`$body-secondary-bg-dark`, `$link-color-dark`, …) that each app's `styles.scss` also
configures from the palette. That covers every component that reads `var(--bs-body-bg)`
/ `var(--bs-border-color)` / etc. directly — cards, dropdowns, modals, popovers,
list-groups, tables, forms.

Bootstrap intentionally keeps `$primary`/`$success`/`$danger`/etc. **constant** across
color modes (only their "subtle" text/bg/border variants auto-adjust). Since the spec
wants `--primary`/`--info`/`--warning`/`--danger` to actually shift in dark mode,
`_tokens.scss` additionally overrides Bootstrap's own `--bs-primary` /
`--bs-primary-rgb` / etc. (and `--bs-focus-ring-color`) inside `[data-bs-theme="dark"]`.
This reaches everything that reads those CSS custom properties directly — links,
`.text-primary`/`.border-primary`/`.bg-primary` utilities, form checks, the focus ring.

**Caveat a reviewer should know:** Bootstrap's *compiled* color variants — `.btn-primary`,
`.badge.text-bg-primary`, `.alert-primary` — bake a shade of the **light** color into
their own local `--bs-btn-bg`/etc. custom properties at build time (via the
`button-variant`/`badge`/`alert-variant` mixins) and do not read `--bs-primary` at
runtime. They will not shift to the dark-mode hex in dark mode. In practice they stay
legible and reasonably vivid on the dark background regardless (that's also Bootstrap's
own default behavior for stock theme colors). Getting exact per-component hex parity in
dark mode would require compiling Bootstrap's component partials a second time with a
dark `$theme-colors` map — out of scope for this foundation layer.

## Shared UI primitives

`frontend/projects/shared/src/lib/ui/`, all exported from `shared` (the library's
`public-api.ts`) — standalone, `OnPush`, signals, `inject()`. Bootstrap classes +
tokens + bootstrap-icons only, no other dependencies.

### `InfoHintComponent` (`app-info-hint`)

Inline "ⓘ" icon button. Shows its text on hover **and** on click/tap (touch-friendly).
Esc or an outside click closes it.

```html
<app-info-hint text="Only captains can invite new members." />
<!-- or richer projected content: -->
<app-info-hint><strong>Note:</strong> this can't be undone.</app-info-hint>
```

Inputs: `text?: string`, `ariaLabel?: string` (default `"More information"`).

Replaces the old hover-only `title="..."` pattern — swap those over as you touch each
component (not done automatically by this change; see the task's scope note).

### `FieldRowComponent` (`app-field-row`)

Form-field wrapper: label + optional required marker + optional `InfoHint` (pass
`hint`) + projected control + optional help line + optional error text.

```html
<app-field-row label="Team name" hint="Shown to other captains." required [error]="nameError()">
  <input class="form-control" id="team-name" [formControl]="nameControl" />
</app-field-row>

<app-field-row label="Notes" [help]="'Visible to staff only.'" layout="horizontal">
  <textarea class="form-control" [formControl]="notesControl"></textarea>
</app-field-row>
```

Inputs: `label` (required), `hint?`, `required?` (default `false`), `error?`, `help?`,
`for?` (id — wire it to your control's `id` so the `<label>` is properly associated),
`layout?: 'stacked' | 'horizontal'` (default `'stacked'`; `'horizontal'` puts the label
left of the control from `640px` up, and still stacks below that).

### `ConfirmService` + `ConfirmDialogComponent` (`app-confirm-dialog`)

Themed replacement for the native `confirm()`. **Self-mounting** — nothing needs to be
added to an app's template/shell. Calling `confirm()` creates a `ConfirmDialogComponent`
and attaches it straight to `document.body`; it tears itself down once the user
answers.

```ts
private readonly confirmService = inject(ConfirmService);

async delete(): Promise<void> {
  const ok = await this.confirmService.confirm({
    title: 'Delete team?',
    message: 'This removes the team and all its members. This cannot be undone.',
    danger: true,
    requireTyping: team.name,
  });
  if (ok) { ... }
}
```

`ConfirmOptions`: `title`, `message`, `confirmLabel?` (default "Confirm"),
`cancelLabel?` (default "Cancel"), `danger?` (renders the confirm button as
`btn-danger`), `requireTyping?: string` (confirm button stays disabled until the typed
value matches exactly — for irreversible ops).

If a future screen wants a dialog embedded in its own template instead (e.g. for
testing), `ConfirmDialogComponent` can be used directly — bind `[options]` and listen
for `(closed)`.

### `PageHeaderComponent` (`app-page-header`)

```html
<app-page-header title="Towers" subtitle="12 active" [topoBg]="true">
  <button actions class="btn btn-primary">New tower</button>
</app-page-header>
```

Inputs: `title` (required), `subtitle?`, `topoBg?` (default `false`). Actions go in an
element with the `actions` attribute (projected via `select="[actions]"`); wraps below
the title on narrow screens.

### `StatTileComponent` (`app-stat-tile`)

```html
<app-stat-tile label="Active towers" [value]="12" icon="bi-flag" tone="primary" />
```

Inputs: `label` (required), `value` (required, `string | number`), `icon?` (a
`bi-*` bootstrap-icons class), `tone?: 'default' | 'primary' | 'success' | 'warning' |
'danger' | 'info'` (default `'default'`). The value renders with `.tabular-nums`.

## Verifying changes

```bash
cd frontend
npx ng build player --configuration development
npx ng build staff --configuration development
```

Both must succeed. `ng build shared` (ng-packagr) is a fast way to type-check every
exported primitive in isolation, since its entry point is `public-api.ts` regardless of
whether anything imports a given symbol yet.
