## 1. Backend: replay bundle

- [x] 1.1 Add `game/replay.py` with a `build_replay_bundle(session, *, interval_seconds, window_from, window_to)` returning session identity/window, teams (id/name/colour), roster, towers with lat/lng, zone geometry, ownership intervals, and per-frame downsampled positions.
- [x] 1.2 Implement frame-interval resolution: caller value, server-enforced minimum, and coarsening when the frame count would exceed the cap — reporting the interval actually used.
- [x] 1.3 Implement per-player-per-frame downsampling (one most-recent ping per player per bucket) using Postgres `DISTINCT ON`, not Python-side dedupe.
- [x] 1.4 Exclude samples whose `recorded_at` falls outside the Session window by more than the grace period; keep `received_at` on the samples that survive.
- [x] 1.5 Include ownership intervals that overlap the requested window (not only those starting inside it), so frame 0 shows correct ownership.
- [x] 1.6 Report availability metadata: `location_tracking_enabled`, consenting-player count vs roster size, retention window, and earliest surviving sample.
- [x] 1.7 Add `StaffSessionReplayView` in `game/replay_api.py` (`IsAdminUser`), route it at `api/staff/sessions/<int:pk>/replay/` in `geogame/urls.py`.

## 2. Backend: tests

- [x] 2.1 Test the endpoint is staff-only and 404s on an unknown session.
- [x] 2.2 Test downsampling: many pings in one bucket yield one position; the raw location-history endpoint still returns all of them.
- [x] 2.3 Test interval coarsening reports the interval used and does not truncate the session.
- [x] 2.4 Test windowing includes ownership intervals that started before `from` and had not ended.
- [x] 2.5 Test a session with `location_tracking_enabled` false returns ownership and teams with no positions, and reports why.
- [x] 2.6 Test out-of-window `recorded_at` samples are excluded.
- [x] 2.7 Test a session with partially purged history reports retention window and earliest surviving sample.

## 3. Shared frontend projection

- [x] 3.1 Create `frontend/projects/shared/src/lib/replay/` with `ReplayFrame`, `ReplayPlayer`, `ReplayTower`, `ReplayStanding` types carrying frame `index`, `label`, and nullable `at`.
- [x] 3.2 Implement the shared projection: carry-forward with a staleness horizon (infinite for the simulated source), ownership resolution, and towers-held standings.
- [x] 3.3 Cover the shared projection with tests. (`simulator/replay.ts` had **no** existing tests to move — 16 new specs were written against the projection instead.)
- [x] 3.4 Reduce `frontend/projects/staff/src/app/simulator/replay.ts` to an adapter mapping `SimulationEvent[]` onto the projection input; verify the simulator page behaves identically.
- [x] 3.5 Export the replay types and projection from the `shared` public API.

## 4. Staff replay view

- [x] 4.1 Add `getSessionReplay(id, params)` to `shared/staff-api.service.ts` with typed bundle interfaces.
- [x] 4.2 Write the recorded-session adapter (`shared/replay/recorded-source.ts`) mapping a bundle onto the shared projection input — placed in `shared` rather than the staff app because only `shared` has a unit-test builder.
- [x] 4.3 Replace `location-history.component.ts` with a replay component: Leaflet map rendering zones, towers coloured by owner at the current frame, and player markers coloured by team.
- [x] 4.4 Add timeline controls — play, pause, step, seek — bound to frame index, with the current frame's wall-clock instant displayed.
- [x] 4.5 Ensure scrubbing issues no HTTP requests after the initial bundle fetch.
- [x] 4.6 Add team filtering that narrows plotted players while leaving the standings panel complete.
- [x] 4.7 Add the standings panel, labelled as towers-held and explicitly not the accrued score.
- [x] 4.8 Render availability state: tracking disabled, how many of the roster are plotted, and a purged-span marker on the timeline.
- [x] 4.9 Retain the raw ping feed as a collapsible panel beneath the map, keeping the existing user/team/time-window filters.

## 5. Routing and entry points

- [x] 5.1 Route `/sessions/:id/replay` in `frontend/projects/staff/src/app/app.routes.ts`; redirect `/sessions/:id/locations` to it.
- [x] 5.2 Link to the replay from the session detail view.
- [x] 5.3 Reuse the shared team-colour helper rather than duplicating `simulator/team-colors.ts`.

## 6. Verification

- [x] 6.1 Add frontend tests for the shared projection: carry-forward, staleness drop, pre-first-sample omission, ownership at a boundary instant, ownership change mid-replay.
- [x] 6.2 Run `ruff check .` clean.
- [x] 6.3 Run `coverage run manage.py test game organize --noinput` and `coverage report --fail-under=80` clean. (942 tests OK; 92% total, `game/replay.py` 92%, `game/replay_api.py` 100%.)
- [x] 6.4 Run the frontend test suite clean. (37 specs pass; both apps build.)
- [x] 6.5 Drive a simulator run, stop it, then replay that Session — confirm both sources agree. Covered by `simulator.tests.SimulatedRunReplayTest` (5 tests): a driven-then-stopped run replays through the staff bundle, and the tape's last CAPTURE per tower is checked against the bundle's latest ownership interval.
  - [ ] 6.5a Visual smoke test of the rendered page in a browser. **Not done** — needs the dev stack plus staff credentials for the local dev database, which this session does not have.

## 7. Defects found during verification

- [x] 7.1 `history_truncated` fired whenever the first ping post-dated the session start — true of nearly every session. Re-derived from the retention cutoff instead, in `game/replay.py` and the view's purged-span marker.
- [x] 7.2 Frame assignment was off by one roughly half the time: Postgres `CAST(... AS integer)` rounds, so a window start carrying >0.5s of microseconds pushed every sample into the next frame. Replaced with an explicit `FLOOR` over float seconds; pinned by `test_frame_assignment_ignores_sub_second_window_skew`.
- [x] 7.3 An unparseable `from`/`to` bound was silently ignored on the existing `location-history` feed. Both it and the replay endpoint now reject it with a 400 naming the bound, via a shared `parse_window_bound`.
- [x] 7.4 CI ran only `game organize`, so the simulator app's tests — including the new sim-to-replay coverage — executed nowhere. Added `simulator` to the CI test labels and to the documented commands; the combined run is green (964 tests, 92%).
