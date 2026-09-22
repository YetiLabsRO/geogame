## MODIFIED Requirements

### Requirement: Player SPA scope

The system SHALL provide an Angular player app covering all player-facing functionality, organised in the designed tabbed shell and runnable both in a browser and inside the native shell.

#### Scenario: Player routes

- **WHEN** a player uses the app
- **THEN** it SHALL provide auth screens (login, register, password reset, invite-accept), the main map, per-TeamGroup score maps at `/map/<team_group_slug>/`, tower detail, challenge submission, RFID capture, and a rules page
- **AND** it SHALL be built with standalone components, signals, `@if`/`@for` control flow, `input()`/`output()`/`inject()`, and `ChangeDetectionStrategy.OnPush`
- **AND** it SHALL consume the DRF API; Django templates for these routes have been removed
- **AND** it SHALL reach device capabilities (geolocation, NFC, push, haptics, keep-awake, network, BLE) only through the shared platform services so the same code runs on the web and in the native shell

## ADDED Requirements

### Requirement: Tabbed navigation shell

The system SHALL present the player app inside a top app bar and a four-tab bottom navigation: Journey, Society, Chronicle, Ledger.

#### Scenario: Tabs and their content

- **WHEN** an authenticated player with a selected Session uses the app
- **THEN** the bottom navigation SHALL offer Journey (live map, tower detail, scan, trail), Society (my team, browse/create/join teams, requests, share), Chronicle (session history and detail) and Ledger (live scoreboard, my team's locked and floating score, Dementors status, settings, rules, sign out)
- **AND** the top app bar SHALL show the current Session name
- **AND** the active tab SHALL be highlighted for any route inside its section

#### Scenario: Existing links keep working

- **WHEN** a player opens an existing path such as `/tower/<id>`, `/nfc/<token>`, `/join/<code>`, `/team/<id>/share` or `/history/<id>`
- **THEN** the route SHALL resolve to the same screen inside the shell, and `/journey`, `/society`, `/chronicle` SHALL redirect to their tab roots

#### Scenario: Shell hidden on auth flows

- **WHEN** the player is on a login, register, reset, invite or session-picker screen
- **THEN** the bottom navigation SHALL NOT be shown

### Requirement: Theme and safe areas

The system SHALL render the player app with the shared design system in light and dark themes and respect device safe areas.

#### Scenario: Theme follows the OS

- **WHEN** the player has not chosen a theme
- **THEN** the app SHALL follow `prefers-color-scheme`, and a Ledger setting SHALL let the player force light or dark, persisted locally
- **AND** on native the status bar style SHALL match the active theme

#### Scenario: Notched devices

- **WHEN** the app runs on a device with display cut-outs or a home indicator
- **THEN** the top app bar and bottom navigation SHALL pad by the safe-area insets and no content SHALL sit under the cut-out

### Requirement: Tower detail follows the Tower Challenge design

The system SHALL render the tower detail screen after the Figma Tower Challenge (Trial) screen.

#### Scenario: Trial screen

- **WHEN** a player opens a tower
- **THEN** the screen SHALL show the tower name and zone as a hero, the live distance readout with a `ui-progress-meter`, the challenge text in a card, the photo capture control, a primary submit button disabled when out of range, and the cooldown countdown after a rejection, in both themes
