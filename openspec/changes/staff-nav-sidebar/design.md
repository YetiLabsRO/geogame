## Context

The staff shell is `app.html`: a Bootstrap navbar whose `<ul>` is `flex-row` with nineteen `nav-item`s, plus a right-hand cluster holding the session switcher, username and sign-out. `navbar-expand-sm` is set but no `navbar-toggler` exists, so the collapse behaviour Bootstrap would provide is never wired up and the row overflows at every width rather than only on small screens.

Constraints that shape this:

- The app themes stock Bootstrap 5.3 rather than replacing it (`frontend/THEME.md`). Whatever replaces the navbar must keep using Bootstrap classes and the `--panel` / `--border` / `--ink-muted` token layer, and must follow `data-bs-theme="dark"` without its own dark-mode branch.
- Route paths are not changing. Everything in `app.routes.ts` keeps its URL; only how it is reached changes.
- The destination list grows. Four capabilities added a nav entry in the last stretch of work; the structure has to absorb the next one without another redesign.

## Goals / Non-Goals

**Goals:**

- Every route the staff app serves is reachable by clicking, at every viewport width.
- Destinations are grouped so their purpose is legible without reading all nineteen.
- The shell works on a phone, which it does not today.
- No route, component, or API changes — presentation only, so the diff is reviewable and reversible.

**Non-Goals:**

- No new staff screens, and no changes to the pages themselves beyond the width they occupy.
- No per-user customisation, pinning, favourites, or reordering.
- No role-based hiding of sections. Everything here is already behind `staffGuard`; narrowing by role is a separate concern with its own permissions model.
- No search/command palette over destinations. Reasonable later; nineteen items grouped into four sections does not need one yet.

## Decisions

### A sidebar, not dropdowns

Grouping the row into four dropdown menus would also fit, and is a smaller diff. A sidebar was chosen because it shows the groups *and* their contents at once: with dropdowns, finding a screen you cannot name costs four open-and-close cycles, which is the actual failure mode when a console has this many destinations. The sidebar also has room to grow vertically, where the top bar had already run out horizontally.

The cost is real and accepted: the shell markup changes rather than being extended, and the sidebar takes 224px from every page.

### Four sections, split by when you use them

- **Run** — what you open while a game is live: review queue, field mode, scoreboard, join requests, game state, dementors.
- **Build** — what you prepare beforehand: map editor, towers, zones, collections, challenges, trails, NFC tags, badges, AI review.
- **Organize** — who is playing: games, sessions, teams, invites.
- **Analyze** — after or instead of a game: simulator, and session replay's entry point stays on the session itself.

Splitting by *when* rather than by *data type* is the decision worth defending. A type-based split would put towers, zones and the map editor together with the scoreboard under "game data", which matches the schema but not the work. Staff arrive at this console in one of three modes — preparing, running, or reviewing — and that is the axis that predicts which screen they want.

### Collapsed behind a toggle below `lg`

The sidebar is persistent at `lg` and up, and below that collapses to a toggle that opens it as an overlay over the page. `lg` rather than `sm` because the staff pages are dense tables and maps; at `md` there is not enough room for both.

Field mode is the one staff screen genuinely used on a phone, which is why a working small-screen shell is a goal here rather than a nicety.

### State lives in the shell component, not a service

A single `sidebarOpen` signal on `App`, toggled by the button and cleared on navigation. No service, no route data, no persistence.

*Why:* nothing else needs to read it. A service would be indirection without a second consumer, and persisting a collapsed sidebar across reloads is a preference feature this change explicitly is not adding.

### The section list is data, not markup

Sections and their items are a typed array in `app.ts`, rendered by a nested `@for`. Adding a destination is one line in that array.

*Why:* the current file is nineteen near-identical eleven-line `<li>` blocks, which is exactly why `/nfc-tags` could be added as a route and silently never linked. A data-driven list makes an omission visible, and makes "is every route reachable?" a question you can answer by reading one array.

## Risks / Trade-offs

- **Page width changes, and not only by the sidebar's 224px.** The content column also drops Bootstrap's centred `.container` (max-width 1140-1320px) for a full-width column, which suits a dense console beside a sidebar. Net effect: wide screens gain usable width (1920px: ~1320 -> ~1660), mid screens are roughly unchanged, and below `lg` the sidebar is an overlay so pages get everything. → The map editor and scoreboard are the two worth eyeballing, since full-bleed is a real change to how they read.
- **Muscle memory breaks for anyone who knows the current row.** → Route paths are unchanged, so bookmarks and deep links all still work; only the shell moves.
- **Four sections is a judgement call and some items are arguable** — AI review could sit under Analyze, game state under Organize. → The grouping is data in one array, so moving an item is a one-line change once real use says otherwise.
- **A route added without a sidebar entry is still possible.** → Reduced, not eliminated: the items array is the one obvious place to add it, and this change fixes the one existing instance. A test asserting every non-parameterised route appears in the array would close it properly; noted, not built here.
