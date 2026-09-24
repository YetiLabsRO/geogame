# Tasks — live game overview

## 1. Share link model

- [x] 1.1 Add `game.SessionOverviewLink`: `token` (unique, `secrets.token_urlsafe(24)`, non-editable), `session` FK, `label`, `is_active`, `expires_at` (nullable), `created_by`, `created_at`. Migration `0040_sessionoverviewlink`. Also carries `revoked_at`, so "was this the one I killed?" is answerable.
- [x] 1.2 `SessionOverviewLinkQuerySet.usable()` is the single definition of "this link works" — used by both the REST resolver and the websocket, so revocation and expiry cannot drift apart between them.
- [x] 1.3 Tests: tokens distinct and ≥24 chars; expired and revoked links both refused; revocation immediate.

## 2. Snapshot assembly

- [x] 2.1 `game/overview.py`: `build_overview_snapshot(session)` — session + lifecycle state, groups, teams, towers with geometry and ownership, zones with geometry and control colour, standings, active multipliers, recent captures, positions.
- [x] 2.2 Ownership read from the open interval via `events._tower_ownership_by_group`, **keyed by TeamGroup** — several groups play one map, so a tower has one owner per group rather than one owner. Zone colours likewise.
- [x] 2.3 Towers come from the Session's current geometry. Unlike `replay._towers_for`, the overview is the present instant, so current geometry is exactly the right set and a retired tower should be absent.
- [x] 2.4 `position_visibility()`: plot only when effective `location_visibility == EVERYONE` and effective `teammate_visibility_mode != SELECT_COUNT`. Returns a reason code when suppressed so the UI explains rather than renders an empty map.
- [x] 2.5 Consent filtered under every configuration; a withdrawn consent removes the player.
- [x] 2.6 Recent captures read from `TeamTowerOwnership` starts, not from a broadcast log — a screen that connects mid-game must not open with an empty ticker.
- [x] 2.7 Tests (17): open vs closed interval; every row of the visibility table; non-consenting and withdrawn players; standings agree with the scoreboard endpoint; ticker newest-first.

## 3. Endpoints

- [x] 3.1 `GET /api/staff/sessions/{id}/overview/` — `IsAdminUser`, 404 for an unknown Session.
- [x] 3.2 `GET /api/overview/{token}/` — unauthenticated, and **narrower than the staff snapshot**: no usernames.
- [x] 3.3 Share-link list / create / revoke, staff-only. Revoke is a state change; revoked links stay listed.
- [x] 3.4 `OverviewLinkThrottle` keyed on the token, not the caller — a display and a phone behind one NAT are one address and two links. Needed a `CACHES` setting, which the project did not have (Redis in production, LocMem otherwise; the per-process caveat is in the settings comment).
- [x] 3.5 Unknown, revoked, expired and wrong-session tokens all return the identical 404 body.
- [x] 3.6 Tests (14), including that revoked and never-existed responses are byte-identical.

## 4. Realtime admission

- [x] 4.1 `ws_auth`: `?overview=<token>` resolves to `scope['overview_link']`, leaving the user anonymous.
- [x] 4.2 A scope presenting both credentials sets `auth_conflict` and is refused rather than merged.
- [x] 4.3 `_admission` admits a usable link bound to the URL's Session, reusing 1.2's helper; a link for another Session is 4403.
- [x] 4.4 Restricted connections forward only `OVERVIEW_EVENTS`; `dementor.tick` excluded by construction.
- [x] 4.5 Revocation broadcasts to a per-link channel group so a socket already open is closed — otherwise the revoke button stops the next request and leaves the projector running.
- [x] 4.6 Tests (10). Confirmed non-vacuous: removing the allowlist filter fails exactly the two allowlist tests and nothing else.

## 5. Staff overview view

- [x] 5.1 `/sessions/:id/overview` behind `staffGuard`; Leaflet map, towers painted by owner, zones tinted by controller, neutral when unowned, contested rendered as a neutral low-opacity fill rather than white (white reads as a hole in OSM tiles).
- [x] 5.2 Standings rail, towers-held tally, capture ticker, lifecycle state badge.
- [x] 5.3 Live from the websocket; snapshot poll at 15s, slowing to 60s while the socket is up. Positions move only on the poll — they are not on the socket — which also keeps the visibility rule enforced in exactly one place.
- [x] 5.4 Suppressed dots explain themselves, naming the setting and what to change.
- [x] 5.5 Presentation mode drops the chrome, scales type, and best-effort requests browser fullscreen.
- [x] 5.6 Reuses `TeamColorResolver` and the replay view's paint conventions.
- [x] 5.7 No control on the page alters game state.
- [x] 5.8 `/overview` (no id) resolves the session switcher's selection, matching `/scoreboard`, and awaits the profile rather than reading it — a reload has not resolved it yet.

## 6. Share route and link management

- [x] 6.1 `/live/:token` in the staff app, outside `staffGuard`, alongside `/login`.
- [x] 6.2 Same component, token-fed, management and controls absent.
- [x] 6.3 A chromeless branch in the app shell for `/live/`: neither the staff sidebar nor the signed-out "Sign in" bar belongs above a wall display.
- [x] 6.4 Share-link panel on the session console: list, create, copy, revoke behind a confirm. Plus a "Live overview" action on the console header.
- [x] 6.5 Nav entry under Run; `/live/:token` is parameterised and so excluded from the nav-coverage assertion by construction. Confirmed the assertion fails when the `/overview` entry is removed.

## 7. Verification

- [x] 7.1 `ruff check .` clean.
- [x] 7.2 `coverage run manage.py test game organize simulator --noinput` and `coverage report --fail-under=80` clean. 1005 tests OK; 92% total, `game/overview.py` 100%, `game/overview_api.py` 96%, `game/ws_auth.py` 95%, `game/consumers.py` 99%.
- [x] 7.3 Frontend suite clean (shared 49, staff 10); both apps build.
- [x] 7.4 Browser: the share route renders the map, 6 towers painted by owner, 6 player dots, standings, held tally and ticker, with no sidebar, no management and 0px horizontal overflow.
- [x] 7.5 Browser: revoking from the session console flips the row to "Revoked" and the open display refuses with "This link is no longer valid."
- [x] 7.6 Browser: `location_visibility = OWN_TEAM` drops the dots (14 paths → 8) and shows the explanation naming what to change; `EVERYONE` brings them back.
- [x] 7.7 Browser: staff `/overview` and `/sessions/:id/overview` both render; presentation mode engages; no horizontal overflow at 1600px or at 390px.
- [x] 7.8 Browser: zone tint verified against real `TeamZoneOwnership` rows — held paints the team colour at 0.3, contested paints neutral at 0.12.

## 8. Notes

- The websocket cannot be exercised against `manage.py runserver` (WSGI); the dev display correctly falls back to polling and says "Polling". Pre-existing, and it affects the scoreboard identically.
- The copied share address is built from the API host. Correct in production, where nginx serves `/staff/` and `/api/` from one host; in development it points at :8200 rather than the SPA dev server.
