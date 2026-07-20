## ADDED Requirements

### Requirement: Creator authors the template

The system SHALL distinguish the **creator** who authors a Game (template) from the **runner** who runs a Session under it, and record the creator on the Game.

#### Scenario: Recording the creator

- **WHEN** a Game is created
- **THEN** the system SHALL set `Game.created_by` to the authoring user (the creator)
- **AND** the creator SHALL be permitted to edit the Game's collections, rules, challenge bank, TeamGroup taxonomy, and role definitions

### Requirement: Runner runs sessions

The system SHALL let a runner launch and control Sessions under a Game without granting them edit rights on the original template.

#### Scenario: Running without authoring

- **WHEN** a runner creates or controls a Session under a Game they do not own
- **THEN** the system SHALL permit start, pause, resume, and finish of that Session
- **AND** it SHALL deny mutation of the original Game's template data unless the runner is also its creator or an authorised collaborator

### Requirement: Cloning a template

The system SHALL let a runner clone a Game so they can personalise it and run the clone instead of the original.

#### Scenario: Cloning deep-copies the template, shares the geometry

- **WHEN** a user calls `POST /api/staff/games/{id}/clone/`
- **THEN** the system SHALL create a new Game whose rules config, challenge bank, TeamGroup taxonomy, and role definitions are deep-copied from the source
- **AND** the clone SHALL link to the **same** Collections (and therefore the same Towers and Zones) as the source, sharing geometry by reference rather than duplicating it
- **AND** the clone SHALL record `cloned_from` pointing at the source Game, and set `created_by` to the cloning user

#### Scenario: Clone edits do not affect the original

- **WHEN** the owner of a clone adds challenges or changes rules on the clone
- **THEN** the original Game SHALL be unaffected
