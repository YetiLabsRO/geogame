## Why

There is no view of a game in progress that shows *where* it is happening. The pieces exist but never meet:

| Surface | Map | Live | Scope |
| --- | --- | --- | --- |
| player `/` | yes | yes | one player's eyes — fog-of-war, teammates only, phone layout |
| staff `/scoreboard` | **no** | yes | numbers only, no geography |
| staff `/sessions/:id/replay` | yes | **no** | a finished session on a scrubber |
| staff `/simulator` | yes | yes | **simulated runs only** |

So a runner watching a live game can see the scores moving or the map standing still, never both. The thing you would put on a screen in the base tent — towers changing colour as they flip, zones shading toward whoever controls them, standings alongside — does not exist for a real session.

Everything it needs is already recorded and already broadcast. `visible_live_pings()` resolves live positions, `GET /api/sessions/{id}/scoreboard/` is already session-addressed with staff access to any session, and the websocket already carries `tower.ownership_changed`, `zone.control_changed`, `scoreboard.updated` and `session.state_changed`. What is missing is a surface that composes them, and a way to put that surface on a screen nobody is signed in at.

## What Changes

- Add a **live overview** — a map-dominant, distance-readable view of one Session as it runs: towers painted by their owning team, zones tinted by control, a standings rail, a capture ticker, and the session's state (running / paused / finished) stated plainly.
- Add `GET /api/staff/sessions/{id}/overview/`: one self-contained snapshot (session state, teams, tower geometry + current owner, zone geometry + current controller, standings, active multipliers, recent captures, player positions where permitted).
- Add a **revocable share link** so the display can run on a screen with no staff account signed into it: `SessionOverviewLink` carries an opaque token, is created and revoked by staff per Session, and addresses a read-only route (`/staff/live/{token}`) plus a read-only snapshot endpoint (`GET /api/overview/{token}/`). A revoked link stops working immediately.
- **Apply the Session's own live-location config to the overview, even for staff.** This is the deliberate part: `visible_live_pings()` lets staff see every consenting player regardless of `location_visibility`, which is right for a console one staff member is reading and wrong for a screen a room is reading. The overview therefore plots player positions only when the effective `location_visibility` is `EVERYONE` and `teammate_visibility_mode` is not `SELECT_COUNT`; otherwise it shows towers, zones and standings and says on the page why the dots are absent.
- **Admit a share link to the realtime socket read-only, behind an event allowlist** — `tower.ownership_changed`, `zone.control_changed`, `scoreboard.updated`, `bonus.appeared`, `session.state_changed` — so a wall display reacts to a capture in under a second rather than at the next poll. `dementor.tick` is never forwarded to a share viewer: it carries per-player role and energy detail the overview does not show.
- Give the staff app a nav entry, a share-link manager on the session console, and a presentation mode that drops the shell chrome and scales type for reading across a room.

## Capabilities

### New Capabilities
- `live-overview`: the overview surface and its snapshot contract; the visibility policy that governs a *shared* surface as distinct from a staff console; the share-link lifecycle (issue, address, revoke, expire); and the realtime admission and event allowlist for a share viewer.

### Modified Capabilities
- `staff-app`: the staff SPA scope gains the live overview as a named surface, reachable from the nav and from a Session's console, with share links managed there.

## Impact

- **New model + migration**: `game.SessionOverviewLink` (token, session, label, `is_active`, optional `expires_at`, `created_by`, `created_at`). One table, no changes to existing ones.
- **New code**: `game/overview.py` (snapshot assembly), `game/overview_api.py` (staff snapshot, token snapshot, link CRUD), a staff overview component plus a shared presentation layer, and a share-link panel on the session console.
- **Modified**: `game/consumers.py` and `game/ws_auth.py` (share-viewer admission + allowlist), `geogame/urls.py`, the staff routes and nav model, `shared/staff-api.service.ts`.
- **No deployment change.** nginx already serves the staff bundle publicly at `/staff/` and gates it with `staffGuard` rather than at the edge, exactly as `/staff/login` is reached today — so `/staff/live/{token}` is reachable the moment it ships.
- **Default configuration shows no player dots.** `location_visibility` defaults to `OWN_TEAM`, which cannot be honoured on a surface with no single viewer; a Session that wants dots on the wall must set `EVERYONE` deliberately. This is a consequence of the rule above and is called out in the UI rather than left to be discovered.
- **New public surface.** The token endpoint and the token websocket are the first unauthenticated reads of live game state. They are read-only, session-scoped, revocable, rate-limited, and expose strictly a subset of what the staff snapshot exposes.
