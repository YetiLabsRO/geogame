## ADDED Requirements

### Requirement: Ephemeral advertising identity

The system SHALL issue each player a per-session, opaque, ephemeral advertising identity that the player's device broadcasts over BLE, and SHALL keep the mapping from that identity to the player only on the server.

#### Scenario: Issuing an advertising token

- **WHEN** a player's device requests an advertising identity for its active session via `POST /api/proximity/identity/`
- **THEN** the system SHALL return a short opaque `ProximityIdentity` token bound to that player and session
- **AND** the token SHALL NOT encode the player's user identity or any personal data, so a bystander scanning the air learns nothing about who is present
- **AND** the server SHALL retain the token→player mapping privately for the duration of the session

#### Scenario: Rotating an identity

- **WHEN** an identity's rotation interval elapses or a device re-requests its identity
- **THEN** the system SHALL be able to issue a fresh token and mark the previous one expired
- **AND** reports referencing an expired token SHALL be resolvable for their freshness window and then ignored, so a replayed old token cannot be farmed indefinitely

### Requirement: Proximity reporting

The system SHALL let each device report the set of advertising identities it observes over BLE together with each observation's signal strength, and SHALL persist these as untrusted `ProximityReport` inputs.

#### Scenario: Submitting a report batch

- **WHEN** a device submits a batch of observed `{token, rssi}` entries via `POST /api/proximity/reports/`
- **THEN** the system SHALL persist a `ProximityReport` stamped with the reporter, the session, and a receive time
- **AND** it SHALL accept the batch even if some observed tokens are unknown or expired, recording what it can and discarding the rest
- **AND** it SHALL rate-limit and size-cap submissions so one device cannot flood the session

### Requirement: Server-authoritative proximity derivation

The system SHALL derive who-is-near-whom on the server from reported observations rather than trusting any device's own claim of proximity, and SHALL record each derived nearness as a `ProximityEvent`.

#### Scenario: Fusing both directions of a pair

- **WHEN** the server runs a derivation pass over reports within the freshness window
- **THEN** it SHALL produce at most one `ProximityEvent` per unordered pair of players per pass
- **AND** the event's confidence SHALL be higher when both devices reported seeing each other than when only one did, so one-directional deafness still yields a usable event
- **AND** the derived proximity SHALL be the authoritative input to any game built on this substrate (see the `mode-dementors` capability), never a value asserted by a player's device

#### Scenario: Rejecting implausible reports

- **WHEN** a report implies an implausible situation (for example a rate far above the configured cadence, an impossibly large crowd of simultaneous contacts, or an expired identity)
- **THEN** the system SHALL filter the offending observations out of derivation
- **AND** it SHALL keep the remaining plausible observations rather than discarding the whole batch

### Requirement: Coarse RSSI distance buckets

The system SHALL translate RSSI into a small ordinal set of coarse distance buckets and SHALL NOT present RSSI as a precise distance in metres.

#### Scenario: Mapping signal strength to a bucket

- **WHEN** the server evaluates an observation's RSSI
- **THEN** it SHALL assign an ordinal proximity bucket (for example VERY_CLOSE, NEAR, or FAR) using configurable thresholds
- **AND** it SHALL apply hysteresis so a signal hovering at a boundary does not rapidly oscillate between buckets
- **AND** it SHALL treat the mapping as coarse, reflecting that RSSI varies by several metres and is attenuated by bodies and foliage rather than blocked by line of sight

### Requirement: Mixed-device and BLE-capability support

The system SHALL support a heterogeneous mix of Android and iPhone devices in one session, and SHALL let a Game require BLE-capable devices while still tolerating differing radios among admitted devices.

#### Scenario: Requiring BLE-capable devices

- **WHEN** a Game sets `require_ble_capable` and a device that fails a BLE self-check tries to join a session
- **THEN** the system SHALL refuse entry with a clear message explaining the BLE requirement
- **AND** when `require_ble_capable` is not set, the system SHALL admit the device but MAY exclude it from proximity gameplay

#### Scenario: Tolerating heterogeneous radios

- **WHEN** admitted devices include a mix of Android and iPhone hardware with differing radio characteristics
- **THEN** the system SHALL still derive proximity from whatever reports arrive
- **AND** it SHALL NOT assume symmetric detection between any two devices

### Requirement: Foreground-only reliability handling

The system SHALL treat reliable BLE detection as available only while a device's app is in the foreground with the screen on, and SHALL degrade gracefully when reports are stale or absent.

#### Scenario: Stale reports are treated as absence, not penalty

- **WHEN** a device stops sending reports because its app is backgrounded or its screen is off
- **THEN** the server SHALL consider that device's observations stale once they fall outside the freshness window
- **AND** it SHALL treat the absence as "no observation this window" rather than fabricating proximity
- **AND** any game built on the substrate SHALL be able to prompt the player to keep the phone out and active (see the `mode-dementors` capability)

### Requirement: Proximity substrate configuration

The system SHALL expose the substrate's cadence and thresholds as configuration on the Game with nullable per-Session overrides, resolved by the effective-value helper.

#### Scenario: Session override wins over Game default

- **WHEN** a Session sets an override for a substrate knob (report interval, scan duty-cycle, freshness window, RSSI thresholds, or `require_ble_capable`)
- **THEN** the effective value for that Session SHALL be the Session override
- **AND** when the Session leaves it unset, the effective value SHALL fall back to the Game default
