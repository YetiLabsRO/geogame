## ADDED Requirements

### Requirement: Optional wearable badge as an alternate transport

The system SHALL support an optional ESP32-C3 wearable badge as an alternate always-on transport for proximity games, feeding the same server-authoritative substrate used by phone BLE without changing the game rules.

#### Scenario: Badge feeds the same substrate as phone BLE

- **WHEN** a Session runs a proximity game (see the `mode-dementors` capability) with badges instead of, or alongside, phone BLE (see the `ble-proximity` capability)
- **THEN** badge-observed proximity SHALL be recorded into the same proximity/energy-economy substrate as phone-BLE proximity, tagged with a `BADGE` source
- **AND** the energy economy and role flips SHALL treat badge-sourced and phone-sourced proximity uniformly, so a Session MAY run all-phone, all-badge, or mixed

#### Scenario: Badge is optional and opt-in

- **WHEN** a Session is configured without badges
- **THEN** the phone-BLE proximity path SHALL continue to operate unchanged
- **AND** enabling badges SHALL NOT be required for any existing proximity game to function

### Requirement: Phone becomes optional during play

The system SHALL allow the player's phone to be present-but-backgrounded, off, or absent during play, with the badge owning proximity detection and the glanceable display.

#### Scenario: Phone present but not foreground

- **WHEN** a player wears an assigned badge and their phone is in a pocket, backgrounded, or powered off
- **THEN** the badge SHALL continue detecting nearby badges and displaying energy/role state without the phone being in the foreground
- **AND** the game SHALL NOT require the phone's BLE radio to be advertising or scanning in the foreground for that player

#### Scenario: Phone fully absent under gateway coverage

- **WHEN** gateway coverage spans the play area and a player has no phone present
- **THEN** the player SHALL still be able to participate via their badge alone
- **AND** the server SHALL receive that player's proximity and telemetry via the gateways rather than via any phone

### Requirement: ESP-NOW badge-to-badge proximity mesh

The system SHALL have badges detect one another directly over ESP-NOW, without pairing, a WiFi router, or a phone in the loop, forming a proximity field of peers.

#### Scenario: Connectionless peer detection

- **WHEN** two badges come within radio range
- **THEN** each badge SHALL detect the other by receiving its broadcast beacon over ESP-NOW, with no pairing or router involved
- **AND** each badge SHALL log the heard badge id and the received signal strength (RSSI) into a local observation buffer

#### Scenario: Long-Range mode for wider fields

- **WHEN** a deployment enables ESP-NOW Long-Range (LR) mode
- **THEN** detection range SHALL extend beyond the default mode's tens-of-meters
- **AND** the deployment SHALL accept the reduced throughput that LR mode entails

### Requirement: RSSI-coarse ranging is decided server-side

The system SHALL treat RSSI as a coarse distance estimate and SHALL decide the "in range" / drain threshold on the server using the Session's proximity configuration, not on the badge.

#### Scenario: Server maps RSSI to range buckets

- **WHEN** the server ingests a badge observation carrying a raw RSSI value
- **THEN** the server SHALL map the RSSI to a coarse range bucket using the Session's proximity threshold configuration
- **AND** the badge SHALL NOT itself decide whether another badge is within drain range

#### Scenario: Noisy RSSI is smoothed, not treated as metric distance

- **WHEN** RSSI values for a pair of badges fluctuate due to reflections or bodies
- **THEN** the server SHALL smooth RSSI over a short window before bucketing
- **AND** it SHALL NOT interpret RSSI as a precise metric distance

### Requirement: RGB ring displays server-authored energy and role state

The system SHALL have the badge's RGB ring show the wearer their current energy level and role state as a glanceable display driven by server-authored state.

#### Scenario: Glanceable energy and role

- **WHEN** the server pushes a badge's current state (energy, role, active effects)
- **THEN** the ring SHALL render energy level and role so the wearer can read their status at a glance without a phone
- **AND** the rendered state SHALL reflect the last server-authored state the badge received

#### Scenario: Stale state on link loss

- **WHEN** the badge loses its gateway downlink
- **THEN** the badge SHALL hold and display its last-known state rather than inventing new state
- **AND** it SHALL indicate a stale/disconnected condition via a distinct ring pattern

### Requirement: IMU gesture, activity, and dead-reckoning mechanics

The system SHALL use the badge's IMU for gesture actions, activity classification, and short-horizon dead-reckoning, reporting these to the server rather than acting on them locally.

#### Scenario: Gesture action reported to the server

- **WHEN** the wearer performs a recognized gesture (e.g. a cast/drain flick)
- **THEN** the badge SHALL emit a gesture event to the server via the gateway relay
- **AND** the server SHALL decide the gesture's effect on the game; the badge SHALL NOT apply the effect itself

#### Scenario: Activity detection feeds energy and stamina

- **WHEN** the badge classifies the wearer's activity as running, standing, or still
- **THEN** it SHALL report the activity class as telemetry
- **AND** the server SHALL be able to apply energy and stamina rules based on that activity class

#### Scenario: Dead-reckoning smooths position between updates

- **WHEN** GPS or proximity updates are sparse
- **THEN** the badge SHALL use IMU-based dead-reckoning to smooth the wearer's estimated position between authoritative updates
- **AND** dead-reckoned positions SHALL be reported as advisory telemetry, not as authoritative ground truth

### Requirement: Gateway relay nodes carry data between mesh and server

The system SHALL relay badge-observed proximity and telemetry to the server, and push server-authored per-badge state back to the badges, through a small number of gateway nodes.

#### Scenario: Uplink of batched observations

- **WHEN** a gateway node (ESP32 + WiFi/4G, or an organizer tablet running the relay app) collects badge observations and telemetry off the mesh
- **THEN** it SHALL batch them and relay them to the server's ingest endpoint
- **AND** it SHALL buffer and retry when its uplink is temporarily offline

#### Scenario: Downlink of authoritative state

- **WHEN** the server returns per-badge authoritative state
- **THEN** the gateway SHALL re-broadcast that state onto the mesh
- **AND** each badge SHALL apply the state addressed to its own badge id and update its ring

#### Scenario: Overlapping gateway coverage is deduplicated

- **WHEN** two gateways both hear and relay the same badge observation
- **THEN** the server SHALL deduplicate by badge id plus rolling counter/timestamp
- **AND** overlapping coverage SHALL improve reliability without double-counting proximity

### Requirement: Backend gateway ingest endpoint

The system SHALL expose an authenticated ingest endpoint that accepts gateway-relayed proximity and telemetry batches and returns per-badge authoritative state.

#### Scenario: Authenticated, versioned batch ingest

- **WHEN** a gateway posts a batch to `POST /api/gateway/ingest/`
- **THEN** the server SHALL authenticate the gateway by its per-gateway credential and validate the wire-protocol version
- **AND** it SHALL accept a proximity batch and a telemetry batch, and respond with the current per-badge state for the gateway to distribute

#### Scenario: Badge identity resolved server-side

- **WHEN** an ingested observation references an opaque on-air badge id
- **THEN** the server SHALL resolve it to the badge's active assignment to a player/team/session
- **AND** telemetry SHALL be persisted (battery, activity, IMU samples) against the badge device record

### Requirement: Server remains authoritative over game outcomes

The system SHALL keep the server as the single authority for the energy economy and role changes; badges and gateways SHALL transport and display only.

#### Scenario: Device-asserted outcomes are ignored

- **WHEN** a badge or gateway submits data that asserts a game outcome (e.g. "this wizard is now a dementor")
- **THEN** the server SHALL ignore the asserted outcome and accept only the underlying observations (heard ids, RSSI, gestures, activity, battery)
- **AND** the server SHALL compute all energy changes and role flips itself, consistent with the `mode-dementors` capability

### Requirement: Provisioned hand-out and collect model

The system SHALL support a provisioned operating model in which physical badges and gateways are registered as assets, handed out and bound to players/teams for a Session, and collected afterward.

#### Scenario: Registering devices

- **WHEN** staff register a physical badge or gateway
- **THEN** the system SHALL create a durable device record capturing its identity, firmware version, and status
- **AND** the badge's durable identity SHALL be an opaque id, so a lost or borrowed badge SHALL NOT expose a real player identity on the air

#### Scenario: Hand-out binds a badge for a Session

- **WHEN** staff hand a badge to a player at the start of a Session
- **THEN** the system SHALL create a `BadgeAssignment` binding that badge to the player/team for that Session
- **AND** subsequent observations of that badge id SHALL resolve to that assignment for the duration of the Session

#### Scenario: Collect releases and flags un-returned devices

- **WHEN** staff collect badges at the end of an event
- **THEN** the system SHALL release the assignments so the physical badges can be reused for a future event
- **AND** it SHALL flag any badge that was not returned

### Requirement: Battery and power telemetry

The system SHALL have badges operate on battery with low-power duty cycling and report battery and health telemetry so staff can manage the fleet.

#### Scenario: Reporting battery state

- **WHEN** a badge reports telemetry
- **THEN** it SHALL include its current battery level
- **AND** the staff inventory view SHALL surface low-battery and stale-firmware badges so they can be swapped or recharged

#### Scenario: Duty-cycling to last an event

- **WHEN** a badge is in normal play
- **THEN** its firmware SHALL duty-cycle the radio and ring to conserve power over a multi-hour event
- **AND** the collect step SHALL allow recharging the fleet for the next event
