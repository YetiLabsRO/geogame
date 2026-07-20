## ADDED Requirements

### Requirement: Live location is opt-in per game

The system SHALL keep live location tracking disabled by default and stream or store positions only for a Session whose effective configuration enables it.

#### Scenario: Tracking off by default

- **WHEN** a Session runs on a Game whose effective `location_tracking_enabled` is false
- **THEN** the system SHALL NOT accept location pings for that Session
- **AND** it SHALL NOT require any location consent
- **AND** the player app SHALL NOT stream any position

#### Scenario: Tracking enabled by the game

- **WHEN** a Game sets `location_tracking_enabled` true (optionally overridden per Session by the runner)
- **THEN** the system SHALL accept pings, require consent to play, and expose live positions per the effective `location_visibility` (see the `game-configuration` capability for the config fields)

### Requirement: Game-level update frequency

The system SHALL pace location streaming from a single game-level update frequency that individual players cannot change.

#### Scenario: Player app reads the effective interval

- **WHEN** the player app streams location for a location-enabled Session
- **THEN** it SHALL sample at the effective `location_ping_interval_seconds` resolved from the Session override or the Game default
- **AND** the app SHALL expose no player-facing control to change the frequency

#### Scenario: Runner adjusts the frequency

- **WHEN** a runner changes `location_ping_interval_seconds` for the Game or overrides it on the Session
- **THEN** the effective interval SHALL change for every player in that Session
- **AND** no per-player value SHALL exist that overrides it

### Requirement: Consent is required to play a location-enabled game

The system SHALL require a player to agree to the game's location rules before they may play a location-enabled Session, and SHALL record that agreement.

#### Scenario: Recording consent

- **WHEN** a player calls `POST /api/location/consent/` for their current Session and the Game's location rules
- **THEN** the system SHALL store a `LocationConsent` for `(user, session)` with `agreed_at` and a snapshot or hash of the `location_consent_text` version agreed to
- **AND** `GET /api/location/consent/` SHALL report the player's standing consent status and the effective consent text

#### Scenario: Playing without consent is blocked

- **WHEN** a player tries to play or submit in a location-enabled Session without standing consent
- **THEN** the system SHALL block the action with a clear, actionable error directing them to the consent step
- **AND** it SHALL reject any location ping from that player

#### Scenario: Withdrawing consent

- **WHEN** a player withdraws consent for a Session
- **THEN** the system SHALL stop accepting their pings and stop plotting their position live
- **AND** it SHALL purge that player's stored pings for the Session
- **AND** continued play of a location-mandatory Session SHALL be blocked until consent is granted again

### Requirement: Location ping history

The system SHALL store consented player positions as an append-only `LocationPing` history suitable for live plotting and after-game replay and analysis.

#### Scenario: Ingesting a ping

- **WHEN** a consented player calls `POST /api/location/ping/` with a `point`, `accuracy`, and client `recorded_at` for a location-enabled Session
- **THEN** the system SHALL store a `game.LocationPing` recording `user`, `session`, denormalized `team`, `point`, `accuracy`, `recorded_at`, and a server `received_at`
- **AND** it SHALL reject the ping when tracking is disabled or consent is missing

#### Scenario: Replaying after the game

- **WHEN** a staff user calls `GET /api/staff/sessions/{id}/location-history/`
- **THEN** the system SHALL return the Session's `LocationPing` series, filterable by user, team, and time window, for analysis of who was where and when
- **AND** the series SHALL remain available after the Session is deactivated or finished until the retention window expires

### Requirement: Live position visibility

The system SHALL expose live player positions only within the bounds of the effective `location_visibility`, defaulting no broader than the player's own team.

#### Scenario: Visible positions for a player

- **WHEN** a player calls `GET /api/location/live/` for a location-enabled Session
- **THEN** the system SHALL return the latest position per visible player or team, filtered by the effective `location_visibility` — `NONE` returns no positions to players, `OWN_TEAM` returns only the caller's team, `EVERYONE` returns all consenting players
- **AND** it SHALL never reveal a player who has not consented or whose consent was withdrawn

#### Scenario: Staff always sees live positions

- **WHEN** a staff user reads live positions for a Session
- **THEN** the system SHALL return all consenting players' latest positions regardless of `location_visibility`
- **AND** richer visibility rules (own-team / everyone / N nearest people) are refined by the `presence-rules` capability

### Requirement: Bounded retention of location data

The system SHALL retain location pings only within the game's retention window and only while consent stands, then purge them.

#### Scenario: Purging expired pings

- **WHEN** the `purge_location_pings` task runs
- **THEN** it SHALL delete `LocationPing` rows older than the effective `location_retention_days` for their Session
- **AND** it SHALL delete a user's Session pings when that user's consent for the Session has been withdrawn
