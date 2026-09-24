# Tasks — deleting games and sessions, and dialogs the app owns

## 1. The deletion gate on the server

- [ ] 1.1 An `IsSuperUser` DRF permission in `game/admin_api.py`, alongside the existing `IsAdminUser` use.
- [ ] 1.2 A `DeletionBlocked` refusal carrying machine-readable `blockers`, in the shape `IllegalTransition` already gives the start gate, so one client-side reader serves both.
- [ ] 1.3 `Session.deletion_blockers()` — empty for draft and finished; for a live state, one blocker naming the state and the action that would settle it.
- [ ] 1.4 `Game.deletion_blockers()` — one blocker per live Session, each naming that session and its settling action.
- [ ] 1.5 `AdminSessionViewSet.perform_destroy`: superuser or 403; no blockers or 409.
- [ ] 1.6 `AdminGameViewSet.perform_destroy`: superuser or 403 — replacing the creator/collaborator check, which stays for update — then no blockers or 409.
- [ ] 1.7 `UserProfileSerializer` exposes `is_superuser`.
- [ ] 1.8 Tests: each refusal and each success, for both models; that a game's Collections, Towers and Zones survive it; that a clone survives its parent with empty ancestry; that a deleted session leaves no dangling `current_session`.

## 2. The delete controls

- [ ] 2.1 `deleteGame` / `deleteSession` on `StaffApiService`; `is_superuser` on the `UserProfile` type and an `isSuperuser` signal on `AuthService`.
- [ ] 2.2 A delete control on each Games row, present only for a superadmin.
- [ ] 2.3 A delete control on each Sessions row, on the same terms.
- [ ] 2.4 The Game dialog names the game, its session count, and that the sessions and their history go too; it requires the slug typed.
- [ ] 2.5 The Session dialog names the session and what goes with it.
- [ ] 2.6 A 409's blockers render as a list on the row, which stays put; a 403 renders as its message.
- [ ] 2.7 A success removes the row without a reload, and clears the current-session selection when that was what went.
- [ ] 2.8 Tests: the control's visibility follows `is_superuser`; a blocked delete leaves the row and shows its blockers.

## 3. Dialogs the app owns

- [ ] 3.1 `ConfirmService` becomes `DialogService` — `confirm()`, `alert()`, `prompt()` — keeping `ConfirmService` as a deprecated alias so the seven existing callers keep working through the migration.
- [ ] 3.2 The dialog component gains an alert mode (one acknowledging control) and a prompt mode (a labelled input, an initial value, resolving to the text or to null on cancel).
- [ ] 3.3 Semantics: `role="alertdialog"` when destructive, `role="dialog"` otherwise; `aria-labelledby` / `aria-describedby` already present stay correct in every mode.
- [ ] 3.4 Focus is trapped within the panel while open and returned to the previously focused element on close.
- [ ] 3.5 The page behind does not scroll while a dialog is open.
- [ ] 3.6 Escape and the backdrop cancel, returning what the cancel control returns — including for prompt, where that is null, not an empty string.
- [ ] 3.7 Tests for the service and the component: each mode's resolution, Escape, backdrop, focus return, the trap.

## 4. The nine remaining native calls

- [ ] 4.1 `review/active-locks.component.ts` — cancelling a team's lock.
- [ ] 4.2 `admin/score-multipliers-panel.component.ts` — deleting a scheduled multiplier.
- [ ] 4.3 `admin/game-roles-panel.component.ts` — deleting a role.
- [ ] 4.4 `admin/towers.component.ts` — closing every active ownership, which ends a round and deserves the destructive treatment.
- [ ] 4.5 `admin/collections.component.ts` — the collection action behind its confirm.
- [ ] 4.6 `admin/challenges.component.ts` — deleting a presence requirement, deleting a challenge, removing media: three sites.
- [ ] 4.7 `player/location/location-consent.component.ts` — the consent confirmation, carrying the session's consent text.
- [ ] 4.8 A guard test walks both SPAs and the shared library and fails on a native `confirm` / `alert` / `prompt`, excepting the dialog component itself, naming file and line when it fires.

## 5. Status as language

- [ ] 5.1 A `StatusPillComponent` in `shared`: a status string, an optional tone, a humanising fallback for statuses it has no label for.
- [ ] 5.2 One label map covering session lifecycle states, invite statuses, simulation run statuses, authoring proposal and operation statuses, and trail step states — the sets the app currently prints raw.
- [ ] 5.3 Every raw-status render moves onto the pill: `sessions`, `session-detail`, `game-state`, `live-overview`, `invites`, `simulator`, `authoring-review`, `badges`, the player's `trail` and `join-requests`.
- [ ] 5.4 Retire the per-component `STATE_BADGES` / `STATE_LABELS` maps the pill replaces.
- [ ] 5.5 Tests: the humanising fallback; that a known status renders its label rather than its constant.

## 6. Pills that can be read

- [ ] 6.1 A Sass relative-luminance function and a `pill-ink($fill)` that picks white or dark ink from it, in the shared theme next to the palette it reads.
- [ ] 6.2 Emit the pill's fill and ink per tone from the theme tokens, for light and dark mode both, so the running-state green takes white text.
- [ ] 6.3 The pill centres its text — a flex box with a line-height that leaves equal space above and below, rather than Bootstrap's `line-height: 1`.
- [ ] 6.4 Check the result in a browser against both modes and against the statuses in the screenshots that prompted this.

## 7. The session list's game filter

- [ ] 7.1 A game filter on the session list, defaulting to every game, working alongside the lifecycle filter.
- [ ] 7.2 The empty state names the filters in force.
- [ ] 7.3 Tests: the two filters compose; clearing the game filter restores every game.

## 8. Closing out

- [ ] 8.1 `ruff check .` clean.
- [ ] 8.2 Backend suite green, coverage at or above 80.
- [ ] 8.3 Frontend unit tests green.
- [ ] 8.4 `openspec validate destructive-actions-and-dialogs --strict` clean.
