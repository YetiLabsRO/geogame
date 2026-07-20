## Why

Phone-only BLE proximity (see the `ble-proximity` and `mode-dementors` capabilities introduced by the sibling `mode-dementors-ble` change) works, but leans on a phone that must keep its radio advertising and scanning in the foreground — the iOS background-BLE restriction in particular makes "hold your phone up the whole game" the failure mode. This change adds an **optional** ESP32-C3 **wearable badge** (wrist/watch form) that owns the radio and a glanceable RGB ring display, so the phone can be merely *present* (in a pocket, off, or absent) rather than on and foreground. The badges detect each other **directly** over ESP-NOW — a connectionless, no-pairing, no-router 2.4 GHz protocol — forming their own proximity mesh, while a few gateway nodes relay to the Django backend. The server stays the single source of truth for the energy economy and role flips; the badge is just an always-on sensor plus a light. This is a **provisioned** model: the company is on-site to hand out and collect devices.

## What Changes

- Introduce a new `wearable-badge` capability: an optional ESP32-C3 wearable (RGB ring, IMU, battery, Bluetooth + 2.4 GHz radio) that acts as an always-on proximity radio and a glanceable energy/role display, as an **alternate transport** for proximity games feeding the same server-authoritative substrate as phone BLE.
- **Firmware behaviour**: ESP-NOW badge-to-badge detection (no pairing, no phone in the loop) with RSSI used as a coarse distance estimate for the "in range" / drain threshold; Long-Range (LR) mode as an option for wider fields; an RGB ring that shows the wearer their energy level and role state; IMU-driven gesture actions (cast/drain), activity detection (running / standing / still) for energy & stamina rules, and cheap dead-reckoning to smooth position between GPS/proximity updates; low-power duty cycling and battery telemetry.
- **Gateway relay**: a small number of gateway nodes (ESP32 + WiFi/4G, or organizer tablets) that collect badge-observed proximity + telemetry off the mesh and relay batches to the server, and push server-authored per-badge state (energy, role, effects) back down to the badges.
- **Backend ingest**: an authenticated ingest endpoint that accepts gateway-relayed proximity/telemetry batches, feeds them into the same `ProximityEvent`/energy-economy substrate the phone-BLE path uses, and returns per-badge authoritative state for the gateways to distribute. The server owns game logic; badges and gateways never decide outcomes.
- **Provisioning**: registry models for physical badges and gateways, and a hand-out/collect assignment binding a badge to a player/team for a Session, with inventory and asset tracking; phones become fully optional during play when gateway coverage is present.

## Capabilities

### New Capabilities
- `wearable-badge`: an optional ESP32-C3 wearable badge (ESP-NOW proximity mesh + RGB ring + IMU) with gateway relay and a backend ingest endpoint, as an alternate always-on transport for server-authoritative proximity games.

### Modified Capabilities
<!-- None. This change references the `ble-proximity` and `mode-dementors` capabilities (introduced by the sibling `mode-dementors-ble` change) in prose as the substrate it feeds, but does not modify their specs; the badge is an additional transport, not a change to the phone-BLE path. -->

## Impact

- **Models**: new `game.BadgeDevice` (physical badge registry: hardware id/MAC, firmware version, battery, status), `game.GatewayNode` (gateway registry: id, transport, last-seen, coverage note), `game.BadgeAssignment` (binds a `BadgeDevice` to a `Player`/`Team` for a `Session` at hand-out, released at collection), and `game.BadgeTelemetry` (battery/activity/IMU samples). Badge-observed proximity is written into the existing `game.ProximityEvent` substrate rather than a new proximity model.
- **APIs**: new `POST /api/gateway/ingest/` (gateway-authenticated batch ingest of proximity + telemetry, returns per-badge state), gateway-facing state fetch, and staff provisioning endpoints under `/api/staff/badges/` and `/api/staff/gateways/` (register, assign/hand-out, collect, inventory).
- **Firmware/hardware**: new ESP32-C3 badge firmware and gateway relay firmware/app (out-of-tree hardware artifacts referenced by the repo); a bill of materials and cost envelope (~$14/unit self-built at 100 units, an estimate) plus non-recurring engineering (NRE) captured in `design.md`.
- **Frontend**: staff app gains a provisioning/inventory view (register devices, hand out to players, collect, monitor battery/last-seen).
- **Migrations/other**: additive migrations for the four new `game` models; new gateway auth mechanism (per-gateway token/key); no changes to existing gameplay data.
