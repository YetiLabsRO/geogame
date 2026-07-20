## Context

The `mode-dementors` game (wizards vs dementors: a dementor within radio range drains a wizard's energy; a full drain flips the wizard's role; safety-in-numbers reverses it) is server-authoritative and rides on the `ble-proximity` capability: phones advertise an id and report the ids + RSSI they see, and the server runs the energy economy. The hard constraint is that a phone must keep BLE advertising **and** scanning in the foreground — brutal on iOS, awkward on Android, and terrible UX ("hold your phone up for 40 minutes"). This change moves the radio and the display off the phone and onto a cheap dedicated **wearable badge**, and lets a handful of **gateway** nodes carry data to the server, so phones become optional.

The badge is not a new game — it is a new **transport**. Everything it observes lands in the same `ProximityEvent`/energy-economy substrate the phone path uses; the server is still the only thing that decides who drains whom. That keeps `mode-dementors` (and future proximity modes) transport-agnostic: a Session can run all-phone, all-badge, or mixed.

## Goals / Non-Goals

**Goals:**
- Make the phone **optional** during proximity play: the badge is the always-on radio + glanceable energy/role light; the phone MAY be present but off/backgrounded, or absent entirely when gateways cover the field.
- Badges detect each other **directly** over ESP-NOW (no pairing, no router, no phone in the loop), forming a proximity mesh; RSSI gives a coarse distance for the "in range" / drain threshold.
- A few gateway nodes relay badge-observed proximity + telemetry to the server and push server-authored per-badge state back down.
- Keep the server **authoritative**: badges/gateways transport and display, they never decide game outcomes.
- Support a **provisioned** operating model: hand devices out at the start, collect them at the end, with inventory and per-Session assignment.
- IMU adds mechanics (gesture cast/drain, activity detection for energy/stamina) and cheap dead-reckoning to smooth position between updates.

**Non-Goals:**
- Replacing the phone-BLE path or the `mode-dementors` energy rules — this is an additional transport into the same substrate, not a rules change.
- Consumer retail / take-home hardware, per-user pairing, or an app-store BLE peripheral — the model is on-site hand-out/collect.
- Precise indoor positioning. RSSI is deliberately coarse; short range is a *feature* (it defines "in range"), and dead-reckoning only smooths between authoritative updates.
- Certification (FCC/CE) and mass manufacturing — the pilot is self-built units; certification is a later, separate effort.

## Decisions

- **ESP32-C3 as the badge MCU.** Cheap, integrated 2.4 GHz radio (BLE 5 + ESP-NOW on the same radio), low power, plenty of GPIO for an addressable RGB ring and an I2C IMU. Alternative considered: nRF52 (better BLE, no ESP-NOW) — rejected because ESP-NOW is the whole point (connectionless mesh with no pairing/phone).
- **ESP-NOW for badge-to-badge detection.** Espressif's connectionless protocol on the WiFi radio: no router, no pairing, ~250-byte packets, low power. Each badge periodically broadcasts a small beacon (its badge id + a rolling counter); every badge logs the ids it hears and the RSSI. Realistic reliable range in a crowded park is tens of meters — which is what we *want*: short range defines "in range", and RSSI estimates distance for the drain threshold. **Long-Range (LR) mode** is available as a per-deployment option for wider/sparser fields at the cost of throughput.
- **RSSI as coarse ranging, not precise distance.** The badge reports raw RSSI; the *server* maps RSSI→"in drain range" using the Session's `proximity_meters`-style threshold, so ranging policy stays server-side and tunable per Session (consistent with the config pattern used elsewhere). Alternative considered: on-badge distance decisions — rejected because it would move authority onto the device.
- **RGB ring is a pure display of server state (with a local fallback).** The ring shows energy level (e.g. brightness/fill) and role (e.g. warm = wizard, cold = dementor) so the wearer gets a glanceable read without a phone. The badge renders whatever state the server last pushed; if the gateway link drops, it holds last-known state and shows a "stale/disconnected" pattern rather than inventing new state.
- **IMU (accelerometer + gyro) drives three things.** (1) **Gesture actions** — a recognizable motion (e.g. a "cast" flick) emits a gesture event the server can act on (cast/drain); (2) **activity detection** — running / standing / still classification feeding energy & stamina rules; (3) **dead-reckoning** — short-horizon step/heading integration to smooth position between GPS/proximity updates. Gestures/activity are *reported* to the server; the server decides their effect.
- **Gateways are thin relays, not brains.** A gateway (ESP32 + WiFi/4G, or an organizer's tablet running a relay app) sits on the ESP-NOW mesh, batches what the badges observed, and POSTs it to the server; then it fetches per-badge authoritative state and re-broadcasts it onto the mesh for the badges to apply. Alternative considered: every badge has its own uplink (WiFi/4G) — rejected on cost, power, and SIM logistics.
- **Backend ingest reuses the proximity substrate.** The gateway ingest endpoint translates badge observations into the same `ProximityEvent` records the phone-BLE path produces (see the `ble-proximity` capability), tagging the source as `BADGE` so the energy economy in `mode-dementors` treats both transports uniformly. Telemetry (battery, activity, IMU samples) lands in `BadgeTelemetry`; dead-reckoned positions may land in `LocationPing`.
- **Provisioned hand-out/collect with per-Session binding.** A `BadgeDevice` is a durable asset; a `BadgeAssignment` binds it to a `Player`/`Team` for one `Session` at hand-out and is released at collection, so the same physical badge is reused across events. Badge identity on the air is a short opaque id resolved server-side to the assignment, so a lost/borrowed badge never leaks a real identity.
- **Gateway authentication is per-gateway.** Each gateway carries its own token/key (not a player token); the ingest endpoint authenticates the gateway, not individual badges, and trusts the server to resolve badge id → assignment.

### Bill of materials & cost envelope (ESTIMATE)

Rough per-unit BOM for a self-built badge at ~100 units. **These are planning estimates, not quotes**; component prices move and assembly adds labour.

| Item | Est. unit cost |
| --- | --- |
| ESP32-C3 module | ~$2.50 |
| Addressable RGB ring (e.g. ~12x WS2812/SK6812) | ~$2.00 |
| IMU (6-axis accel+gyro, I2C) | ~$1.50 |
| LiPo battery (~300–500 mAh) | ~$2.50 |
| Charge/protection circuit (e.g. TP4056 + protection) | ~$1.00 |
| PCB (at ~100-unit panelized run) | ~$1.50 |
| Enclosure + wrist strap | ~$2.00 |
| Passives, connectors, misc | ~$1.00 |
| **Estimated total** | **~$14/unit** |

- **Cost is sensitive to volume and assembly.** ~$14/unit assumes self-assembly at 100 units; hand-assembly labour, higher-quality straps/enclosures, or smaller runs push it up.
- **Non-recurring engineering (NRE)** — one-time, not per unit: PCB design + layout, firmware development (badge + gateway), a small assembly jig, and field-test iterations. Treat NRE as a fixed project cost amortized over the fleet, separate from the per-unit envelope. **Certification (FCC/CE) is deliberately out of scope** for the pilot and would be additional NRE later.
- **Gateways** are a handful per field (a few units), so their cost is negligible against the badge fleet; an organizer tablet running the relay app can stand in for a dedicated gateway.

### ESP-NOW mesh + gateway topology

- **Badges** broadcast short beacons and passively log heard ids + RSSI; they do not route each other's traffic (avoiding a full routing mesh keeps power and complexity down). "Mesh" here means a dense field of peers that all hear each other within range, plus gateways that skim the field — not multi-hop routing.
- **Gateways** are placed to cover the play area (a few nodes for a park); each hears the badges near it, batches observations, and uplinks. Overlapping gateway coverage is fine (dedupe server-side by badge id + timestamp/counter). More gateways = better coverage + faster state propagation.
- **Downlink**: the server's per-badge state (energy, role, effects) is fetched by gateways and re-broadcast on the mesh; badges apply the state addressed to their id and update the ring. Latency target is a few seconds end-to-end, acceptable for the energy economy.

## Risks / Trade-offs

- [Gateway coverage gaps mean some badge observations never reach the server] → Place enough gateways for the field, allow overlap, and have badges buffer recent observations to opportunistically flush when any gateway is in range; the server dedupes.
- [RSSI is noisy — reflections and bodies swing it a lot] → Keep ranging coarse and server-side; smooth RSSI over a short window and map to a few range buckets rather than metric distance; the drain threshold is a bucket, not a precise radius.
- [Phones-optional removes the per-user identity/consent surface a phone provides] → Bind identity at hand-out via `BadgeAssignment`; the on-air badge id is opaque; consent/roster is handled at provisioning time, not on the badge.
- [Battery life over a multi-hour event] → Duty-cycle the radio and ring, report battery telemetry, surface low-battery in the staff inventory view, and provision spares/chargers; the collect step recharges for the next event.
- [Lost or walked-off devices in a provisioned fleet] → Inventory + assignment tracking flags un-returned badges at collection; opaque ids limit any data exposure; badges hold no durable personal data.
- [Firmware is out-of-tree and can drift from server expectations] → Version the wire protocol and record `firmware_version` per `BadgeDevice`; the ingest endpoint validates protocol version and the staff view surfaces stale firmware.
- [ESP-NOW and BLE share one radio] → Time-slice or prefer ESP-NOW for detection while keeping BLE available for optional phone-presence/pairing; document the duty-cycle in firmware.

## Migration Plan

This change is **additive** — no existing gameplay data changes.

1. Add `game.BadgeDevice`, `game.GatewayNode`, `game.BadgeAssignment`, and `game.BadgeTelemetry` models with additive migrations. No backfill needed (there is no prior badge data).
2. Extend the `ProximityEvent` source (from the `ble-proximity` substrate) to record a `BADGE` source alongside `PHONE`, so badge-relayed proximity is uniform with phone-BLE proximity for the energy economy. If `ProximityEvent` does not yet exist when this ships, the ingest endpoint provisions its records against whatever proximity substrate `ble-proximity`/`mode-dementors` land, without changing their rules.
3. Add per-gateway auth (token/key) and the `POST /api/gateway/ingest/` endpoint; add staff provisioning endpoints and the inventory view.
4. Firmware (badge + gateway) and the hardware pilot proceed out-of-tree against the frozen wire protocol; the backend can be exercised end-to-end with a software gateway simulator before physical units exist.
