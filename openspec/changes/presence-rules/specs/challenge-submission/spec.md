## ADDED Requirements

### Requirement: Presence enforcement on submission

The system SHALL enforce the challenge's effective presence requirement on a submission, in addition to the submitter's own proximity check, so a submission is accepted only when the required teammates are actually present (see the `presence-rules` capability).

#### Scenario: Enough members present

- **WHEN** an authenticated user submits an attempt and the challenge's effective presence requirement demands `N` members present
- **THEN** the system SHALL evaluate co-presence via the `presence-rules` capability (geofence, optional continuous-tracking window, or photo fallback)
- **AND** the submission SHALL proceed to `PENDING` only when at least `N` distinct active members are verified present, or a photo fallback applies

#### Scenario: Presence not satisfied

- **WHEN** the effective presence requirement is not satisfied and no photo fallback applies
- **THEN** the system SHALL reject the submission with a specific reason code (`INSUFFICIENT_MEMBERS_PRESENT`, `MEMBER_OUTSIDE_GEOFENCE`, or `PRESENCE_WINDOW_NOT_SATISFIED`)
- **AND** the rejection SHALL name which condition failed so the team can react

#### Scenario: No requirement is a no-op

- **WHEN** a challenge references no `PresenceRequirement` and the Session's effective `togetherness_mode` is `SPLIT_ALLOWED` with `presence_window_seconds = 0`
- **THEN** the presence step SHALL impose no constraint beyond the submitter's proximity check
- **AND** the submission SHALL behave exactly as before this capability existed

### Requirement: Presence evidence on the review surface

The system SHALL record and expose the presence evidence for a submission so staff can review who was verified present and how.

#### Scenario: Reviewing presence evidence

- **WHEN** a staff member opens a presence-gated submission for review
- **THEN** the review surface SHALL expose the linked `PresenceCheck` (required vs present member counts, the method used, and whether the window was satisfied) alongside the existing photo and response text (see the `presence-rules` capability)
- **AND** a submission accepted via the photo fallback SHALL remain `PENDING` until a staff member confirms the required people are present

## MODIFIED Requirements

### Requirement: Authenticated submission with proximity check

The system SHALL accept a challenge submission only from an authenticated user standing near the tower, deriving the submitting team from the user's active membership, and SHALL additionally enforce the challenge's effective presence requirement before the submission is accepted.

#### Scenario: Submitting a challenge

- **WHEN** an authenticated user submits an attempt via `POST /api/team_tower_challenges/`
- **THEN** the submission SHALL include the tower, the challenge, the submitter's current GPS position, and optionally a photo
- **AND** the system SHALL derive the team from the authenticated user's active `TeamMembership` and record `submitted_by`
- **AND** the system SHALL create a `TeamTowerChallenge` with outcome `PENDING`

#### Scenario: Rejecting a distant submission

- **WHEN** the submitter's GPS position is farther than the current Session's `proximity_meters` from the tower
- **THEN** the system SHALL reject the submission
- **AND** the threshold SHALL be read from the current Session's Game config (default 50 meters), not hardcoded

#### Scenario: Enforcing presence after proximity

- **WHEN** the submitter's own proximity check passes and the challenge has an effective presence requirement
- **THEN** the system SHALL additionally evaluate the presence requirement (minimum members co-present in the geofence, optionally over a continuous window, or a staff-reviewed photo fallback) before accepting the submission (see the `presence-rules` capability)
- **AND** when the presence requirement is the default null requirement, this step SHALL be a no-op preserving the base behaviour
