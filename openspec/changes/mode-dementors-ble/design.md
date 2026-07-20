## Context

The geogame is today a GPS/geofence domination game. This change adds a fundamentally different sensing mode: **phone-to-phone proximity** with no venue infrastructure, themed as wizards fleeing dementors across a park. The mechanic the product cares about is that proximity is *wireless and omnidirectional* — a dementor drains any wizard within radio range, through trees and bodies, not by line of sight. That "magic through obstacles, fuzzy edge" property is a good match for the physics of radio: it passes through foliage and is attenuated (not blocked) by bodies, and its distance estimate is coarse.

Two candidate substrates were weighed. **WiFi (SSID broadcast / scanning)** was explored first but is **not feasible on iOS**: Apple does not expose programmatic SSID creation or arbitrary WiFi scanning to third-party apps, so an iPhone can neither reliably beacon nor sense peers this way. **Bluetooth Low Energy (BLE)** is the feasible path: both Android and iOS let an app advertise a payload and scan for nearby advertisers, and BLE's Received Signal Strength Indicator (RSSI) gives a coarse distance proxy. The target deployment is hostile to precision: 100+ people, a public park, open participation, and an **uncontrolled mix of Android and iPhone hardware** of varying radios and OS versions. That rules out any design that assumes calibrated ranging or symmetric, always-on background radios. The design therefore splits into a reusable, server-authoritative **`ble-proximity`** substrate and the **`mode-dementors`** rules on top, so the substrate can be reused by later modes and the wearable badge.

## Goals / Non-Goals

**Goals:**
- A reusable, **server-authoritative** proximity substrate: phones are untrusted sensors that advertise an ephemeral ID and report seen IDs + RSSI; the **server** derives who-is-near-whom and owns all game state.
- A wizards-vs-dementors energy game: per-player energy, dementor-drains-wizard, full-drain role flip, safety-in-numbers, an area-drain alternative, a reverse numbers game (a group flips dementors), and two-way conversion.
- Support **mixed Android + iPhone** devices; allow a Game to **require BLE-capable phones** while still tolerating heterogeneous hardware.
- Design explicitly around **foreground-only BLE**: reliable detection needs the app in the foreground with the screen on ("phone out and active"); the UX must nudge and the economy must tolerate gaps.
- Give each player live feedback (energy, role, drain/gain) and staff live totals, optionally on a map/tablet.
- Prove it works with a **real-park pilot** before general availability.

**Non-Goals:**
- Precise ranging or true distance in metres. RSSI yields **coarse buckets** (e.g. VERY_CLOSE / NEAR / FAR), not calibrated distance.
- **Reliable background / screen-off detection**, especially iOS↔iOS, which is effectively broken for third-party apps and is out of scope; the wearable badge (`wearable-badge` change) is the always-on answer.
- The optional hardware badge itself (separate change; this substrate is what it plugs into).
- GPS/domination gameplay — orthogonal; this mode does not depend on Towers/Zones.
- Cryptographically strong anti-cheat. The server-authoritative design raises the bar and enables plausibility checks, but a determined attacker with a rooted phone is not fully defeated here.

## Decisions

- **Server-authoritative economy; phones are sensors.** Each phone reports the ephemeral IDs and RSSI values it hears; the server computes proximity, energy, and roles centrally. Alternative considered: peer-to-peer energy exchange computed on-device — rejected because it is trivially spoofable, cannot be kept consistent across 100 phones, and gives no admin ground truth.
- **Ephemeral per-session advertising identity, decoupled from user identity.** The server issues a short opaque `ProximityIdentity` token that the phone advertises; the mapping token→player lives only server-side and MAY rotate. Alternative considered: advertising a stable user ID or MAC — rejected for trivial impersonation and for privacy (persistent trackable beacons in public). Rotation also mitigates a bystander tracking players.
- **RSSI → coarse distance buckets, not metres.** The server maps RSSI to a small ordinal set of proximity buckets with hysteresis, and treats "in drain range" as a configurable bucket threshold. Rationale: RSSI varies ±several meters, is attenuated by bodies/trees, and differs by device — buckets are the honest resolution and fit the "magic through trees" theme. Alternative considered: RSSI-to-metres path-loss ranging — rejected as false precision on uncontrolled hardware.
- **Both directions of a pair are evidence, and the server fuses them.** A near-pair may be reported by A-sees-B, B-sees-A, or both. The server derives a single `ProximityEvent` per unordered pair per tick, using whichever reports exist and a confidence that rises when both sides corroborate. This tolerates one-directional deafness (common with iOS background limits or radio asymmetry).
- **Tick-based economy over a sliding freshness window.** On each server tick, the server considers only `ProximityReport`s newer than a freshness window; energy deltas are applied per tick from the currently-derived events. Stale/absent reports simply mean "no drain this tick," which naturally handles a player pocketing their phone. Cadence (report interval, tick interval, freshness window) are config knobs.
- **Config on `Game` with nullable per-`Session` overrides**, resolved by the existing effective-value helper (matches `proximity_meters` and the pause/failure knobs). Knobs include: drain rate, drain range bucket, starting energy, flip-on-empty vs die-on-empty, safety-in-numbers vs area-drain, group sizes/hold durations for the reverse game, conversion thresholds, tick/report cadence, and `require_ble_capable`.
- **Safety-in-numbers and area-drain are two configured modes of the same rule.** In safety-in-numbers, a wizard's effective drain is divided by the number of nearby wizards (a cluster is harder to drain); in area-drain, a dementor drains every wizard in range at full rate. One boolean selects which. The reverse numbers game is a symmetric extension: when at least *N* wizards keep a dementor within range continuously for *T*, that dementor flips to wizard.
- **Two-way conversion via a single energy axis.** A dementor also carries energy; sustained proximity to a qualifying wizard group (or a configured "restore" rule) raises it, and crossing a threshold flips it back to wizard. A wizard drained to empty flips to dementor (or dies, per config). This keeps one state machine driven by one number.
- **Require-BLE-capable is a gate, not an assumption.** A Game MAY set `require_ble_capable`; a device failing a BLE self-check is refused entry with a clear message, but the running game still assumes heterogeneous, imperfect radios among admitted devices.
- **Reuse Channels + polling fallback** (per the architecture brief's real-time decision) for live energy/role push and the staff dashboard; polling `GET /api/dementors/me/` remains a graceful fallback.

## Risks / Trade-offs

- [iOS↔iOS background BLE is effectively broken; screen-locked phones go dark] → Design for **foreground + screen-on** only: the app keeps the screen awake during play, prominently instructs "phone out, screen on," and the economy treats missing reports as no-op rather than penalty; the wearable badge is the eventual always-on fix.
- [RSSI is coarse and device-dependent — a strong-radio phone looks closer than a weak one at the same distance] → Use ordinal buckets with hysteresis and per-pair fusion; never expose metres; tune thresholds during the pilot; accept fuzzy edges as thematic ("magic range is fuzzy").
- [Spoofing: a phone could report fake IDs/RSSI to farm flips or avoid draining] → Server authority + plausibility checks (rate limits, reciprocity/corroboration bonus, impossible-teleport and impossible-crowd filters, ephemeral rotating IDs so a replayed ID expires); documented as raising the bar, not eliminating cheating.
- [Scale: 100+ advertisers in one park floods every scanner; report batches get large and ticks get heavy] → Cap and sample reports per batch, keep the ephemeral ID payload tiny, coarsen tick cadence under load, and index `ProximityReport` by session + freshness; validate the ceiling in the pilot.
- [Battery drain from continuous advertise + scan + screen-on] → Expose scan duty-cycle in config, keep sessions time-boxed, and warn players to arrive charged; measure battery burn in the pilot.
- [Privacy: broadcasting a beacon in a public park with bystanders present] → Advertise only an opaque ephemeral token that rotates and maps to a player only server-side; no PII on air; identities are session-scoped and discarded after.
- [Fairness/feel: a hidden dementor should be *noticeable* but not omniscient-feeling] → The live drain/gain indicator surfaces "something is draining you" without revealing who or exactly where; tune drain rate so a wizard has time to react and flee.
- [Pilot is the real test; lab numbers will not transfer] → Ship behind the pilot gate; the pilot must confirm detection latency, false-positive/negative rates, the RSSI bucket thresholds, tick cadence, and battery on mixed hardware at scale before general availability.

## Migration Plan

1. Additive migration for `game.ProximityIdentity`, `game.ProximityReport`, `game.ProximityEvent`, and `game.DementorState`; no changes to existing tables' semantics.
2. Additive migration adding dementor config fields to `organize.Game` (defaults chosen so the mode is simply unused until a Game opts in) and nullable override fields to `organize.Session`; wire them into the effective-value resolver.
3. No data backfill: existing Sessions are unaffected because no Game enables the mode by default.
4. Native BLE advertise/scan is delivered as a mobile device build behind a feature flag; the server side ships first and is exercised by a simulated-reports test harness, then validated by the real-park pilot before the mode is offered for general use.
