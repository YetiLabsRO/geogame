## Why

**Nothing can be removed.** A Game can be created, cloned and deactivated, but never deleted; a Session likewise. Every mistyped slug, every abandoned rehearsal, every half-built clone stays on the Games page and in the session switcher forever, and the only way out is the Django admin — which happily cascades a live run into nothing without a word of warning. The staff console has no answer at all, so the one destructive operation people actually need is the one they have to leave the app to perform, on the screen least equipped to make it safe.

**The confirmations are browser popups.** A themed `ConfirmService` exists and seven call sites use it. Nine others still call the native `confirm()`, including the ones that close every ownership in a round and delete a challenge outright. They arrive unstyled, unbranded, anchored to the top of the window, unreadable in dark mode, and they say "localhost:4501 says". The app is asking for the most consequential decisions it ever asks for through the one surface it does not control. And there is nothing stopping the tenth from being written tomorrow.

**The status pills are hard to read.** `OPEN_FOR_PARTICIPANTS` is a database constant wearing a badge — a label nobody would write for a human. The RUNNING pill draws black text on trail green, because Bootstrap computes badge ink at build time against a 4.5 contrast ratio and falls to black when our green misses it; at 0.75em on a saturated fill that is the least legible of the two options, not the most. And every pill sits its text high in the fill, because Bootstrap's `line-height: 1` leaves descender space under all-caps text that nothing above it balances.

**The session list cannot be narrowed to a game.** It groups by game and filters by lifecycle — all, active, past — so an install with a dozen games gives you a dozen headings to scroll past to reach one. The grouping that helps when there are three games is exactly what costs you when there are thirty.

## What Changes

- **A superadmin can delete a Game or a Session** from the staff console, and only a superadmin can. Deleting a Game takes its Sessions with it — that is what a Game is made of — and says so plainly before it happens.
- **A live run is never deleted out from under itself.** A Session that is open for participants, running, or paused must be closed first; the refusal names the action that would unblock it. A Game with any live Session is refused for the same reason, naming them.
- **Deleting asks first, in the app's own dialog**, and a Game — which takes sessions, teams and their history with it — asks the person to type its slug.
- **Every confirmation, alert and prompt becomes a themed modal.** The nine remaining native calls move to the shared service; `alert()` and `prompt()` join `confirm()` there so there is a themed answer for each; a guard test fails the build if a native one reappears.
- **Dialogs are semantic.** `alertdialog` for the destructive ones and `dialog` for the rest, labelled and described by their own title and message, focus moved in on open and returned on close, Escape and backdrop cancel, and Tab held inside the panel.
- **Status reads as language, not as an enum.** `OPEN_FOR_PARTICIPANTS` becomes `Open for participants`, everywhere a status is shown, from one shared pill.
- **Pill ink is chosen by luminance**, not by a build-time contrast ratio, so a mid-tone fill gets white text rather than black; and the pill centres its text.
- **The session list filters by game**, alongside the lifecycle filter it already has.

## Capabilities

### Modified Capabilities
- `game-configuration`: a Game can be deleted by a superadmin, cascading to its Sessions and leaving shared Collection content intact.
- `sessions`: a Session can be deleted by a superadmin once it is no longer live.
- `staff-app`: delete controls on the Games and Sessions pages; every dialog is the app's own; status is shown as language through one shared pill; the session list filters by game.
- `player-app`: the location-consent confirmation is the app's own dialog rather than the browser's.

## Impact

- **Backend**: `AdminGameViewSet.perform_destroy` / a new `AdminSessionViewSet.perform_destroy` gain a superuser gate and a live-state gate; a shared `IsSuperUser` permission and a `DeletionBlocked` refusal carrying machine-readable blockers, mirroring the 409 shape `IllegalTransition` already uses for the start gate. `UserProfileSerializer` gains `is_superuser` so the SPA can hide a control it would be refused anyway. No migrations — every FK that matters is already `CASCADE` or `SET_NULL`, including `UserProfile.current_session`.
- **Frontend**: `ConfirmService` grows `alert()` and `prompt()` and the dialog component grows the focus trap and `prompt` input; nine call sites migrate; a new `StatusPillComponent` in `shared` with a Sass luminance function for its ink; `sessions.component.ts` gains a game filter and the delete control; `games.component.ts` gains the delete control.
- **Not a soft delete.** Deactivating already exists and is the reversible option; this is the irreversible one, and the dialog says so. A Game's Collections, Towers and Zones are shared by reference and survive — only the Game's own configuration and its runs go.
- **Non-goal**: deleting Teams, Challenges or Collections from the console. Challenge deletion already exists and only moves onto the themed dialog here; the rest stay where they are.
