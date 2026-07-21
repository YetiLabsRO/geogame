## 1. Backend: badge & gateway registry + provisioning

- [x] 1.1 Add `game.BadgeDevice` (opaque on-air `badge_id`, hardware MAC, `firmware_version`, `battery_pct`, `status`, `last_seen_at`) with admin + migration.
- [x] 1.2 Add `game.GatewayNode` (id, `transport` WIFI/CELLULAR/TABLET, per-gateway token/key, `last_seen_at`, coverage note) with admin + migration.
- [x] 1.3 Add `game.BadgeAssignment` binding a `BadgeDevice` to a `Player`/`Team` for a `Session` (assigned_at / released_at) with admin + migration.
- [x] 1.4 Add `game.BadgeTelemetry` (battery, activity class, IMU sample, `recorded_at`, FK to `BadgeDevice`) with migration.
- [x] 1.5 Staff provisioning endpoints under `/api/staff/badges/` and `/api/staff/gateways/`: register, list/inventory, hand-out (create assignment), collect (release assignment), and low-battery/stale flags.

## 2. Backend: gateway ingest + server-authoritative processing

- [x] 2.1 Define and version the gateway↔server wire protocol (proximity batch: `[badge_id, seen_badge_id, rssi, counter, ts]`; telemetry batch; per-badge state response).
- [x] 2.2 `POST /api/gateway/ingest/`: authenticate the gateway (per-gateway token), validate protocol version, dedupe by `badge_id + counter/ts`.
- [x] 2.3 Resolve `badge_id → BadgeAssignment` and translate badge-observed proximity into the `ProximityEvent` substrate tagged source `BADGE` (see the `ble-proximity` capability), feeding the same energy economy as phone BLE (see the `mode-dementors` capability).
- [x] 2.4 Map raw RSSI → server-side range buckets using the Session's proximity threshold (server owns ranging policy); persist telemetry to `BadgeTelemetry` and dead-reckoned positions to `LocationPing`. *(Dead-reckoning payloads persist in `BadgeTelemetry.imu` — there is no `LocationPing` model in this codebase; see Implementation notes.)*
- [x] 2.5 Return per-badge authoritative state (energy, role, active effects) in the ingest response for gateways to re-broadcast.
- [x] 2.6 Reject/ignore any badge- or gateway-asserted game outcome; only observations are accepted, the server decides outcomes.

## 3. Firmware: badge (ESP32-C3)

Scaffold under `firmware/badge/` (PlatformIO, ESP32-C3, Arduino framework). NOT compiled — no PlatformIO toolchain in this environment; hardware-dependent internals carry honest TODOs. Checked items below are "scaffolded, review-ready", not "hardware-verified".

- [x] 3.1 ESP-NOW beacon: periodically broadcast `badge_id` + rolling counter; log heard ids + RSSI into a short observation buffer. *(espnow_beacon.\*, neighbor_table.\*)*
- [x] 3.2 Optional Long-Range (LR) mode toggle for wider fields; document the range/throughput trade-off. *(config.h `kLongRangeMode`; trade-off table in firmware/README.md)*
- [x] 3.3 RGB ring driver: render energy level + role from last server-pushed state; hold last-known state and show a "stale/disconnected" pattern when the gateway link is lost. *(ring_light.\*)*
- [x] 3.4 IMU integration: gesture recognition (cast/drain flick → gesture event), activity classification (running / standing / still), and short-horizon dead-reckoning; report these, do not act on them locally. *(imu.\* — pipeline shape with stub thresholds; needs the real driver + pilot tuning)*
- [x] 3.5 Apply per-badge state addressed to this badge from gateway downlink broadcasts. *(espnow_beacon.cpp downlink filter + main.cpp)*
- [x] 3.6 Power management: duty-cycle radio + ring; sample and report `battery_pct`; low-battery ring indication. *(battery.\*, ring low-batt marker; radio duty-cycling is a TODO(power) knob pending real draw measurements)*
- [ ] 3.7 Optional BLE phone-presence: advertise/scan for a paired phone so the phone MAY be present-but-backgrounded without owning detection. *(Stub entry point only — `provisioning.h BeginBleStub()`; BLE + ESP-NOW radio time-slicing needs hardware to validate, deferred to the pilot.)*

## 4. Firmware/app: gateway relay

Scaffold under `firmware/gateway/` (PlatformIO, ESP32, Arduino framework). NOT compiled — same caveat as section 3.

- [x] 4.1 Gateway firmware/app joins the ESP-NOW field, collects badge observation + telemetry batches, and holds a per-gateway credential. *(espnow_collector.\*, config.h `kGatewayToken`)*
- [x] 4.2 Uplink: batch and POST observations to `/api/gateway/ingest/` over WiFi/4G (or tablet network); buffer and retry when offline. *(uplink.\* — batching, oldest-first drop, exponential backoff)*
- [x] 4.3 Downlink: fetch per-badge state and re-broadcast it onto the mesh for badges to apply. *(uplink.cpp response parse → espnow_collector SendDownlink)*
- [x] 4.4 Software gateway simulator (server-side test harness) that emits synthetic proximity/telemetry so the backend can be exercised end-to-end before physical units exist. *(game/tests.py `_ingest`/`_obs` harness drives the exact wire protocol through the real endpoint)*

## 5. Provisioning tooling (staff app)

- [x] 5.1 Inventory view: register devices/gateways, see battery + last-seen + firmware version, flag stale/low-battery/un-returned. *(staff SPA `/badges` fleet panel, wireframe)*
- [x] 5.2 Hand-out flow: bind a badge to a player/team for a Session (create `BadgeAssignment`); scan/select badge, confirm assignment. *(per-row "Hand out" inline form; id-based select — QR scan is future polish)*
- [x] 5.3 Collect flow: release assignments at end-of-event; report any un-returned badges. *(per-row Collect / Lost actions; un-returned rows highlighted once the session finishes)*

## 6. Hardware pilot

6.2–6.4 are real-hardware tasks that cannot be performed in this environment; left unchecked deliberately (6.1 is documentation and is done).

- [x] 6.1 Produce a bill of materials and a costed build plan (~$14/unit at 100 units as an ESTIMATE; capture NRE separately) in `design.md` and a spreadsheet. *(BOM + NRE captured in design.md and mirrored in firmware/README.md, all marked ESTIMATE; no spreadsheet — a repo-committed table serves the same purpose without a binary artifact.)*
- [ ] 6.2 Build a small pilot batch (e.g. 10–20 units) of ESP32-C3 badges + 2–3 gateways. *(Physical build — out of scope for an agent.)*
- [ ] 6.3 Field test: run a `mode-dementors` Session with phones off/absent, gateways covering the field; measure RSSI→range behaviour, ring readability, latency, and battery life over a full event. *(Requires the pilot batch.)*
- [ ] 6.4 Capture findings (range buckets, gateway count/placement, battery duty-cycle) and feed tuning back into server-side ranging config and firmware. *(Requires 6.3; the tuning surface already exists — Session-effective `ble_rssi_*` knobs, no code change needed.)*

## 7. Tests

- [x] 7.1 Ingest tests: gateway auth required; protocol-version validation; dedupe by `badge_id + counter`; badge-asserted outcomes ignored. *(GatewayIngestAuthTest, GatewayIngestDedupTest, GatewayIngestTranslationTest.test_badge_asserted_outcomes_are_ignored)*
- [x] 7.2 Substrate tests: badge-relayed proximity produces `ProximityEvent` records tagged `BADGE` that drive the same energy economy as phone BLE (parity test against the phone path). *(GatewayIngestTranslationTest incl. test_parity_with_the_phone_path + test_badge_proximity_drives_the_energy_economy)*
- [x] 7.3 Provisioning tests: hand-out creates an assignment resolving `badge_id → player/team/session`; collect releases it; opaque `badge_id` never exposes a real identity on the air. *(BadgeProvisioningApiTest incl. test_on_air_downlink_payload_is_identity_free)*
- [x] 7.4 Ranging tests: RSSI maps to server-side range buckets per Session threshold; noisy RSSI is smoothed, not treated as metric distance. *(GatewayRangingTest)*
- [x] 7.5 Telemetry tests: battery/activity/IMU samples persist to `BadgeTelemetry`; low-battery and stale-firmware flags surface in inventory. *(BadgeTelemetryApiTest, GatewayDisplayStateTest)*

## Implementation notes

- **Stacked on `mode-dementors-ble`** (branch base `4b517d4`): the badge is a
  pure TRANSLATION layer over the existing substrate. Gateway ingest resolves
  each observing badge's active `BadgeAssignment` → (session, player), maps
  the *seen* badge to the seen player's `ProximityIdentity` token (issued
  lazily via the same `ProximityIdentity.issue` the phone path uses), and
  writes an ordinary `ProximityReport` with `source=BADGE`. The untouched
  `derive_proximity` + `run_tick` pipeline then does bucketing, hysteresis,
  fusion and the dementors economy — transport parity is by construction, and
  a player running badge + phone simultaneously fuses into one pair stream.
- **`ProximityEvent`/`ProximityReport` gained a `source` field**
  (PHONE default / BADGE / MIXED) instead of a parallel proximity model —
  this is the design.md "tag the source as BADGE" step. `derive_proximity`
  computes the event source from the contributing reports' sources; existing
  phone rows keep the PHONE default (fully backward compatible).
- **Fifth model beyond the proposal's four**: `BadgeObservationSeen`, a small
  dedup marker table with a unique `(badge, seen_badge, counter)` constraint
  — the DB-enforced implementation of "dedupe by badge id + rolling counter"
  across overlapping gateways (rows pruned after 15 min). Internal detail,
  no API surface.
- **Wire protocol**: JSON over `POST /api/gateway/ingest/`, authenticated by
  an `X-Gateway-Token` header (per-gateway credential, `GatewayNode.token`),
  `protocol_version` validated first (400 on mismatch, so stale firmware
  fails loudly). Mirrored in C++ in `firmware/common/protocol.h`.
- **2.4 deviation — `LocationPing`**: the task's "dead-reckoned positions to
  `LocationPing`" references a model that does not exist in this codebase
  (it belongs to the separate `live-location-tracking` change). Dead-reckoned
  payloads are stored in `BadgeTelemetry.imu` (JSON) as advisory telemetry;
  route them onward when a location capability lands.
- **Gesture events are recorded, not yet consumed**: `BadgeTelemetry.gesture`
  (CAST/DRAIN) persists per the spec ("the server SHALL decide the gesture's
  effect") — no dementors rule consumes gestures yet, so the decided effect
  is currently "none". Wiring a rule is a future mode change.
- **Firmware NOT compiled** (tasks 3.x/4.x): no PlatformIO toolchain in this
  environment; `firmware/` is a review-ready scaffold with honest
  hardware-dependent TODOs, documented in `firmware/README.md`. 3.7 (BLE
  phone-presence) is stub-only and left unchecked.
- **Downlink is identity-free**: ingest responses carry only
  `badge_id/role/energy/alive/ring` (tested), because gateways re-broadcast
  them on the open mesh. Ring state is a pure function of server state
  (`game/badges.py ring_state`).
- **Un-returned tracking**: collect releases per badge; a badge still
  assigned after its session reaches FINISHED is flagged `unreturned` in the
  inventory (and collect accepts `mark_lost` to record walk-offs).
- **No new Game/Session config knobs** — ranging reuses the existing
  Session-effective `ble_rssi_*` thresholds, so `organize/models.py` is
  untouched by this change.
- **Migration**: `game/0024_wearable_badge_hardware` (5 new models + 2
  `source` fields). Numbering will collide with parallel branches ending at
  `game/0025` on `openspec-impl` — renumber at merge as usual.
- **Merge conflict hotspots**: `game/models.py` (badge section appended after
  the dementors models + `source` fields inside ProximityReport/Event),
  `game/proximity.py` (evidence dict gained a `sources` set), `game/admin.py`
  (4 registrations appended), `geogame/urls.py` (5 routes + import block),
  `game/tests.py` (imports + appended section), migration numbering.
  Frontend: `shared/src/public-api.ts`, staff `app.routes.ts` / `app.html`
  (additive route + nav entries). New files (`game/badges.py`,
  `game/badge_api.py`, `badges.service.ts`, `admin/badges.component.ts`,
  `firmware/**`) conflict with nothing.
- **Coverage note**: `test game organize` green (483 tests = 439 baseline
  + 44 new); ruff clean; `makemigrations --check` clean; both Angular apps
  build (staff gained the `/badges` route).
