## MODIFIED Requirements

### Requirement: Live map data with ownership coloring

The system SHALL expose zones and active towers over a REST API so clients can render a live map colored by current control, and SHALL additionally broadcast ownership and zone-control changes in real time so clients recolor the affected geometry without waiting for a poll. This supersedes the previous polling-only stance: the REST snapshot remains the source of truth for initial load and reconciliation, while real-time push is the primary freshness mechanism, with polling retained as a graceful fallback.

#### Scenario: Fetching zones

- **WHEN** a client requests `GET /api/zones/`
- **THEN** the system SHALL return zones as GeoJSON (via `rest_framework_gis`) with current per-TeamGroup ownership coloring
- **AND** an optional `group` query parameter SHALL color the zones by the named TeamGroup

#### Scenario: Fetching towers with proximity filtering

- **WHEN** a client requests `GET /api/towers/`
- **THEN** the system SHALL return only active towers as GeoJSON
- **AND** it SHALL accept optional `lat`, `lng`, and `accuracy` query parameters for proximity filtering

#### Scenario: Broadcasting a recolor on ownership change

- **WHEN** a tower is conquered, stolen, released, or deactivated and ownership or zone control is recomputed
- **THEN** the system SHALL broadcast a `tower.ownership_changed` event (and a `zone.control_changed` event when zone control flips) to the Session group carrying the affected geometry and its new per-TeamGroup coloring (see the `realtime-updates` capability)
- **AND** connected clients SHALL recolor the affected tower/zone in real time without a full reload

#### Scenario: Polling fallback

- **WHEN** a client cannot establish a websocket, or the Session's effective `realtime_enabled` is false
- **THEN** the client SHALL fall back to polling `GET /api/zones/` and `GET /api/towers/` (or a manual refresh) and the returned data SHALL remain correct, differing from the real-time path only in immediacy
