## MODIFIED Requirements

### Requirement: Live map data with ownership coloring

The system SHALL expose zones and active towers over a REST API filtered to what the caller's team may currently see, colored by current control subject to the game's other-teams ownership visibility setting.

#### Scenario: Fetching zones

- **WHEN** a client requests `GET /api/zones/`
- **THEN** the system SHALL return zones as GeoJSON (via `rest_framework_gis`) with current per-TeamGroup ownership coloring
- **AND** an optional `group` query parameter SHALL color the zones by the named TeamGroup
- **AND** a zone whose only towers are undiscovered `FOG_REVEAL` towers SHALL be omitted for a team that has not yet revealed it (see the `tower-visibility` and `discovery-tracking` capabilities)

#### Scenario: Fetching towers filtered by team visibility

- **WHEN** a client requests `GET /api/towers/`
- **THEN** the system SHALL return only active towers visible to the caller's team — every `VISIBLE` tower plus every tower the team has discovered (see the `discovery-tracking` capability)
- **AND** it SHALL omit `HIDDEN` and `FOG_REVEAL` towers the caller's team has not yet discovered, at the queryset level so undiscovered geometry never reaches the client
- **AND** it SHALL accept optional `lat`, `lng`, and `accuracy` query parameters for proximity filtering and for driving discovery evaluation

#### Scenario: Respecting other-teams ownership visibility

- **WHEN** the current Session's Game has an effective `reveal_other_teams_ownership` of False
- **THEN** a returned zone or tower SHALL carry ownership coloring only where the caller's own team holds it, without revealing which other team currently holds it
- **AND** when the effective `reveal_other_teams_ownership` is True the system SHALL color by every team's current control as in the shipped behavior

#### Scenario: Staff and omniscient callers see everything

- **WHEN** the caller is staff or has no team context (e.g. a staff overview)
- **THEN** the system SHALL bypass the team-visibility filter and return all active towers and zones with full ownership coloring
