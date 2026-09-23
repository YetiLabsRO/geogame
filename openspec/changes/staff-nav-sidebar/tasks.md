## 1. Shell structure

- [x] 1.1 Define the section/item nav model in `app.ts` as a typed array — Run, Build, Organize, Analyze — with every top-level staff route represented, including the currently-unlinked `/nfc-tags`.
- [x] 1.2 Add a `sidebarOpen` signal and a toggle, cleared on navigation so choosing a destination dismisses the overlay.
- [x] 1.3 Rewrite `app.html`: sidebar (brand, sections, Django Admin link) beside a main column holding the top bar (toggle, session switcher, username, sign out) and the router outlet.
- [x] 1.4 Render sections and items with a nested `@for`, marking the active entry via `routerLinkActive` (exact only for `/`).
- [x] 1.5 Add the "Django Admin" link the shipped `staff-app` spec already requires — it is absent from the current shell.
- [x] 1.6 Keep the unauthenticated/non-staff shell free of the sidebar, as today.

## 2. Layout and theme

- [x] 2.1 Style the sidebar in `app.scss` using existing tokens (`--panel`, `--border`, `--ink-muted`, `--primary`) — no new palette values, no hardcoded colors.
- [x] 2.2 Persistent sidebar at `lg` and up; below that a fixed overlay with a backdrop, hidden until toggled.
- [x] 2.3 Give the sidebar its own scroll so a long section cannot push content off-screen.
- [x] 2.4 Verify dark mode follows `data-bs-theme` with no dark-specific branch of its own. (No dark branch and no hardcoded colors in `app.scss`; the one literal is the overlay scrim, deliberately theme-independent like the shadow tokens.)

## 3. Accessibility

- [x] 3.1 Mark up the sidebar as a `<nav>` with an accessible name; sections as labelled groups.
- [x] 3.2 Give the toggle `aria-expanded` / `aria-controls`, and the active entry `aria-current="page"`.
- [ ] 3.3 Confirm the whole sidebar is keyboard reachable and the visible focus ring survives the new background. **Not done** — needs a browser; chrome-devtools MCP would not launch this session.

## 4. Verification

- [x] 4.1 Assert every non-parameterised route in `app.routes.ts` appears in the nav model, so a future route cannot be added without a link. Required adding a `test` target for the `staff` project in `angular.json` (its `tsconfig.spec.json` already existed); 6 specs, and the coverage assertion was confirmed to fail when a link is removed.
- [x] 4.2 `ng build staff` clean.
- [x] 4.3 Frontend test suite clean. (shared 37, staff 6; both apps build.)
- [ ] 4.4 Check the two widest pages — map editor and scoreboard — still lay out correctly in the full-width content column. **Not done** — needs a browser.
- [ ] 4.5 Check the shell at phone width: sidebar hidden, toggle reveals it, choosing a destination dismisses it. **Not done** — needs a browser.
