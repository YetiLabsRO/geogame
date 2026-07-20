## Why

The product wants a phone-to-phone **proximity** game with no fixed venue hardware: a Harry-Potter-themed chase played across a park where **wizards** flee **dementors**, and being physically near a dementor drains your magic. The distinguishing idea is that proximity is *wireless, not line-of-sight* — hiding behind a tree does not save you. An early exploration used WiFi SSIDs for phone-to-phone sensing; that idea is **dropped** because iOS forbids the required WiFi APIs. The feasible substrate is **Bluetooth Low Energy (BLE)**: each phone advertises an identity and reports the identities and signal strengths it can hear. This change is also the **proof-of-concept for phone-to-phone proximity** that later modes and the wearable badge build on, so it is split into a reusable substrate (`ble-proximity`) plus the game rules (`mode-dementors`). Because BLE and RSSI are unreliable and spoofable on uncontrolled consumer phones, the economy must be **server-authoritative**: phones are sensors, the server is the single source of truth.

## What Changes

- Add a **`ble-proximity`** capability: a generic, server-authoritative BLE proximity substrate. Each player is issued a per-session **ephemeral advertising identity**; the app advertises it over BLE and periodically **reports the identities + RSSI it observes** to the server; the server derives **who-is-near-whom** as `ProximityEvent`s. Raw phone submissions are stored as `ProximityReport`s and treated as untrusted inputs.
- Add a **`mode-dementors`** capability: an energy/role game built on `ble-proximity`. Players start as **WIZARD** or **DEMENTOR**; each player carries an **energy** value; a server tick applies **drain** (dementor near wizard) and **gain/regeneration** rules, flips roles on full drain, and supports **safety-in-numbers**, an **area-drain** alternative, a **reverse numbers game** (a group of wizards holds dementors long enough to flip them), and **two-way conversion** (enough restored energy turns a dementor back into a wizard).
- Add gameplay config knobs on `Game` with nullable per-`Session` overrides (drain rate, thresholds, group rules, flip-vs-die, conversion rules, tick cadence, report cadence, whether BLE-capable phones are required).
- **Player app**: live view of own energy level, role, and a real-time drain/gain indicator (so a player notices an unseen dementor nearby). **Staff app**: live totals (e.g. "5 dementors / 10 wizards"), optionally on a map/tablet dashboard.
- New models: `game.ProximityIdentity`, `game.ProximityReport`, `game.ProximityEvent` (substrate) and `game.DementorState` (per-player energy/role) plus `game.DementorConfig`-style knobs on `Game`/`Session`.
- New DRF endpoints for advertising-identity issuance, proximity reporting, energy/role polling, and staff totals; Channels push for live energy/role updates and the staff dashboard (graceful polling fallback).
- A **real-park pilot** validation task on mixed Android + iPhone devices at ~100-person scale.

## Capabilities

### New Capabilities
- `ble-proximity`: a server-authoritative BLE proximity substrate — phones advertise an ephemeral ID and report seen IDs + RSSI, and the server derives who-is-near-whom.
- `mode-dementors`: a wizards-vs-dementors energy/role game built on BLE proximity, with server-run drain/gain economy, role flips, and group mechanics.

### Modified Capabilities
<!-- None -->

## Impact

- **Models**: new `game.ProximityIdentity` (per player, per session, rotating ephemeral BLE ID), `game.ProximityReport` (raw observed-ID + RSSI batch from one phone), `game.ProximityEvent` (server-derived near-pair with a coarse distance bucket and confidence), `game.DementorState` (per player: role, energy, last-tick bookkeeping, flip history); dementor config fields on `organize.Game` with nullable `organize.Session` overrides resolved by the effective-value helper.
- **APIs**: `POST /api/proximity/identity/` (issue/rotate advertising ID), `POST /api/proximity/reports/` (submit a batch of seen IDs + RSSI), `GET /api/dementors/me/` (own energy + role + live delta), `GET /api/staff/dementors/session/{id}/totals/` (role counts + map feed); websocket channels for live energy/role and the staff dashboard.
- **Frontend**: player SPA gains a Dementors game screen (energy bar, role badge, drain/gain pulse, "keep your phone out and screen on" prompt) plus the native BLE advertise/scan bridge; staff SPA gains a live totals + optional map/tablet dashboard.
- **Migrations/other**: additive migrations for the new models and config fields; no changes to existing gameplay defaults. Native BLE requires a device build (advertising + scanning) — encoded as a constraint, not a Django dependency. A real-park pilot is required before general availability.
