## ADDED Requirements

### Requirement: FCM delivery for native subscriptions

The system SHALL deliver notifications to `FCM`-kind subscriptions through Firebase Cloud Messaging when credentials are configured, alongside Web Push for `WEBPUSH`-kind subscriptions.

#### Scenario: Sending to a native device

- **WHEN** a notification event fires for a consented subscriber whose subscription kind is `FCM` and `FCM_CREDENTIALS_FILE` (or `GOOGLE_APPLICATION_CREDENTIALS`) is configured
- **THEN** the system SHALL send an FCM HTTP v1 message to the stored device token carrying the same title, body and data (including the `url`) that the Web Push payload carries

#### Scenario: Invalid or unregistered token

- **WHEN** FCM reports the token unregistered or the sender id mismatched
- **THEN** the system SHALL revoke that subscription and SHALL NOT send to it again, mirroring the Web Push 404/410 handling

#### Scenario: No FCM credentials

- **WHEN** no FCM credentials are configured
- **THEN** `FCM` subscriptions SHALL be logged and not delivered, and Web Push delivery SHALL be unaffected
