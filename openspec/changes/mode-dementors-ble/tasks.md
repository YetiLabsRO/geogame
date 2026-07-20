## 1. BLE proximity substrate — models

- [ ] 1.1 Add `game.ProximityIdentity` (per player, per session: opaque `token`, `issued_at`, optional `rotates_at`, `active`) with a uniqueness constraint on the active token per session; admin + migration.
- [ ] 1.2 Add `game.ProximityReport` (reporter `ProximityIdentity` / player, `session`, `reported_at`, and a batch of observed `{token, rssi}` entries as a related model or JSON, plus `received_at`); index by session + `received_at` for freshness queries.
- [ ] 1.3 Add `game.ProximityEvent` (server-derived unordered near-pair for a session/tick: `player_a`, `player_b`, `distance_bucket`, `confidence`, `derived_at`); index by session + `derived_at`.
- [ ] 1.4 Add a `require_ble_capable` flag and BLE substrate cadence knobs (report interval, scan duty-cycle, freshness window) on `organize.Game` with nullable `organize.Session` overrides via the effective-value helper.

## 2. BLE proximity substrate — server logic & API

- [ ] 2.1 `POST /api/proximity/identity/`: issue (or rotate) the caller's ephemeral advertising token for their active session; map token→player only server-side.
- [ ] 2.2 `POST /api/proximity/reports/`: accept a batch of observed tokens + RSSI from one phone; validate/rate-limit; persist a `ProximityReport`; reject unknown/expired tokens gracefully.
- [ ] 2.3 RSSI→bucket mapper with hysteresis (VERY_CLOSE / NEAR / FAR or configurable set); no metres exposed.
- [ ] 2.4 Proximity derivation pass: from reports within the freshness window, fuse both directions of each pair into one `ProximityEvent` with a corroboration-boosted `confidence`; apply plausibility filters (rate, impossible-crowd, expired-ID).
- [ ] 2.5 BLE-capability gate: a device self-check endpoint/flag so a Game with `require_ble_capable` refuses non-BLE devices with a clear message while still admitting mixed BLE hardware.

## 3. Dementors mode — models & config

- [ ] 3.1 Add `game.DementorState` (per player per session: `role` WIZARD/DEMENTOR, `energy`, `last_tick_at`, flip/convert history, `alive`).
- [ ] 3.2 Add dementor config on `organize.Game` + nullable `organize.Session` overrides (drain rate, drain-range bucket, starting energy, `flip_on_empty` vs `die_on_empty`, `safety_in_numbers` vs area-drain, reverse-game group size `N` + hold duration `T`, conversion threshold, tick cadence); resolve via the effective-value helper.
- [ ] 3.3 Session start hook: assign initial WIZARD/DEMENTOR roles and starting energy per config.

## 4. Dementors mode — server economy tick

- [ ] 4.1 Tick job: read current `ProximityEvent`s in the drain-range bucket, apply drain to wizards near dementors, and apply gain/regeneration per config; write `DementorState` atomically.
- [ ] 4.2 Safety-in-numbers vs area-drain: divide a clustered wizard's effective drain by nearby-wizard count, or drain all in range at full rate, per config.
- [ ] 4.3 Full-drain flip: a wizard reaching empty flips to dementor or dies per `flip_on_empty`/`die_on_empty`.
- [ ] 4.4 Reverse numbers game: when ≥`N` wizards keep a dementor in range continuously for `T`, flip that dementor to wizard.
- [ ] 4.5 Two-way conversion: a dementor whose energy crosses the conversion threshold flips back to wizard; record all flips with cause.

## 5. Real-time & APIs

- [ ] 5.1 `GET /api/dementors/me/`: own role, energy, and the live drain/gain delta for the current tick (polling fallback).
- [ ] 5.2 `GET /api/staff/dementors/session/{id}/totals/`: live role counts (e.g. 5 dementors / 10 wizards) and a per-player feed for a map/tablet.
- [ ] 5.3 Channels push: live energy/role updates to each player and live totals to the staff dashboard; polling remains a graceful fallback.

## 6. Frontend

- [ ] 6.1 Player SPA Dementors screen: energy bar, role badge, and a real-time drain/gain pulse that signals an unseen dementor nearby.
- [ ] 6.2 Player SPA "phone out, screen on" affordance: keep the screen awake during play and prompt when reports go stale.
- [ ] 6.3 Native BLE bridge in the mobile player build: advertise the ephemeral token and scan for peers, batching seen tokens + RSSI to the report endpoint.
- [ ] 6.4 Staff SPA dashboard: live role totals plus an optional map/tablet view of players by role.

## 7. Tests

- [ ] 7.1 Substrate tests: identity issuance/rotation, report ingestion (incl. unknown/expired tokens), RSSI bucketing hysteresis, and pair fusion/confidence from one- vs two-directional reports.
- [ ] 7.2 Plausibility/anti-cheat tests: rate limiting, impossible-crowd and expired-ID filtering, and that on-device claims cannot bypass server-computed energy.
- [ ] 7.3 Economy tests: drain, safety-in-numbers vs area-drain, full-drain flip (flip vs die), reverse numbers game (N wizards hold a dementor for T → flip), two-way conversion, and stale-report ticks applying no drain.
- [ ] 7.4 Config tests: per-Session overrides beat Game defaults for every dementor knob; `require_ble_capable` gate admits/refuses correctly.
- [ ] 7.5 Simulated-swarm harness: synthesize reports for ~100 identities and assert tick correctness and performance bounds; keep branch coverage ≥80% and ruff-clean.

## 8. Real-park pilot validation

- [ ] 8.1 Run a pilot in a real park with mixed Android + iPhone devices: measure detection latency, false-positive/negative rates, and BLE range on foreground/screen-on phones; tune the RSSI bucket thresholds and drain-range bucket from field data.
- [ ] 8.2 Scale + battery check: exercise toward ~100 participants, measure report-batch sizes, tick load, and battery burn from continuous advertise+scan+screen-on; confirm the mode meets its detection and fairness targets before general availability, and record the pilot results.
