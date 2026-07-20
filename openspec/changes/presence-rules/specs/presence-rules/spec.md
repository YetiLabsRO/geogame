## ADDED Requirements

### Requirement: Team togetherness configuration

The system SHALL let each Game configure whether a team must be together to complete a challenge, as a default with a nullable per-Session override, defaulting to allowing the team to split.

#### Scenario: Configuring togetherness

- **WHEN** a creator sets `togetherness_mode` on a Game or a runner overrides it on a Session
- **THEN** the value SHALL be one of `SPLIT_ALLOWED` or `WHOLE_TEAM_TOGETHER`, defaulting to `SPLIT_ALLOWED`
- **AND** the effective value SHALL resolve through `Session.effective('togetherness_mode')` (Session override wins, else Game default)

#### Scenario: Whole team required

- **WHEN** the effective `togetherness_mode` is `WHOLE_TEAM_TOGETHER`
- **THEN** any presence check for that Session SHALL require the full active team to be present (see the effective-resolution requirement)
- **AND** this SHALL apply regardless of a challenge's own `min_members_present`

#### Scenario: Splitting allowed by default

- **WHEN** a Game is created without configuring presence
- **THEN** `togetherness_mode` SHALL be `SPLIT_ALLOWED` and members MAY act independently
- **AND** no togetherness constraint SHALL be imposed on submissions

### Requirement: Teammate map visibility configuration

The system SHALL let each Game configure which other players a player sees on the map, as a default with a nullable per-Session override, and this configuration SHALL be the source of truth that the live-location plotting reads (see the `live-location` capability).

#### Scenario: Choosing a visibility mode

- **WHEN** a creator sets `teammate_visibility_mode` on a Game or a runner overrides it on a Session
- **THEN** the value SHALL be one of `OWN_TEAM` (default), `EVERYONE`, or `SELECT_COUNT`
- **AND** when the mode is `SELECT_COUNT`, `teammate_visibility_count` SHALL specify how many other players are shown

#### Scenario: Own-team-only default

- **WHEN** the effective `teammate_visibility_mode` is `OWN_TEAM`
- **THEN** a player SHALL be shown only members of their own team on the map
- **AND** the live-location plotting SHALL consume this resolved value rather than defining its own visibility rule (see the `live-location` capability)

#### Scenario: Select a number of people

- **WHEN** the effective mode is `SELECT_COUNT` with `teammate_visibility_count = N`
- **THEN** a player SHALL be shown at most the nearest `N` other players
- **AND** when the mode is `EVERYONE` a player SHALL be shown all live players in the Session

### Requirement: Per-challenge minimum members present

The system SHALL model `game.PresenceRequirement` as a reusable requirement that a Challenge MAY reference through a nullable `presence_requirement` foreign key, where a null reference means the challenge has no presence requirement.

#### Scenario: Attaching a requirement

- **WHEN** a creator attaches a `PresenceRequirement` to a Challenge
- **THEN** it SHALL define `min_members_present` (default `1`), a `method` of `GEOFENCE`, `PHOTO`, or `GEOFENCE_OR_PHOTO`, an optional `geofence_radius_meters`, and an optional `window_seconds`
- **AND** the same `PresenceRequirement` MAY be referenced by more than one Challenge

#### Scenario: No requirement by default

- **WHEN** a Challenge has `presence_requirement = NULL`
- **THEN** the challenge SHALL impose no minimum beyond the submitter themselves
- **AND** removing a `PresenceRequirement` referenced by a Challenge SHALL set the reference to `NULL` and SHALL NOT delete the Challenge

### Requirement: Effective presence resolution

The system SHALL resolve an effective presence requirement per submission as a pure function of the Session config, the challenge's `PresenceRequirement`, and the tower.

#### Scenario: Resolving the required member count

- **WHEN** presence is resolved for a submission
- **THEN** the required member count SHALL be the submitting team's active-membership count when the effective `togetherness_mode` is `WHOLE_TEAM_TOGETHER`, otherwise the requirement's `min_members_present` (default `1`)
- **AND** a null `PresenceRequirement` SHALL resolve to `min_members = 1`, `method = GEOFENCE`, the tower's effective `proximity_meters` as radius, and the Session's effective `presence_window_seconds` as window

#### Scenario: Resolving radius and window fallbacks

- **WHEN** the requirement leaves `geofence_radius_meters` or `window_seconds` unset
- **THEN** the geofence radius SHALL fall back to the tower's effective `proximity_meters` (see the `challenge-submission` and `geographic-map` capabilities)
- **AND** the window SHALL fall back to the Session's effective `presence_window_seconds`

### Requirement: Geofence presence verification

The system SHALL verify presence by counting distinct active teammates whose recent live-location is inside the geofence around the tower, treating geofencing as the primary verification method.

#### Scenario: Enough members inside the geofence

- **WHEN** presence is evaluated with a required count of `N`
- **THEN** a teammate SHALL count as present when their most recent live-location ping is fresh and lies within the geofence radius of the tower (see the `live-location` capability)
- **AND** the submitter SHALL always count as one present member from their submission GPS even if their ping is momentarily stale
- **AND** the check SHALL pass only when at least `N` distinct active members are counted present

#### Scenario: Not enough members present

- **WHEN** fewer than `N` distinct active members are inside the geofence
- **THEN** the check SHALL fail with reason `INSUFFICIENT_MEMBERS_PRESENT`
- **AND** when a specific required member is located outside the geofence the reason SHALL be `MEMBER_OUTSIDE_GEOFENCE`

### Requirement: Photo fallback presence verification

The system SHALL support a photo of the required people as a fallback presence method, treated as weaker evidence than geofencing and never auto-confirmed.

#### Scenario: Photo method routes to review

- **WHEN** the effective method is `PHOTO`, or is `GEOFENCE_OR_PHOTO` and geofence or window data is insufficient
- **THEN** the system SHALL accept a submitted photo of the required people as presence evidence
- **AND** the submission SHALL be left `PENDING` for staff review and SHALL NOT be automatically confirmed
- **AND** the requirement SHALL note that photo evidence is weaker because it is easily AI-edited

### Requirement: Continuous-tracking window verification

The system SHALL strengthen presence by verifying a window of continuous movement when a window is configured, because a trajectory over a duration is harder to spoof than a single point and it also corrects GPS error.

#### Scenario: Verifying a movement window

- **WHEN** the effective `window_seconds` is greater than `0`
- **THEN** each counted member's live-location pings across the last `window_seconds` SHALL all lie within the geofence for the member to be considered present (see the `live-location` capability)
- **AND** momentary GPS jitter that stays within the geofence SHALL still pass, so the window smooths location error

#### Scenario: Window not satisfied

- **WHEN** a required member was inside the geofence only at the final instant but not across the window
- **THEN** the check SHALL fail with reason `PRESENCE_WINDOW_NOT_SATISFIED`

#### Scenario: Point-in-time when no window

- **WHEN** the effective `window_seconds` is `0`
- **THEN** presence SHALL be evaluated on the most recent fresh ping only (point-in-time), preserving today's behaviour

### Requirement: Presence evidence record

The system SHALL persist a `game.PresenceCheck` record linked to the submission capturing what was verified, so staff review and later disputes are auditable.

#### Scenario: Recording a presence check

- **WHEN** a presence-gated submission is evaluated
- **THEN** the system SHALL create a `PresenceCheck` linked to the `TeamTowerChallenge` recording the resolved required count, the method used, the set of verified member ids, and whether the window was satisfied
- **AND** the record SHALL be exposed on the staff review surface (see the `challenge-submission` capability)

### Requirement: Presence configuration API

The system SHALL expose the presence configuration and requirements over the staff/creator REST API and expose a player-facing presence status for the current tower.

#### Scenario: Managing presence configuration

- **WHEN** a staff user edits a Game or Session, or calls `GET/POST/PATCH/DELETE /api/staff/presence-requirements/`
- **THEN** the system SHALL accept the four presence knobs (`togetherness_mode`, `teammate_visibility_mode`, `teammate_visibility_count`, `presence_window_seconds`) and let them list, create, edit, and delete `PresenceRequirement`s
- **AND** the challenge editor SHALL accept a `presence_requirement` reference

#### Scenario: Player presence status

- **WHEN** a player views the challenge for the tower they are at
- **THEN** the system SHALL report the required member count, the currently-present member count, and whether a photo fallback is offered
- **AND** it SHALL update as teammates enter or leave the geofence

### Requirement: Presence rules default to no requirement

The system SHALL default every presence control so that an unconfigured Game behaves exactly as before this capability existed.

#### Scenario: Unconfigured game is unchanged

- **WHEN** a Game is created and no presence configuration is set on it or its Sessions and its challenges reference no `PresenceRequirement`
- **THEN** `togetherness_mode` SHALL be `SPLIT_ALLOWED`, `teammate_visibility_mode` SHALL be `OWN_TEAM`, and `presence_window_seconds` SHALL be `0`
- **AND** submissions SHALL impose no presence constraint beyond the submitter's own proximity check (see the `challenge-submission` capability)
