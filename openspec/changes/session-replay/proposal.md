## Why

The simulator can already be scrubbed: it records an append-only tape and replays it on a Leaflet map with a tick slider, which is how we reason about whether a game design works. Real sessions record strictly richer data — `LocationPing` series, `TeamTowerOwnership` intervals, submissions — but the only view of it is a filterable table at `/sessions/:id/locations`, whose own docstring calls itself a wireframe. So the one thing the simulator exists to support (looking at how a game actually unfolded) cannot be done on a game that actually happened.

Separately, the simulator shipped in two commits with no OpenSpec capability at all, so nothing in `openspec/specs/` describes behavior we depend on.

## What Changes

- Introduce a single **replay model** — an ordered series of frames, each a full reconstructed snapshot of player positions, tower ownership, and team standings at one instant — with **two sources**: the simulator's tick tape and a recorded Session's wall-clock history.
- Add `GET /api/staff/sessions/{id}/replay/`, returning a self-contained bundle (roster, teams, tower geometry, zone geometry, per-frame downsampled positions, ownership intervals) so scrubbing never calls the backend.
- Replace the table-only location-history page with a **map + timeline scrubber** for recorded sessions: play/pause, step, seek, per-team filtering, tower ownership over time, and a standings panel. The raw ping table is retained as a panel beneath the map.
- Extract the simulator's client-side frame reconstruction into a shared projection used by both sources, so the two replays render through one code path.
- Document the already-shipped simulator as a first-class capability so `openspec/specs/` reflects reality.
- Harden time-window parsing on **both** the new replay endpoint and the existing `location-history` feed: an unparseable `from`/`to` bound is now a 400 naming the bound, not a silently unfiltered series. (The usual cause is a `+00:00` offset left unencoded, which arrives as a space.)

## Capabilities

### New Capabilities
- `session-replay`: the frame model, the two sources (simulated tape / recorded session), the staff replay bundle API, downsampling and retention behavior, and the map+scrubber view's required affordances.
- `game-simulator`: the shipped staff simulator — run configuration, lifecycle (setup/step/play/pause/stop/teardown), the requirement that it drive real domain code rather than a parallel rules engine, determinism from a seed, and cleanup of sim-created rows.

### Modified Capabilities
- `staff-app`: the staff SPA scope gains session replay and the simulator as named surfaces.
- `session-history`: the past-session read-only view gains a replay entry point alongside the final scoreboard and ownership timeline.

## Impact

- **New code**: `game/replay.py` (frame/bundle assembly), `game/replay_api.py` (`StaffSessionReplayView`), a shared `frontend/projects/shared/src/lib/replay/` projection + types, a rewritten `frontend/projects/staff/src/app/location/location-history.component.ts` (renamed to a replay component) and a shared map renderer.
- **Modified**: `game/location_api.py` (window-bound parsing, now shared with the replay endpoint), `geogame/urls.py` (one route), `frontend/projects/staff/src/app/app.routes.ts` (route rename `/sessions/:id/locations` → `/sessions/:id/replay`, old path redirects), `frontend/projects/staff/src/app/simulator/replay.ts` (re-pointed at the shared projection), `shared/staff-api.service.ts`.
- **No model changes and no migrations.** `LocationPing`, `TeamTowerOwnership` (a start/end interval table), `DementorState` and `Team` already carry everything a frame needs.
- **Data availability is bounded by existing rules**: replay of a recorded session is only as complete as `location_tracking_enabled`, per-player consent, and `location_retention_days` allow — a replay of a session that never tracked location shows tower ownership and standings but no player tracks.
- **Permissions**: staff-only (`IsAdminUser`), matching the existing location-history endpoint. No player-facing surface.
