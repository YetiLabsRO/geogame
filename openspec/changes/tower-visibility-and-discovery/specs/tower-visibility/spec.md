## ADDED Requirements

### Requirement: Two-axis visibility model

The system SHALL model tower visibility as two independent axes — tower discoverability and challenge visibility — that compose freely, so a tower's presence on the map and the legibility of its challenge are configured separately.

#### Scenario: The two axes are independent

- **WHEN** a creator configures a tower's visibility
- **THEN** the tower SHALL carry a `discoverability` axis (whether/when the tower appears on the map) and a `challenge_visibility` axis (whether/when its challenge is legible)
- **AND** any combination of the two axes SHALL be valid, so a `HIDDEN` tower MAY be `VISIBLE_ANYWHERE` and a `VISIBLE` tower MAY be `HIDDEN_UNTIL_ARRIVAL`

### Requirement: Tower discoverability axis

The system SHALL model tower discoverability as an enum of `HIDDEN`, `VISIBLE`, or `FOG_REVEAL` controlling whether and how a team comes to see a tower on the map.

#### Scenario: Visible tower

- **WHEN** a tower's effective discoverability is `VISIBLE`
- **THEN** the tower SHALL be shown on the map to every team from the start of the run without any discovery step

#### Scenario: Hidden tower revealed by walking up to it

- **WHEN** a tower's effective discoverability is `HIDDEN`
- **THEN** the tower SHALL NOT be shown on the map to a team until a member of that team is within the tower's effective `proximity_meters`, at which point it SHALL be revealed to that team (see the `discovery-tracking` capability)
- **AND** a team MAY know the tower's zone yet still not see the tower until it is revealed

#### Scenario: Fog-revealed tower

- **WHEN** a tower's effective discoverability is `FOG_REVEAL`
- **THEN** neither the tower nor its zone SHALL be shown to a team until the team reveals it by entering the zone **or** by covering more than the zone's configured coverage percentage (see the `discovery-tracking` capability)

### Requirement: Challenge visibility axis

The system SHALL model challenge visibility as an enum of `HIDDEN_UNTIL_ARRIVAL` or `VISIBLE_ANYWHERE` controlling whether a tower's challenge is legible before the player physically reaches the tower.

#### Scenario: Challenge hidden until arrival

- **WHEN** a tower's effective challenge visibility is `HIDDEN_UNTIL_ARRIVAL`
- **THEN** the challenge's prompt and details SHALL NOT be exposed to a player who is outside the tower's activation area
- **AND** the challenge SHALL become legible and completable once the player is inside the tower's effective `proximity_meters`

#### Scenario: Challenge visible anywhere but completed on-site

- **WHEN** a tower's effective challenge visibility is `VISIBLE_ANYWHERE`
- **THEN** the challenge's prompt SHALL be legible from any distance
- **AND** completion SHALL still be permitted only while the player is inside the tower's activation area (see the `challenge-submission` capability)

### Requirement: Game-wide defaults with per-tower override

The system SHALL let each Game set default values for both visibility axes and SHALL let each tower override them, resolving a null tower value to the Game default.

#### Scenario: Game defaults apply when the tower does not override

- **WHEN** a tower's `discoverability` or `challenge_visibility` field is null
- **THEN** the effective value SHALL be read from the current Session's Game defaults `tower_discoverability_default` and `challenge_visibility_default`
- **AND** the Game defaults SHALL themselves accept a nullable per-Session override, with the Session override winning when set (the standard Game-default plus Session-override config pattern)

#### Scenario: Per-tower override wins

- **WHEN** a tower sets a non-null `discoverability` or `challenge_visibility`
- **THEN** the tower's own value SHALL be used for that axis regardless of the Game default

### Requirement: Fog-of-war reveal threshold per zone

The system SHALL let each zone configure the fraction of its area a team must cover to reveal its `FOG_REVEAL` towers, with a game-wide default.

#### Scenario: Per-zone coverage threshold

- **WHEN** a creator sets a zone's `fog_reveal_coverage_pct`
- **THEN** a team SHALL reveal that zone's `FOG_REVEAL` towers once its accumulated coverage of the zone exceeds that percentage (see the `discovery-tracking` capability)
- **AND** when the zone's `fog_reveal_coverage_pct` is null the effective threshold SHALL fall back to the Game's `fog_reveal_coverage_pct_default`

### Requirement: Other teams' ownership visibility setting

The system SHALL provide a per-game setting controlling whether the public map reveals which other teams have conquered zones and towers, with a nullable per-Session override.

#### Scenario: Concealing other teams' conquests

- **WHEN** a Game's effective `reveal_other_teams_ownership` is False
- **THEN** a team SHALL see ownership colouring only where its own team holds a zone or tower, and SHALL NOT be told which other team currently holds any other zone or tower
- **AND** whether a team can see a tower at all SHALL remain governed by discoverability and discovery, independently of ownership visibility

#### Scenario: Revealing other teams' conquests

- **WHEN** a Game's effective `reveal_other_teams_ownership` is True
- **THEN** the map SHALL colour zones and towers by every team's current control, as in the shipped behavior

### Requirement: Backward-compatible visibility defaults

The system SHALL default every visibility knob so that existing games remain fully visible with no fog and full ownership colouring.

#### Scenario: Migrated game is unchanged

- **WHEN** a Game is migrated without configuring visibility
- **THEN** its defaults SHALL be `tower_discoverability_default=VISIBLE`, `challenge_visibility_default=VISIBLE_ANYWHERE`, and `reveal_other_teams_ownership=True`, with per-tower and per-zone override fields null
- **AND** because no tower is `HIDDEN` or `FOG_REVEAL`, no discovery SHALL be required and the map SHALL render exactly as before this change
