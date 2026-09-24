## ADDED Requirements

### Requirement: Session deletion

The system SHALL let a superadmin delete a Session that is no longer live, removing its roster and its recorded run.

#### Scenario: A superadmin deletes a settled session

- **WHEN** a superadmin deletes a Session whose state is draft or finished
- **THEN** the system SHALL remove the Session together with its teams, memberships, ownership records, submissions, pause windows, location and proximity history, discoveries and trail progress
- **AND** any user whose current session was the deleted one SHALL be left with no current session rather than a dangling one
- **AND** the Game and its shared map content SHALL be untouched

#### Scenario: Only a superadmin may delete

- **WHEN** a staff user who is not a superadmin attempts to delete a Session
- **THEN** the system SHALL refuse with 403
- **AND** the refusal SHALL say that deleting a session is reserved to a superadmin

#### Scenario: A live session is refused

- **WHEN** a superadmin attempts to delete a Session that is open for participants, running, or paused
- **THEN** the system SHALL refuse with 409 rather than deleting
- **AND** the refusal SHALL name the session's current state and the action that would settle it — closing participation for one that is open, finishing for one that is running or paused
- **AND** the refusal SHALL carry those blockers in a machine-readable form, in the same shape the start gate already uses, so the staff console can show them as a list rather than as a sentence

#### Scenario: Deleting is not deactivating

- **WHEN** staff want a Session out of the way without losing its history
- **THEN** finishing it SHALL remain the reversible option that preserves every record for history
- **AND** deletion SHALL be irreversible and SHALL NOT be offered as an alternative to it
