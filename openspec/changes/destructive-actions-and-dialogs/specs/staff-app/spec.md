## ADDED Requirements

### Requirement: Deleting games and sessions from the console

The staff app SHALL offer deletion of Games and Sessions to superadmins, and SHALL NOT offer it to anyone else.

#### Scenario: Who sees the control

- **WHEN** a superadmin opens the Games or Sessions page
- **THEN** each row SHALL carry a delete control, styled as the destructive action it is
- **AND** for a staff user who is not a superadmin the control SHALL be absent rather than present-and-disabled, because an action they can never take is noise

#### Scenario: Deleting asks first

- **WHEN** a superadmin activates a delete control
- **THEN** the app SHALL ask for confirmation in its own dialog before sending anything
- **AND** the dialog SHALL name what is about to go: for a Session, its name and that its teams and records go with it; for a Game, its name, how many Sessions it has, and that those Sessions and their history go with it
- **AND** the dialog SHALL say that the action cannot be undone
- **AND** deleting a Game SHALL require the person to type the Game's slug before the confirm control becomes available

#### Scenario: A refusal is shown where the action was taken

- **WHEN** the server refuses a deletion because the target is live
- **THEN** the app SHALL show the blockers as a list on the row the action was taken from
- **AND** each blocker SHALL name the session and what would settle it
- **AND** the row SHALL remain, unchanged, rather than disappearing optimistically

#### Scenario: After a deletion

- **WHEN** a deletion succeeds
- **THEN** the app SHALL remove the row without a reload
- **AND** if the deleted Session was the current one, the app SHALL clear the current-session selection rather than leave the switcher pointing at nothing

### Requirement: Filtering sessions by game

The staff app SHALL let staff narrow the session list to one Game.

#### Scenario: Choosing a game

- **WHEN** a staff member picks a Game in the session list's game filter
- **THEN** the list SHALL show only that Game's sessions
- **AND** the lifecycle filter — all, active, past — SHALL keep working alongside it rather than being replaced by it
- **AND** choosing no game SHALL restore every game, which SHALL be the default

#### Scenario: A filter that finds nothing

- **WHEN** the combination of filters matches no sessions
- **THEN** the app SHALL say so, and SHALL say which filters are applied
- **AND** it SHALL NOT render an empty heading per game

### Requirement: Status shown as language

The staff app SHALL present every lifecycle and workflow status as a human-readable label through one shared pill component.

#### Scenario: Reading a status

- **WHEN** any status is shown — a session lifecycle state, an invite status, a simulation run status, an authoring proposal status, a trail step state
- **THEN** it SHALL be rendered as words with no underscores, sentence-cased: `OPEN_FOR_PARTICIPANTS` reads `Open for participants`
- **AND** the same status SHALL read the same way on every screen that shows it

#### Scenario: A status the app does not know

- **WHEN** a status arrives that the app has no label for
- **THEN** the pill SHALL humanise it — underscores to spaces, sentence case — rather than showing the raw constant or an empty pill

### Requirement: Legible status pills

Status pills SHALL choose their text colour from the luminance of their fill, and SHALL centre their text within it.

#### Scenario: Ink on a fill

- **WHEN** a pill is drawn on any of the app's status colours
- **THEN** its text colour SHALL be chosen from the fill's relative luminance, taking white on a dark or mid-tone fill and dark ink on a light one
- **AND** a mid-tone fill such as the running-state green SHALL take white text
- **AND** the choice SHALL be made from the theme's own colour tokens, so retinting the theme retints the ink with it, rather than being hand-assigned per status

#### Scenario: Text within the pill

- **WHEN** a pill is drawn
- **THEN** its text SHALL be optically centred within the fill, both horizontally and vertically
- **AND** this SHALL hold for all-caps, mixed-case and descender-bearing labels alike

#### Scenario: Both colour modes

- **WHEN** the app is in dark mode
- **THEN** pills SHALL remain legible under the same luminance rule applied to the dark-mode fills

### Requirement: The app owns its dialogs

The staff app SHALL ask every question through its own dialog, and SHALL NOT use the browser's built-in `confirm`, `alert` or `prompt`.

#### Scenario: The three kinds of question

- **WHEN** the app needs a yes/no decision, needs to state something the person must acknowledge, or needs a short piece of text
- **THEN** it SHALL use the shared dialog service's confirm, alert or prompt respectively
- **AND** each SHALL resolve to the person's answer so the caller can await it exactly as it awaited the native call

#### Scenario: Semantics and keyboard

- **WHEN** a dialog opens
- **THEN** it SHALL be a modal dialog element carrying `role="alertdialog"` when it announces a destructive or irreversible action and `role="dialog"` otherwise
- **AND** it SHALL be labelled by its own title and described by its own message
- **AND** focus SHALL move into the dialog on open, stay within it while it is open, and return to whatever was focused before it opened when it closes
- **AND** Escape and the backdrop SHALL both cancel, returning the same answer as the cancel control
- **AND** the page behind SHALL not scroll while a dialog is open

#### Scenario: A native dialog cannot creep back

- **WHEN** source in either SPA or the shared library calls `confirm`, `alert` or `prompt` on `window`
- **THEN** the test suite SHALL fail, naming the file and line
- **AND** the shared dialog component's own implementation SHALL be the sole exception
