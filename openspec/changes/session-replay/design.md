## Context

Two replay systems exist today and they do not meet.

The simulator (`simulator/`, staff `/simulator`) records every action it takes as an append-only `SimulationEvent` tape keyed by tick, and `frontend/projects/staff/src/app/simulator/replay.ts` reconstructs one full frame per tick entirely client-side — a deliberate property, since scrubbing a slider must not round-trip to the server. It renders players and tower ownership on a Leaflet map.

Recorded sessions carry the same information in a different shape: `LocationPing` (append-only, `recorded_at` client clock + `received_at` server clock, `team` denormalized at ingest so roster churn does not corrupt grouping), `TeamTowerOwnership` (a `timestamp_start`/`timestamp_end` interval table, so ownership at any instant is resolvable), and `DementorState` for dementors-mode runs. `StaffLocationHistoryView` already serves the ping series; the UI over it is a table.

Constraints that shape the design:

- Replay data for a recorded session is *partial by construction*. `location_tracking_enabled` may be off, individual players may never have consented or may have withdrawn (which purges their pings), and `location_retention_days` purges the series on a timer. The view must degrade rather than fail.
- A long session at a 10s ping interval produces on the order of 10^4–10^5 pings. The whole series cannot be shipped to the browser the way a short sim tape can.
- `TeamTowerOwnership.timestamp_start` is `auto_now_add`, so ownership history is only as granular as capture events — which is exactly the granularity we want.

## Goals / Non-Goals

**Goals:**

- One frame model and one projection code path serving both sources, so a fix to replay semantics fixes both.
- Scrubbing is backend-free after the initial bundle fetch, preserving the simulator's existing interaction property.
- The recorded-session bundle is bounded in size regardless of session length.
- Honest degradation: a session with no location data still replays ownership and standings.
- Capture the shipped simulator in `openspec/specs/` so it is no longer undocumented behavior.

**Non-Goals:**

- No player-facing replay. Staff-only, matching the existing endpoint's `IsAdminUser`.
- No new persistence. No models, no migrations — everything a frame needs is already recorded.
- No live-follow mode. Replay is retrospective; the live map is a separate existing surface.
- No export (video/GPX/CSV). Worth doing, not now.
- No re-simulation from recorded data ("what if this team had gone left") — that is the simulator's job, from a template game.

## Decisions

### Server buckets, client projects

The bundle API returns positions already downsampled to one sample per player per frame interval, but does **not** return pre-built frames. The client carries positions forward across gaps, resolves ownership intervals, and computes standings.

*Why:* bucketing is the only part that must happen server-side (it is what bounds payload size, and Postgres `DISTINCT ON` does it far better than JS). Frame assembly must happen client-side because that is what makes scrubbing instant. Splitting there gives a bundle of `frames × players` rows — for a 3-hour session, 30s frames and 30 players that is ~10k positions, a few hundred KB, acceptable for a staff tool on a laptop.

*Alternative rejected:* server returns fully-built frames. It would duplicate the simulator's projection logic on the backend in Python, leaving two implementations of replay semantics — precisely the split this change exists to close.

*Alternative rejected:* client fetches raw pings and buckets them itself. Unbounded payload; fails on exactly the long sessions most worth studying.

### Frames are indexed, timestamps are a label

Both sources project to `ReplayFrame { index, label, at, players[], towers[], standings[] }`. The simulator's `index` is its tick and `at` is null; a recorded session's `index` is the bucket ordinal and `at` is that bucket's wall-clock instant. The scrubber binds to `index` in both cases.

*Why:* a single slider control and a single projection signature. The alternative — a time-based scrubber with the simulator faking timestamps from `tick × tick_seconds` — would push a synthetic clock into sim data that has no real clock, and make sim replay lie about wall time.

### Carry-forward with a staleness horizon

A player's position persists across frames where they produced no ping, but goes stale after `max(3 × frame_interval, 120s)` and the player is then dropped from frames until their next ping.

*Why:* GPS gaps under tree cover are routine and blinking markers make tracks unreadable; but a player who stopped pinging an hour ago must not be drawn as if they were standing still on the hillside. The simulator source keeps its current semantics (no staleness — every player moves every tick), expressed as an infinite horizon rather than a separate code path.

### Ownership resolved from intervals, not from an event log

For a recorded session, tower ownership at frame time `t` is the `TeamTowerOwnership` row where `timestamp_start <= t AND (timestamp_end IS NULL OR timestamp_end > t)`. The bundle ships the intervals; the client does a per-frame lookup.

*Why:* it is the shape already stored, it is exact rather than reconstructed, and it stays correct regardless of frame interval. The simulator adapter keeps deriving ownership from `CAPTURE` events, since a sim tape has no interval table — the two adapters converge on the same `ReplayFrame.towers` shape.

### The shared projection lives in `shared`, adapters live beside their sources

`frontend/projects/shared/src/lib/replay/` holds the frame types and the projection (carry-forward, ownership resolution, standings). `simulator/replay.ts` becomes a thin adapter mapping `SimulationEvent[]` onto the projection's input; the new staff replay component holds the recorded-session adapter.

*Why:* the two sources genuinely differ in their *input* shape and genuinely agree on their *output* shape. Putting only the agreement in `shared` avoids a union-typed mega-function that branches on source throughout.

### Standings are derived, not fetched

Per-frame team standings are computed from tower ownership in the frame, matching what `simulator.component.ts` already does (towers held per team). The existing caveat carries over verbatim: this is not the true score, which accrues over time from zone control.

*Why:* fetching historical scores would require a score-history table that does not exist. Deriving towers-held is honest, already understood by the one existing consumer, and the panel labels it as such.

## Risks / Trade-offs

- **Replay of a session with tracking off looks broken to a user who does not know why.** → The bundle reports `location_tracking_enabled`, `consented_player_count`, and `retention_expires_at`; the view states plainly which layers are unavailable and why, rather than rendering an empty map.
- **Purged data silently shortens a replay.** → The bundle carries the retention window and the earliest surviving ping; the timeline marks the purged span rather than starting the session at the first surviving sample.
- **Bundle size still grows with roster × duration.** → `interval_seconds` is a query parameter with a server-enforced floor, and the server caps total frames, coarsening the interval and reporting the coarsening in the response rather than truncating the session.
- **`recorded_at` is client-supplied and can be skewed or replayed.** → Bucketing uses `recorded_at` (the sample clock, which is what a replay wants) but the bundle also ships `received_at` so an implausible track can be diagnosed; samples with `recorded_at` outside the session window ± a grace period are excluded.
- **Extracting `simulator/replay.ts` risks regressing working simulator behavior.** → Its existing tests move with it to the shared projection and must pass unchanged; the simulator adapter is covered by the same suite before the recorded-session adapter is written.
- **Documenting the shipped simulator may enshrine behavior we would not choose again.** → The `game-simulator` spec describes observable behavior and the drive-real-domain-code invariant, deliberately not the driver's internal movement model, which stays free to change.
