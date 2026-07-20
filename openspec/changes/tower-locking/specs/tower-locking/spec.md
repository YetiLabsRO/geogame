## ADDED Requirements

### Requirement: Formal challenge lifecycle

The system SHALL model a challenge attempt as three explicit phases — **identify**, **initiate**, and **finish** — so contention and locking can hook into named transitions.

#### Scenario: Identifying a tower

- **WHEN** a team calls `POST /api/towers/{id}/identify/`
- **THEN** the system SHALL return that team's next challenge for the tower (via `Tower.get_next_challenge`)
- **AND** the call SHALL have no side effects and SHALL be safe to repeat, so identifying never commits the team or affects any lock

#### Scenario: Initiating a challenge

- **WHEN** a team calls `POST /api/towers/{id}/initiate/` to commit to attempting the tower's challenge
- **THEN** the system SHALL apply the effective `tower_lock_mode` for the Session (see the "Locking mode is configurable" requirement)
- **AND** the system SHALL treat the subsequent challenge submission as the **finish** phase (see the `challenge-submission` capability)

#### Scenario: Finishing a challenge

- **WHEN** a team submits its completed challenge and staff confirm it
- **THEN** the system SHALL capture the tower for that team via `tower.assign_to_team(team)` (see the `scoring` capability)
- **AND** the finish phase SHALL be the only phase that transfers tower ownership

### Requirement: Locking mode is configurable per Game with a per-Session override

The system SHALL resolve the tower locking mode from the current Session's effective `tower_lock_mode`, defaulting to `FREE_FOR_ALL` so existing games are unchanged.

#### Scenario: Choosing a mode

- **WHEN** a creator configures a Game or a runner configures a Session
- **THEN** `tower_lock_mode` SHALL be one of `FREE_FOR_ALL` or `LOCK_ON_INITIATE`
- **AND** the Game default SHALL be `FREE_FOR_ALL`
- **AND** a Session MAY override the mode; the effective value SHALL be resolved by `Session.effective('tower_lock_mode')` (session override wins, else Game default)

#### Scenario: Default preserves current behavior

- **WHEN** neither the Game nor the Session sets a non-default locking configuration
- **THEN** the effective mode SHALL be `FREE_FOR_ALL`
- **AND** contention SHALL be governed only by the existing rejection cooldown (see the `challenge-submission` capability), reproducing today's behavior with no change

### Requirement: TowerLock record

The system SHALL persist each exclusive attempt window as a `game.TowerLock` so lock state is observable and auditable.

#### Scenario: Recording a lock

- **WHEN** a lock is created for a team on a tower
- **THEN** the system SHALL store `tower`, `team`, `started_at`, and `expires_at`
- **AND** it SHALL store a nullable `released_at` and a `release_reason` of `FINISHED`, `EXPIRED`, or `CANCELLED`
- **AND** a lock SHALL be considered **active** only while `released_at` is null and `expires_at` is in the future

#### Scenario: At most one active lock per tower per group

- **WHEN** the system attempts to create a lock on a tower for a team's TeamGroup
- **THEN** it SHALL enforce at most one active lock per `(tower, TeamGroup)` via a partial-unique constraint
- **AND** a second concurrent attempt to lock the same tower for the same group SHALL fail atomically rather than create a duplicate

### Requirement: Mode LOCK_ON_INITIATE locks the tower to the initiating team

Under `LOCK_ON_INITIATE`, the system SHALL lock a tower to the team that initiates its challenge for the effective finish time-limit, and SHALL block other teams in the same TeamGroup from initiating while the lock is active.

#### Scenario: Initiating acquires a lock

- **WHEN** a team initiates a challenge on an unlocked tower and the effective mode is `LOCK_ON_INITIATE`
- **THEN** the system SHALL create a `TowerLock` with `started_at = now` and `expires_at = now + effective(tower_lock_finish_minutes)` minutes
- **AND** the tower SHALL be reported as locked to that team for its TeamGroup

#### Scenario: Locked tower blocks other teams

- **WHEN** a team attempts to initiate on a tower that holds an active lock for another team in the same TeamGroup
- **THEN** the system SHALL refuse the initiation with a conflict response
- **AND** the tower SHALL remain locked to the original team until the lock is released or expires

#### Scenario: Finishing captures and releases

- **WHEN** the lock-holding team's submission is confirmed before the lock expires
- **THEN** the system SHALL capture the tower via `tower.assign_to_team(team)` (see the `scoring` capability)
- **AND** the system SHALL release the team's active lock with `release_reason = FINISHED`

#### Scenario: Expiry releases the tower

- **WHEN** an active lock's `expires_at` passes without a confirmed finish
- **THEN** the system SHALL treat the tower as free on the next read (lazy expiry) and a sweep SHALL set `released_at` with `release_reason = EXPIRED`
- **AND** any team in the group MAY then initiate on the tower again
- **AND** the expired lock SHALL NOT capture the tower and SHALL NOT award any points (see the `scoring` capability)

### Requirement: Mode FREE_FOR_ALL awards the tower on completion

Under `FREE_FOR_ALL`, the system SHALL allow multiple teams to attempt a tower simultaneously and SHALL award it to the team whose finish is confirmed most recently, passing to whoever finishes next.

#### Scenario: Simultaneous attempts

- **WHEN** the effective mode is `FREE_FOR_ALL` and several teams initiate on the same tower
- **THEN** the system SHALL NOT create any exclusive lock
- **AND** every team MAY submit its challenge for that tower concurrently, subject only to the existing rejection cooldown (see the `challenge-submission` capability)

#### Scenario: Last completion owns the tower

- **WHEN** two teams in the same TeamGroup both have confirmed finishes on a tower under `FREE_FOR_ALL`
- **THEN** the tower SHALL be owned by the team whose finish was confirmed last
- **AND** on the next team's confirmed finish, ownership SHALL pass to that team, closing the prior owner's ownership window (see the `scoring` capability)

### Requirement: Lock visibility

The system SHALL expose active lock state to players and staff so clients can render lock status and finish-deadline countdowns.

#### Scenario: Staff view active locks

- **WHEN** staff request `GET /api/staff/tower_locks/`
- **THEN** the system SHALL return the active locks in scope with their `tower`, `team`, TeamGroup, `started_at`, `expires_at`, and remaining seconds
- **AND** expired or released locks SHALL be excluded from the active list

#### Scenario: Player sees lock status

- **WHEN** a player views a tower under `LOCK_ON_INITIATE`
- **THEN** the system SHALL indicate whether the tower is locked-by-the-player's-team, locked-by-another-team, or free for the player's TeamGroup
- **AND** for a lock held by the player's team it SHALL expose the finish deadline so the client can show a countdown
