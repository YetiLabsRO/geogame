## MODIFIED Requirements

### Requirement: Live map rendering

The system SHALL render a live Leaflet map of the zones and towers currently visible to the player's team, colored by current TeamGroup control subject to the game's other-teams ownership visibility setting.

#### Scenario: Viewing the map

- **WHEN** a player opens the main map
- **THEN** it SHALL render via Leaflet only the zones and towers visible to the player's team — every `VISIBLE` tower plus towers the team has discovered (see the `tower-visibility` and `discovery-tracking` capabilities)
- **AND** it SHALL color them by current per-TeamGroup ownership, concealing other teams' control when the Game's effective `reveal_other_teams_ownership` is False
- **AND** it SHALL keep showing a tower the team has discovered even after another team conquers it or it becomes ownerless
- **AND** it SHALL update via polling or a refresh action (no websockets required)

### Requirement: GPS proximity feedback and challenge visibility

The system SHALL give the player live proximity feedback before they submit, and SHALL gate whether the tower's challenge is legible according to the tower's challenge-visibility axis.

#### Scenario: Submitting near vs far

- **WHEN** a player is on the tower detail page
- **THEN** it SHALL show live distance-to-tower from device GPS
- **AND** it SHALL disable the submit button when the player is farther than the Session's `proximity_meters` from the tower
- **AND** photo upload SHALL use the browser camera via `<input type="file" capture="environment">`

#### Scenario: Challenge hidden until arrival

- **WHEN** a tower's effective challenge visibility is `HIDDEN_UNTIL_ARRIVAL` and the player is outside the tower's activation area
- **THEN** the app SHALL NOT reveal the challenge prompt or details, showing only a "get closer to reveal" affordance
- **AND** when the player enters the activation area the app SHALL reveal and enable the challenge

#### Scenario: Challenge visible anywhere but completable only on-site

- **WHEN** a tower's effective challenge visibility is `VISIBLE_ANYWHERE`
- **THEN** the app SHALL show the challenge prompt from any distance
- **AND** it SHALL allow completion only while the player is inside the tower's activation area, disabling submission otherwise

## ADDED Requirements

### Requirement: Roaming discovery and fog-of-war rendering

The system SHALL surface tower discovery to the player as they roam, popping up hidden towers on approach and clearing a fog overlay as the team covers a fog-revealed area.

#### Scenario: A hidden tower pops up on approach

- **WHEN** a player walks within a `HIDDEN` tower's proximity while the app is reporting position
- **THEN** the app SHALL receive the newly revealed tower (see the `discovery-tracking` capability) and surface it on the map with a discovery cue

#### Scenario: Fog overlay for fog-revealed zones

- **WHEN** a game uses `FOG_REVEAL` towers
- **THEN** the app SHALL render not-yet-revealed areas under a fog overlay and progressively clear covered area as the team roams
- **AND** a `FOG_REVEAL` zone and its towers SHALL appear only once the team reveals them by entering the zone or crossing the zone's coverage threshold

#### Scenario: Position reporting requires consent

- **WHEN** discovery depends on continuous position reporting
- **THEN** the app SHALL report positions only after the player has granted location consent (see the `live-location` capability), falling back to `POST /api/discovery/ping/` when a live-location stream is not available
