## ADDED Requirements

### Requirement: The player app owns its dialogs

The player app SHALL ask every question through the shared dialog service rather than the browser's built-in `confirm`, `alert` or `prompt`.

#### Scenario: Location-tracking consent

- **WHEN** a player is asked to consent to location tracking, or to withdraw that consent
- **THEN** the app SHALL ask in its own dialog, carrying the session's consent text
- **AND** the answer SHALL drive the same consent call the native confirmation drove

#### Scenario: A native dialog cannot creep back

- **WHEN** player-app source calls `confirm`, `alert` or `prompt` on `window`
- **THEN** the test suite SHALL fail, naming the file and line
