## MODIFIED Requirements

### Requirement: Live scoreboard

The system SHALL show a scoreboard that updates in real time as captures happen, over a websocket, with polling retained as a graceful fallback.

#### Scenario: Watching the scoreboard

- **WHEN** a staff member opens the scoreboard
- **THEN** it SHALL show each team's locked plus floating score with per-TeamGroup tabs
- **AND** it SHALL update in real time from `scoreboard.updated` events over the Session websocket (see the `realtime-updates` capability), reflecting each team's new totals as captures happen

#### Scenario: Polling fallback

- **WHEN** the websocket cannot be established or is disconnected, or the Session's effective `realtime_enabled` is false
- **THEN** the scoreboard SHALL fall back to refreshing automatically by polling (e.g. every 30s), and the totals SHALL remain correct — superseding the earlier "no websockets required" stance while preserving polling as the fallback
