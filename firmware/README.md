# Wearable badge firmware (wearable-badge-hardware)

Firmware scaffold for the optional ESP32-C3 wearable badge and its gateway
relay — the hardware transport behind the `wearable-badge` capability (see
`openspec/changes/wearable-badge-hardware/design.md`, which is authoritative
for the architecture decisions summarized here).

The badge owns the radio and the glanceable display so the phone can be in a
pocket, off, or absent. Badges detect each other **directly over ESP-NOW**
(connectionless: no pairing, no router, no phone in the loop); a few
**gateway** nodes relay observations to the Django backend and push
server-authored display state back. The server remains the single authority
for the energy economy and role flips — nothing in this tree decides a game
outcome.

> **Status: scaffold.** This code has **not been compiled** in this
> repository (no PlatformIO toolchain in the dev environment). It is a
> credible starting point with honest `TODO(hardware)` / `TODO(pilot)`
> markers wherever real hardware is required; expect minor API-level fixes on
> the first real `pio run`. The backend can be exercised end-to-end without
> any hardware — the Django test suite includes a software gateway simulator
> that speaks this exact wire protocol against `POST /api/gateway/ingest/`.

## Layout

```
firmware/
├── common/protocol.h      # wire protocol shared by badge + gateway,
│                          # mirrored by the backend (game/badges.py)
├── badge/                 # ESP32-C3 wearable: PlatformIO project
│   ├── platformio.ini
│   ├── include/config.h   # cadences, pins, thresholds (power-on defaults)
│   └── src/
│       ├── main.cpp             # supervisor loop
│       ├── espnow_beacon.*      # beacon TX + peer/downlink RX
│       ├── neighbor_table.*     # heard ids + RSSI ring buffer
│       ├── ring_light.*         # server-state renderer + stale overlay
│       ├── imu.*                # gesture / activity / dead-reckoning stubs
│       ├── battery.*            # ADC sampling + percentage estimate
│       └── provisioning.*       # serial console (BLE stub) for badge id
└── gateway/               # ESP32 relay: PlatformIO project
    ├── platformio.ini
    ├── include/config.h   # WiFi, ingest URL, per-gateway token, backoff
    └── src/
        ├── main.cpp             # collect → batch → POST → downlink loop
        ├── espnow_collector.*   # report RX ring buffer + downlink TX
        └── uplink.*             # HTTP/JSON with batching + backoff
```

## Building & flashing

Requires [PlatformIO](https://platformio.org/) (`pipx install platformio`).

```bash
# Badge (ESP32-C3, native USB-CDC)
cd firmware/badge
pio run                    # build
pio run -t upload          # flash
pio device monitor -b 115200

# Gateway (generic ESP32 devkit)
cd firmware/gateway
pio run
pio run -t upload
```

Before building the gateway, set the per-site values in
`gateway/include/config.h`: WiFi credentials, the backend ingest URL, and the
**per-gateway token** (register the gateway in the staff app's *Badges* panel
or `POST /api/staff/gateways/` — the token is shown in the fleet view).

## Provisioning flow

1. **Register** the badge in the backend: staff app → *Badges* → *Register
   badge* (or `POST /api/staff/badges/`). The backend mints the opaque 8-char
   on-air `badge_id`.
2. **Write the id into the badge** over USB serial (115200):

   ```
   PROV id=aa110001
   PROV show
   ```

   The id persists in NVS; reboot to apply. An unprovisioned badge blinks
   idle and refuses to join the mesh. (A BLE provisioning channel is stubbed
   in `provisioning.h` for later; serial is fine for a hand-built pilot
   fleet.)
3. **Hand out**: staff bind the badge to a player/team for a Session in the
   fleet panel. From that moment observations of the badge id resolve
   server-side to that player — the id itself never carries identity, so a
   lost or swapped badge leaks nothing.
4. **Collect**: staff release the binding at the end of the event (the panel
   flags un-returned badges once the session finishes); recharge and reuse.

## Mesh + gateway topology

- **Badges** broadcast a small beacon (`badge_id` + rolling counter) about
  once per second and passively log the ids + RSSI they hear. There is **no
  multi-hop routing** — "mesh" means a dense field of peers plus gateways
  that skim it. Badges buffer observations and flush them toward any gateway
  in range every report interval (default 10 s).
- **Gateways** (a few per park) batch what they hear and POST it to
  `/api/gateway/ingest/`, then re-broadcast the response's per-badge display
  state; badges apply only the packet addressed to their own id.
  Overlapping gateway coverage is *good* — the server dedupes by
  `(badge, seen badge, beacon counter)`.
- **Channel discipline**: ESP-NOW and the gateway's WiFi uplink share one
  radio, so the AP's channel dictates the mesh channel. Pin the venue AP
  channel, or use a 4G/tablet uplink. Badge fleet and gateways must also
  agree on Long-Range mode (below).
- **Downlink latency** is a few seconds end-to-end (flush interval + tick),
  which is fine for the energy economy; the ring overlays a distinct stale
  pattern when the downlink goes quiet for 30 s, and never invents state.

## RSSI → range expectations

RSSI is a **coarse, server-interpreted** signal — the badge reports raw dBm
and the server maps it to ordinal buckets (`VERY_CLOSE` / `NEAR` / `FAR`)
using the Session's thresholds, with smoothing/hysteresis server-side. Never
treat it as metric distance.

| Regime | Ballpark | Notes |
| --- | --- | --- |
| VERY_CLOSE (default ≥ -55 dBm) | ~arm's length–3 m | body shadowing swings ±10 dB |
| NEAR (default ≥ -75 dBm) | ~3–15 m | the default drain-range bucket |
| FAR (weaker) | out to tens of m | reliable detection limit in a crowd |
| ESP-NOW default mode | ~30–80 m open park | antenna + crowd dependent |
| ESP-NOW Long-Range (LR) mode | several hundred m line-of-sight | reduced throughput; all-or-nothing fleet-wide |

These are planning numbers; the hardware pilot (tasks 6.x) measures real
curves and feeds tuning back into the Session config — no firmware change
needed, the thresholds live server-side.

## Bill of materials & cost envelope (ESTIMATE)

From `design.md` — **planning estimates, not quotes** (~100-unit self-built
run; prices move and assembly adds labour):

| Item | Est. unit cost |
| --- | --- |
| ESP32-C3 module | ~$2.50 |
| Addressable RGB ring (~12x WS2812/SK6812) | ~$2.00 |
| IMU (6-axis accel+gyro, I2C) | ~$1.50 |
| LiPo battery (~300–500 mAh) | ~$2.50 |
| Charge/protection circuit (TP4056 + protection) | ~$1.00 |
| PCB (~100-unit panelized run) | ~$1.50 |
| Enclosure + wrist strap | ~$2.00 |
| Passives, connectors, misc | ~$1.00 |
| **Estimated total** | **~$14/unit** |

Non-recurring engineering (PCB layout, firmware, assembly jig, field-test
iterations) is a separate one-time cost amortized over the fleet;
FCC/CE certification is deliberately out of scope for the pilot. Gateways
are a handful of units per field (or an organizer tablet running a relay
app), negligible against the badge fleet.

## Protocol versioning

`common/protocol.h` (`kProtocolVersion`) and the backend
(`game/badges.py` `GATEWAY_PROTOCOL_VERSION`) must agree; the ingest endpoint
rejects mismatches with HTTP 400 so stale firmware fails loudly. Badges
report their `firmware_version` in telemetry and the staff fleet panel flags
versions that drift from the backend's expected release.
