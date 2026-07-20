## ADDED Requirements

### Requirement: Per-team tower discovery record

The system SHALL record, per Session, that a team has discovered a tower, so visibility is tracked independently for each team.

#### Scenario: Creating a discovery record

- **WHEN** a team reveals a tower for the first time in a Session
- **THEN** the system SHALL create a `game.TowerDiscovery` with `session`, `team`, `tower`, `discovered_at`, `discovered_by` (the reporting user), and `method` (`PROXIMITY`, `ZONE_ENTRY`, `ZONE_COVERAGE`, `ALWAYS_VISIBLE`, or `STAFF`)
- **AND** the record SHALL be unique per `(session, team, tower)` so re-revealing does not duplicate it

#### Scenario: A team sees only what it discovered or what is always visible

- **WHEN** the system resolves which towers a team may see in a Session
- **THEN** it SHALL return every tower whose effective discoverability is `VISIBLE` plus every tower for which a `TowerDiscovery` exists for that team
- **AND** this set SHALL be computed independently of tower ownership

### Requirement: Discovery of hidden towers by proximity

The system SHALL reveal a `HIDDEN` tower to a team when a member reports a position within the tower's activation area.

#### Scenario: Walking up to a hidden tower

- **WHEN** a team member reports a position within a `HIDDEN` tower's effective `proximity_meters` and no `TowerDiscovery` exists yet for that team and tower
- **THEN** the system SHALL create a `TowerDiscovery` with `method=PROXIMITY`
- **AND** the tower SHALL thereafter be visible to that team

### Requirement: Discovery of fog-revealed towers by zone entry or coverage

The system SHALL reveal a `FOG_REVEAL` tower to a team either when a member enters the tower's zone or when the team's accumulated coverage of that zone exceeds the zone's threshold.

#### Scenario: Entering the zone

- **WHEN** a team member reports a position inside a `FOG_REVEAL` tower's zone
- **THEN** the system SHALL create a `TowerDiscovery` with `method=ZONE_ENTRY` for each not-yet-discovered `FOG_REVEAL` tower in that zone

#### Scenario: Covering enough of the zone without entering it

- **WHEN** a team's accumulated coverage of a zone exceeds the zone's effective `fog_reveal_coverage_pct` (see the `tower-visibility` capability)
- **THEN** the system SHALL create a `TowerDiscovery` with `method=ZONE_COVERAGE` for each not-yet-discovered `FOG_REVEAL` tower in that zone
- **AND** coverage SHALL be computed as the area of the union of the team's buffered visited positions intersected with the zone, divided by the zone's area

### Requirement: Discovery persists across conquest and ownerlessness

The system SHALL keep a team's discovery of a tower permanent for the run once made, regardless of later ownership changes.

#### Scenario: Keeping sight of a lost or ownerless tower

- **WHEN** a tower a team has discovered is later conquered by another team, or its ownership lapses so it has no owner
- **THEN** the team's `TowerDiscovery` SHALL NOT be deleted and the tower SHALL remain visible to that team
- **AND** whether that team can also see who currently owns the tower SHALL be governed by the game's other-teams ownership visibility setting (see the `tower-visibility` capability)

### Requirement: Discovery evaluation from reported positions

The system SHALL evaluate discovery from players' reported positions, consuming the live-location stream when available and offering a self-contained ping fallback.

#### Scenario: Reporting a position via the discovery ping

- **WHEN** a player calls `POST /api/discovery/ping/` with their current position
- **THEN** the system SHALL evaluate proximity, zone-entry, and coverage reveals for the player's team and return the towers newly revealed by this position
- **AND** the same evaluation SHALL run when positions arrive through the `live-location` capability's stream, so both sources create discoveries identically

#### Scenario: Querying a team's discovered towers

- **WHEN** a player calls `GET /api/discovery/towers/`
- **THEN** the system SHALL return the set of towers the caller's team has discovered in the current Session

### Requirement: Staff override of discovery

The system SHALL let staff reveal a tower to a team directly, independent of position.

#### Scenario: Staff reveals a tower

- **WHEN** a staff user reveals a tower to a team
- **THEN** the system SHALL create a `TowerDiscovery` with `method=STAFF`
- **AND** the tower SHALL become visible to that team as if discovered in the field
