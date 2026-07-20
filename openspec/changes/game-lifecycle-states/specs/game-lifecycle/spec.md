## MODIFIED Requirements

### Requirement: Session deactivation closes its ownerships

The system SHALL release a Session's ownerships when it reaches the terminal `FINISHED` lifecycle state (the successor to the old `is_active = False` deactivation), while preserving all records for history.

#### Scenario: Finishing a session

- **WHEN** a Session transitions to `FINISHED` via the `finish` action (see the `session-lifecycle` capability), which supersedes setting `is_active` to `False`
- **THEN** the system SHALL close all open `TeamTowerOwnership` and `TeamZoneOwnership` records on that Session (same semantics as `unassign_all`)
- **AND** the system SHALL preserve those records so the Session remains visible in history (see the `session-history` capability)

#### Scenario: Finishing a paused session

- **WHEN** a Session that is in `PAUSED` (holding an open `PauseWindow`; see the `day-pausing` capability) transitions to `FINISHED`
- **THEN** the system SHALL close the open `PauseWindow` without reopening ownerships, then close all remaining open ownerships, and preserve every record for history
