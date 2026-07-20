## MODIFIED Requirements

### Requirement: Live map rendering

The system SHALL render a live Leaflet map of zones and active towers colored by current TeamGroup control, updating in real time over a websocket with polling retained as a graceful fallback.

#### Scenario: Viewing the map

- **WHEN** a player opens the main map
- **THEN** it SHALL render zones and active towers via Leaflet, colored by current per-TeamGroup ownership
- **AND** it SHALL update in real time from `tower.ownership_changed` and `zone.control_changed` events over the Session websocket (see the `realtime-updates` capability), recoloring the affected geometry without a full reload

#### Scenario: Reconciling on connect

- **WHEN** the player app opens or reopens the map websocket
- **THEN** it SHALL fetch a fresh REST snapshot of zones/towers and reconcile it before applying subsequent live events, so a missed event never leaves the map stale

#### Scenario: Polling fallback

- **WHEN** the websocket cannot be established or is disconnected, or the Session's effective `realtime_enabled` is false
- **THEN** the app SHALL fall back to updating the map via polling or a refresh action, with no loss of correctness — superseding the earlier "no websockets required" stance while preserving polling as the fallback

## ADDED Requirements

### Requirement: Live scoreboard and overtake awareness

The system SHALL show the player a live scoreboard of every team's totals that updates in real time, so the player can tell when they are being overtaken.

#### Scenario: Watching standings update

- **WHEN** a player views the scoreboard and any team's locked or floating total changes
- **THEN** the app SHALL update that team's total in real time from a `scoreboard.updated` event over the Session websocket (see the `realtime-updates` capability)
- **AND** it SHALL visibly indicate when the player's own team is overtaken by another team

#### Scenario: Polling fallback for the scoreboard

- **WHEN** the websocket is unavailable or the Session's effective `realtime_enabled` is false
- **THEN** the app SHALL refresh the scoreboard by polling the REST API, and the standings SHALL remain correct, differing only in immediacy
