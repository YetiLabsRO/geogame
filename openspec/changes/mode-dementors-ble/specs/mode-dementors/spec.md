## ADDED Requirements

### Requirement: Roles and per-player energy

The system SHALL model each player in a dementors-mode session with a role of WIZARD or DEMENTOR and a numeric energy value, held server-side as `DementorState`.

#### Scenario: Assigning roles and energy at start

- **WHEN** a dementors-mode session starts
- **THEN** the system SHALL assign each player an initial role of WIZARD or DEMENTOR per the session's configuration
- **AND** it SHALL set each player's starting energy from the effective config
- **AND** all subsequent role and energy changes SHALL be computed on the server, never asserted by a player's device

### Requirement: Dementors drain nearby wizards

The system SHALL drain a wizard's energy while a dementor is within the configured drain-range proximity bucket, using the server-derived proximity from the `ble-proximity` capability rather than line of sight.

#### Scenario: Draining through obstacles

- **WHEN** a server tick finds a `ProximityEvent` placing a dementor within the drain-range bucket of a wizard
- **THEN** the system SHALL reduce that wizard's energy by the configured drain rate for that tick
- **AND** the drain SHALL apply regardless of any physical obstacle between them, because proximity is wireless, so hiding behind a tree SHALL NOT prevent it
- **AND** a tick with no fresh qualifying proximity SHALL apply no drain for that pair

### Requirement: Full-drain role change

The system SHALL resolve a wizard whose energy reaches empty by either flipping that player to DEMENTOR or marking them out of play, according to configuration.

#### Scenario: Wizard drained to empty

- **WHEN** a wizard's energy reaches zero
- **THEN** if the session is configured `flip_on_empty`, the system SHALL change that player's role to DEMENTOR
- **AND** if the session is configured `die_on_empty`, the system SHALL mark that player out of play instead
- **AND** the system SHALL record the change with its cause and time

### Requirement: Safety in numbers versus area drain

The system SHALL support two configured drain behaviours for a cluster of wizards: safety-in-numbers, where a larger cluster is harder to drain, or area-drain, where a dementor drains every wizard in range at full rate.

#### Scenario: Safety in numbers reduces per-wizard drain

- **WHEN** the session is configured for safety-in-numbers and several wizards are within range of one dementor
- **THEN** the system SHALL reduce each clustered wizard's effective drain as the nearby-wizard count grows
- **AND** a lone wizard SHALL be drained faster than the same wizard standing in a group

#### Scenario: Area drain hits everyone in range

- **WHEN** the session is configured for area-drain and several wizards are within range of one dementor
- **THEN** the system SHALL drain every wizard in range at the full configured rate
- **AND** clustering SHALL NOT reduce any individual's drain

### Requirement: Reverse numbers game

The system SHALL let a group of wizards overpower a dementor by keeping it within range long enough, flipping that dementor to WIZARD.

#### Scenario: A group holds a dementor

- **WHEN** at least the configured number `N` of wizards keep a dementor within the configured proximity bucket continuously for at least the configured hold duration `T`
- **THEN** the system SHALL change that dementor's role to WIZARD
- **AND** it SHALL reset the hold progress if the group drops below `N` before `T` elapses
- **AND** it SHALL record the flip with its cause

### Requirement: Two-way conversion

The system SHALL allow conversion in both directions along a single energy axis, so a dementor that regains enough energy becomes a wizard just as a wizard drained to empty becomes a dementor.

#### Scenario: Dementor restored to a wizard

- **WHEN** a dementor's energy rises across the configured conversion threshold
- **THEN** the system SHALL change that player's role back to WIZARD
- **AND** the conversion SHALL be driven by the same server-computed energy value that governs draining, so one number drives the whole state machine

### Requirement: Player live feedback

The system SHALL show each player their own role, current energy level, and a live drain or gain indication, so a player notices an unseen dementor draining them.

#### Scenario: Seeing an unseen dementor's effect

- **WHEN** a player views their dementors-mode screen while being drained by a dementor they cannot see
- **THEN** the system SHALL display their current energy level and role
- **AND** it SHALL indicate live that energy is being drained (or gained) this tick without necessarily revealing which player or exact location is responsible
- **AND** these values SHALL come from server state (see `GET /api/dementors/me/` and the real-time push), never from the device's own proximity claim

#### Scenario: Prompting to keep the phone active

- **WHEN** the player's device stops sending fresh proximity reports (for example the screen turned off)
- **THEN** the system SHALL prompt the player to keep the phone out with the screen on, because BLE detection is reliable only while the app is foregrounded and active (see the `ble-proximity` capability)

### Requirement: Staff live totals

The system SHALL give staff a live view of role totals for a dementors-mode session, optionally rendered on a map or tablet dashboard.

#### Scenario: Watching the balance of power

- **WHEN** a staff member opens the dementors dashboard for a running session
- **THEN** the system SHALL display current counts by role, for example five dementors and ten wizards
- **AND** it SHALL update those totals live as roles flip, with polling as a graceful fallback
- **AND** it MAY plot players by role on a map or tablet view

### Requirement: Dementors gameplay configuration

The system SHALL expose the dementors gameplay rules as configuration on the Game with nullable per-Session overrides, resolved by the effective-value helper, and defaulting so the mode is inert until a Game opts in.

#### Scenario: Session override wins over Game default

- **WHEN** a Session overrides a dementors knob (drain rate, drain-range bucket, starting energy, `flip_on_empty` versus `die_on_empty`, safety-in-numbers versus area-drain, reverse-game `N` and `T`, conversion threshold, or tick cadence)
- **THEN** the effective value for that Session SHALL be the Session override
- **AND** when the Session leaves it unset, the effective value SHALL fall back to the Game default
- **AND** a Game that does not enable dementors mode SHALL be unaffected by these fields
