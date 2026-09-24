## Why

The staff app's navigation is a single non-wrapping row of 19 links. It runs off the right edge of the window at every viewport width, so the last several destinations — Dementors, Game state, Badges, AI review, Simulator — cannot be reached by clicking at all. The markup declares `navbar-expand-sm` but ships no `navbar-toggler`, so there is nothing to collapse into on small screens either; the row simply overflows.

The list has also outgrown a flat presentation. Nineteen peers with no grouping give no cue about which screens belong to running a game, building one, or administering rosters, and the set grows with every capability we add — replay and the simulator are the two most recent.

## What Changes

- Replace the top-bar link row with a **left sidebar** organised into four labelled sections: Run, Build, Organize, Analyze.
- The sidebar becomes the app shell: it is fixed and independently scrollable, so the number of destinations no longer competes with the page for horizontal space.
- Below a breakpoint the sidebar collapses behind a toggle and opens as an overlay, so the staff app is usable on a phone in the field — which it currently is not.
- The top bar keeps only identity and context: brand, session switcher, username, sign out.
- Add the missing **NFC tags** link. `/nfc-tags` has had a route and a working page since `nfc-native-and-secure-links`, reachable only by typing the URL.
- Mark the active destination, and keep its section visible, so the sidebar answers "where am I" as well as "where can I go".

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `staff-app`: the navigation requirement changes from an unstated flat link row to a sectioned, always-reachable sidebar; every route the app serves SHALL be reachable from it.

## Impact

- **Modified**: `frontend/projects/staff/src/app/app.html` (shell markup), `app.ts` (sidebar open/close state), `app.scss` (sidebar layout), and `styles.scss` only if a token is missing.
- **No backend change, no API change, no migration.** This is presentation only; no route paths change, so existing links and bookmarks keep working.
- **Every staff page** gains horizontal space previously taken by the overflowing nav row, and loses it on the left to the sidebar — net neutral on wide screens, a clear gain below ~1200px where the row was unusable.
- Colors come from the existing token layer (`--panel`, `--border`, `--ink-muted`, `--primary`); no new palette values, and dark mode follows `data-bs-theme` as it already does.
