# Staff App Specification

## Purpose

Provide an Angular v21 staff SPA (`frontend/projects/staff`) for common operational tasks — review, CRUD, invites, scoreboard, and game/session management — so staff rarely need the Django admin.

## Requirements

### Requirement: Staff SPA scope

The system SHALL provide a staff app for the most common operational tasks, gated to staff users.

#### Scenario: Staff capabilities

- **WHEN** a staff user opens the app
- **THEN** it SHALL provide a pending review queue, tower/zone/team CRUD, challenge management, invite management, a live scoreboard, and Game/Session management panels
- **AND** access SHALL be gated behind `is_staff=True`
- **AND** a visible "Django Admin" link SHALL remain for rare operations the staff UI does not cover

### Requirement: Pending review queue

The system SHALL provide a queue optimized for fast confirm/reject decisions.

#### Scenario: Reviewing submissions

- **WHEN** a staff member opens the review queue
- **THEN** it SHALL list submissions oldest-first, showing photo, submitter, team, tower, challenge text, and submission timestamp at a glance
- **AND** Confirm and Reject SHALL be one-click actions, with an optional `response_text` modal for Reject

### Requirement: Live scoreboard

The system SHALL show a scoreboard that updates as captures happen.

#### Scenario: Watching the scoreboard

- **WHEN** a staff member opens the scoreboard
- **THEN** it SHALL show each team's locked plus floating score with per-TeamGroup tabs
- **AND** it SHALL refresh automatically (polling every 30s is acceptable; no websockets required)

### Requirement: Games, Sessions, and session switcher

The system SHALL let staff manage Games and Sessions and switch the current Session.

#### Scenario: Managing games and sessions

- **WHEN** a staff member opens the Games or Sessions pages
- **THEN** they SHALL be able to list and edit Games, and list and edit Sessions grouped by Game, with activate/deactivate toggles
- **AND** a navbar current-session switcher SHALL group sessions by Game and re-scope all staff views to the selected Session
