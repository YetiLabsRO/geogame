## 1. BLE proximity substrate — models

- [x] 1.1 Add `game.ProximityIdentity` (per player, per session: opaque `token`, `issued_at`, optional `rotates_at`, `active`) with a uniqueness constraint on the active token per session; admin + migration.
- [x] 1.2 Add `game.ProximityReport` (reporter `ProximityIdentity` / player, `session`, `reported_at`, and a batch of observed `{token, rssi}` entries as a related model or JSON, plus `received_at`); index by session + `received_at` for freshness queries.
- [x] 1.3 Add `game.ProximityEvent` (server-derived unordered near-pair for a session/tick: `player_a`, `player_b`, `distance_bucket`, `confidence`, `derived_at`); index by session + `derived_at`.
- [x] 1.4 Add a `require_ble_capable` flag and BLE substrate cadence knobs (report interval, scan duty-cycle, freshness window) on `organize.Game` with nullable `organize.Session` overrides via the effective-value helper.

## 2. BLE proximity substrate — server logic & API

- [x] 2.1 `POST /api/proximity/identity/`: issue (or rotate) the caller's ephemeral advertising token for their active session; map token→player only server-side.
- [x] 2.2 `POST /api/proximity/reports/`: accept a batch of observed tokens + RSSI from one phone; validate/rate-limit; persist a `ProximityReport`; reject unknown/expired tokens gracefully.
- [x] 2.3 RSSI→bucket mapper with hysteresis (VERY_CLOSE / NEAR / FAR or configurable set); no metres exposed.
- [x] 2.4 Proximity derivation pass: from reports within the freshness window, fuse both directions of each pair into one `ProximityEvent` with a corroboration-boosted `confidence`; apply plausibility filters (rate, impossible-crowd, expired-ID).
- [x] 2.5 BLE-capability gate: a device self-check endpoint/flag so a Game with `require_ble_capable` refuses non-BLE devices with a clear message while still admitting mixed BLE hardware.

## 3. Dementors mode — models & config

- [x] 3.1 Add `game.DementorState` (per player per session: `role` WIZARD/DEMENTOR, `energy`, `last_tick_at`, flip/convert history, `alive`).
- [x] 3.2 Add dementor config on `organize.Game` + nullable `organize.Session` overrides (drain rate, drain-range bucket, starting energy, `flip_on_empty` vs `die_on_empty`, `safety_in_numbers` vs area-drain, reverse-game group size `N` + hold duration `T`, conversion threshold, tick cadence); resolve via the effective-value helper.
- [x] 3.3 Session start hook: assign initial WIZARD/DEMENTOR roles and starting energy per config.

## 4. Dementors mode — server economy tick

- [x] 4.1 Tick job: read current `ProximityEvent`s in the drain-range bucket, apply drain to wizards near dementors, and apply gain/regeneration per config; write `DementorState` atomically.
- [x] 4.2 Safety-in-numbers vs area-drain: divide a clustered wizard's effective drain by nearby-wizard count, or drain all in range at full rate, per config.
- [x] 4.3 Full-drain flip: a wizard reaching empty flips to dementor or dies per `flip_on_empty`/`die_on_empty`.
- [x] 4.4 Reverse numbers game: when ≥`N` wizards keep a dementor in range continuously for `T`, flip that dementor to wizard.
- [x] 4.5 Two-way conversion: a dementor whose energy crosses the conversion threshold flips back to wizard; record all flips with cause.

## 5. Real-time & APIs

- [x] 5.1 `GET /api/dementors/me/`: own role, energy, and the live drain/gain delta for the current tick (polling fallback).
- [x] 5.2 `GET /api/staff/dementors/session/{id}/totals/`: live role counts (e.g. 5 dementors / 10 wizards) and a per-player feed for a map/tablet.
- [ ] 5.3 Channels push: live energy/role updates to each player and live totals to the staff dashboard; polling remains a graceful fallback.

## 6. Frontend

- [x] 6.1 Player SPA Dementors screen: energy bar, role badge, and a real-time drain/gain pulse that signals an unseen dementor nearby.
- [x] 6.2 Player SPA "phone out, screen on" affordance: keep the screen awake during play and prompt when reports go stale.
- [ ] 6.3 Native BLE bridge in the mobile player build: advertise the ephemeral token and scan for peers, batching seen tokens + RSSI to the report endpoint.
- [x] 6.4 Staff SPA dashboard: live role totals plus an optional map/tablet view of players by role.

## 7. Tests

- [x] 7.1 Substrate tests: identity issuance/rotation, report ingestion (incl. unknown/expired tokens), RSSI bucketing hysteresis, and pair fusion/confidence from one- vs two-directional reports.
- [x] 7.2 Plausibility/anti-cheat tests: rate limiting, impossible-crowd and expired-ID filtering, and that on-device claims cannot bypass server-computed energy.
- [x] 7.3 Economy tests: drain, safety-in-numbers vs area-drain, full-drain flip (flip vs die), reverse numbers game (N wizards hold a dementor for T → flip), two-way conversion, and stale-report ticks applying no drain.
- [x] 7.4 Config tests: per-Session overrides beat Game defaults for every dementor knob; `require_ble_capable` gate admits/refuses correctly.
- [x] 7.5 Simulated-swarm harness: synthesize reports for ~100 identities and assert tick correctness and performance bounds; keep branch coverage ≥80% and ruff-clean.

## 8. Real-park pilot validation

- [ ] 8.1 Run a pilot in a real park with mixed Android + iPhone devices: measure detection latency, false-positive/negative rates, and BLE range on foreground/screen-on phones; tune the RSSI bucket thresholds and drain-range bucket from field data.
- [ ] 8.2 Scale + battery check: exercise toward ~100 participants, measure report-batch sizes, tick load, and battery burn from continuous advertise+scan+screen-on; confirm the mode meets its detection and fairness targets before general availability, and record the pilot results.

## Implementation notes

- **Fork point**: this branch forked from `43d3080` (before the
  points-repository-and-collections merge), so `Tower.game`/`Zone.game` still
  exist here. That is fine — this change touches no geometry; the merger only
  needs to renumber migrations (`game/0023_ble_proximity_dementors`,
  `organize/0017_dementors_ble_config` will collide with the parallel chains
  ending at `game/0025` / `organize/0017` on `openspec-impl`).
- **No scheduler dependency (deviation-free but worth flagging)**: the economy
  tick runs deterministically inside report ingestion (`run_tick(session)` in
  `game/dementors.py`, invoked from `POST /api/proximity/reports/`), elapsed-
  time-scaled via `DementorState.last_tick_at`. No celery/cron was added.
- **5.3 Channels push — NOT done**: Django Channels is not part of this
  codebase (no channels/ASGI in `requirements.txt` or `geogame/settings.py`).
  Polling (`GET /api/dementors/me/` at 3s, staff totals at 5s) is the shipped
  mechanism, matching the design's "polling remains a graceful fallback".
  Wire push when Channels infra lands project-wide.
- **6.3 native BLE bridge — NOT done in this repo**: Web Bluetooth cannot
  advertise, so a browser SPA cannot be the beacon. Delivered instead as a
  strict API contract (`/api/proximity/identity|reports|capability/`) plus a
  debug simulator panel on the player Dementors screen that exercises the
  exact contract with synthetic observations. The native advertise/scan shell
  is a separate mobile build per design.md's migration plan step 4.
- **6.2 wake lock**: best-effort `navigator.wakeLock.request('screen')` while
  the Dementors screen is open, re-acquired on visibilitychange, released on
  destroy; unsupported browsers fall back to the prominent "phone out, screen
  on" banner. `reports_stale` from `/api/dementors/me/` drives the stale-report
  warning alert.
- **6.4**: role totals + per-player table (tablet-friendly) shipped; the
  *optional* map view was skipped (no per-player GPS surface in this mode —
  proximity is deliberately non-geographic).
- **Section 8 (real-park pilot) — intentionally unchecked**: field validation
  with real mixed Android/iPhone hardware cannot be performed by an agent; RSSI
  bucket thresholds (`game/proximity.py` `BUCKET_THRESHOLDS`) and cadence knobs
  are config so the pilot can tune without code changes.
- **Coverage**: `test game organize` → 439 tests, 95% branch coverage. The
  CLAUDE.md CI command (`test game` only) reports 75% — the fork point
  `43d3080` already measures 71% under that command because staff endpoints in
  `organize/api.py` are tested from `organize/tests.py`; not a regression from
  this change (new modules: `game/dementors.py` 99%, `game/proximity.py` 95%,
  `game/proximity_api.py` 93%).
- **Merge conflict hotspots**: `game/models.py` (four new models appended),
  `organize/models.py` (21 knobs + `OVERRIDABLE_CONFIG_FIELDS` entries +
  session-start hook call), `organize/api.py` (`CurrentSessionSerializer.
  dementors_enabled`, staff Game/Session serializer knob lists), `geogame/
  urls.py` (5 new routes), `game/admin.py`, `game/tests.py` (appended test
  classes), migration numbering. Frontend: `app.routes.ts`/`app.html` in both
  SPAs (additive nav/route entries), `shared/src/public-api.ts`.
