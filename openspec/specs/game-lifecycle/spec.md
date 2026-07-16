# Game Lifecycle Specification

## Purpose

Define the staff actions that end or reset a run by releasing ownerships: the tower `unassign_all` action, individual tower deactivation, and Session deactivation.

## Requirements

### Requirement: Release all ownerships

The system SHALL provide a staff action that closes every active tower and zone ownership, used to end a round cleanly.

#### Scenario: Running unassign_all

- **WHEN** a staff member runs the Tower admin `unassign_all` action
- **THEN** the system SHALL close every active `TeamTowerOwnership` and `TeamZoneOwnership`

### Requirement: Tower deactivation closes its ownerships

The system SHALL release a tower's ownerships when it is deactivated.

#### Scenario: Deactivating a tower

- **WHEN** a tower's `is_active` is set to `False`
- **THEN** the system SHALL close that tower's active `TeamTowerOwnership`, close any `TeamZoneOwnership` affected, and trigger zone recomputation

### Requirement: Session deactivation closes its ownerships

The system SHALL release a Session's ownerships when the Session is deactivated, while preserving all records for history.

#### Scenario: Deactivating a session

- **WHEN** a Session's `is_active` is set to `False`
- **THEN** the system SHALL close all open `TeamTowerOwnership` and `TeamZoneOwnership` records on that Session (same semantics as `unassign_all`)
- **AND** the system SHALL preserve those records so the Session remains visible in history (see the `session-history` capability)
