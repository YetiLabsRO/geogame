## ADDED Requirements

### Requirement: Background streaming in the native app

The system SHALL keep the location stream alive on native devices while the app is backgrounded, within the same consent and configuration gates that apply in the foreground.

#### Scenario: Backgrounded on native

- **WHEN** the Session's effective `location_tracking_enabled` is true, the player has consented, and the native app is backgrounded or the screen is locked
- **THEN** the app SHALL continue to POST `/api/location/ping/` at the effective `ping_interval_seconds` using the OS background location service, with the Android foreground-service notification visible

#### Scenario: Browser stays foreground-only

- **WHEN** the app runs in a browser
- **THEN** streaming SHALL keep its existing foreground behaviour and pause when the page is hidden, with no new permission prompts
