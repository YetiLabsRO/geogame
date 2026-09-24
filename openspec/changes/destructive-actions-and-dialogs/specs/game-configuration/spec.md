## ADDED Requirements

### Requirement: Game deletion

The system SHALL let a superadmin delete a Game, removing its configuration and every Session that runs on it, while leaving shared map content intact.

#### Scenario: A superadmin deletes a game

- **WHEN** a superadmin deletes a Game
- **THEN** the system SHALL remove the Game, its challenge bank, roles, collaborators, team-group taxonomy, trails and score multipliers
- **AND** it SHALL remove every Session on that Game, with each Session's teams, memberships and ownership records
- **AND** it SHALL leave the Collections, Towers and Zones the Game referenced in place, because those are shared by reference and belong to the repository rather than to the Game

#### Scenario: Only a superadmin may delete

- **WHEN** a staff user who is not a superadmin attempts to delete a Game
- **THEN** the system SHALL refuse with 403
- **AND** the refusal SHALL say that deleting a game is reserved to a superadmin
- **AND** being the Game's creator or a CREATOR collaborator SHALL NOT grant deletion, although both still grant editing

#### Scenario: A game with a live session is refused

- **WHEN** a superadmin attempts to delete a Game that has any Session in a live state — open for participants, running, or paused
- **THEN** the system SHALL refuse with 409 rather than deleting
- **AND** the refusal SHALL name each live Session and the state it is in
- **AND** it SHALL say what would unblock the deletion: closing participation, or finishing the run

#### Scenario: A game whose sessions are all settled

- **WHEN** a superadmin deletes a Game whose Sessions are all draft or finished
- **THEN** the system SHALL delete the Game and those Sessions
- **AND** a Game with no Sessions at all SHALL delete on the same terms

#### Scenario: A clone's ancestry outlives it

- **WHEN** a Game that other Games were cloned from is deleted
- **THEN** the system SHALL keep those clones
- **AND** each clone's recorded ancestry SHALL become empty rather than dangling
