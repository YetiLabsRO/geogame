## 1. Backend: badge & gateway registry + provisioning

- [ ] 1.1 Add `game.BadgeDevice` (opaque on-air `badge_id`, hardware MAC, `firmware_version`, `battery_pct`, `status`, `last_seen_at`) with admin + migration.
- [ ] 1.2 Add `game.GatewayNode` (id, `transport` WIFI/CELLULAR/TABLET, per-gateway token/key, `last_seen_at`, coverage note) with admin + migration.
- [ ] 1.3 Add `game.BadgeAssignment` binding a `BadgeDevice` to a `Player`/`Team` for a `Session` (assigned_at / released_at) with admin + migration.
- [ ] 1.4 Add `game.BadgeTelemetry` (battery, activity class, IMU sample, `recorded_at`, FK to `BadgeDevice`) with migration.
- [ ] 1.5 Staff provisioning endpoints under `/api/staff/badges/` and `/api/staff/gateways/`: register, list/inventory, hand-out (create assignment), collect (release assignment), and low-battery/stale flags.

## 2. Backend: gateway ingest + server-authoritative processing

- [ ] 2.1 Define and version the gateway↔server wire protocol (proximity batch: `[badge_id, seen_badge_id, rssi, counter, ts]`; telemetry batch; per-badge state response).
- [ ] 2.2 `POST /api/gateway/ingest/`: authenticate the gateway (per-gateway token), validate protocol version, dedupe by `badge_id + counter/ts`.
- [ ] 2.3 Resolve `badge_id → BadgeAssignment` and translate badge-observed proximity into the `ProximityEvent` substrate tagged source `BADGE` (see the `ble-proximity` capability), feeding the same energy economy as phone BLE (see the `mode-dementors` capability).
- [ ] 2.4 Map raw RSSI → server-side range buckets using the Session's proximity threshold (server owns ranging policy); persist telemetry to `BadgeTelemetry` and dead-reckoned positions to `LocationPing`.
- [ ] 2.5 Return per-badge authoritative state (energy, role, active effects) in the ingest response for gateways to re-broadcast.
- [ ] 2.6 Reject/ignore any badge- or gateway-asserted game outcome; only observations are accepted, the server decides outcomes.

## 3. Firmware: badge (ESP32-C3)

- [ ] 3.1 ESP-NOW beacon: periodically broadcast `badge_id` + rolling counter; log heard ids + RSSI into a short observation buffer.
- [ ] 3.2 Optional Long-Range (LR) mode toggle for wider fields; document the range/throughput trade-off.
- [ ] 3.3 RGB ring driver: render energy level + role from last server-pushed state; hold last-known state and show a "stale/disconnected" pattern when the gateway link is lost.
- [ ] 3.4 IMU integration: gesture recognition (cast/drain flick → gesture event), activity classification (running / standing / still), and short-horizon dead-reckoning; report these, do not act on them locally.
- [ ] 3.5 Apply per-badge state addressed to this badge from gateway downlink broadcasts.
- [ ] 3.6 Power management: duty-cycle radio + ring; sample and report `battery_pct`; low-battery ring indication.
- [ ] 3.7 Optional BLE phone-presence: advertise/scan for a paired phone so the phone MAY be present-but-backgrounded without owning detection.

## 4. Firmware/app: gateway relay

- [ ] 4.1 Gateway firmware/app joins the ESP-NOW field, collects badge observation + telemetry batches, and holds a per-gateway credential.
- [ ] 4.2 Uplink: batch and POST observations to `/api/gateway/ingest/` over WiFi/4G (or tablet network); buffer and retry when offline.
- [ ] 4.3 Downlink: fetch per-badge state and re-broadcast it onto the mesh for badges to apply.
- [ ] 4.4 Software gateway simulator (server-side test harness) that emits synthetic proximity/telemetry so the backend can be exercised end-to-end before physical units exist.

## 5. Provisioning tooling (staff app)

- [ ] 5.1 Inventory view: register devices/gateways, see battery + last-seen + firmware version, flag stale/low-battery/un-returned.
- [ ] 5.2 Hand-out flow: bind a badge to a player/team for a Session (create `BadgeAssignment`); scan/select badge, confirm assignment.
- [ ] 5.3 Collect flow: release assignments at end-of-event; report any un-returned badges.

## 6. Hardware pilot

- [ ] 6.1 Produce a bill of materials and a costed build plan (~$14/unit at 100 units as an ESTIMATE; capture NRE separately) in `design.md` and a spreadsheet.
- [ ] 6.2 Build a small pilot batch (e.g. 10–20 units) of ESP32-C3 badges + 2–3 gateways.
- [ ] 6.3 Field test: run a `mode-dementors` Session with phones off/absent, gateways covering the field; measure RSSI→range behaviour, ring readability, latency, and battery life over a full event.
- [ ] 6.4 Capture findings (range buckets, gateway count/placement, battery duty-cycle) and feed tuning back into server-side ranging config and firmware.

## 7. Tests

- [ ] 7.1 Ingest tests: gateway auth required; protocol-version validation; dedupe by `badge_id + counter`; badge-asserted outcomes ignored.
- [ ] 7.2 Substrate tests: badge-relayed proximity produces `ProximityEvent` records tagged `BADGE` that drive the same energy economy as phone BLE (parity test against the phone path).
- [ ] 7.3 Provisioning tests: hand-out creates an assignment resolving `badge_id → player/team/session`; collect releases it; opaque `badge_id` never exposes a real identity on the air.
- [ ] 7.4 Ranging tests: RSSI maps to server-side range buckets per Session threshold; noisy RSSI is smoothed, not treated as metric distance.
- [ ] 7.5 Telemetry tests: battery/activity/IMU samples persist to `BadgeTelemetry`; low-battery and stale-firmware flags surface in inventory.
