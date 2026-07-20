## ADDED Requirements

### Requirement: Opt-in push consent and subscriptions

The system SHALL deliver push notifications only to users who have explicitly consented and registered a push subscription, and SHALL let them revoke it at any time.

#### Scenario: Registering a subscription

- **WHEN** a user grants notification permission in the app and the client posts `POST /api/push/subscriptions/` with a Web Push (VAPID) or FCM subscription
- **THEN** the system SHALL store an `organize.PushSubscription` for that user and device (endpoint, keys or FCM token, `created_at`)
- **AND** it SHALL treat the subscription as consented and active

#### Scenario: Revoking a subscription

- **WHEN** a user disables notifications, or the client calls `DELETE /api/push/subscriptions/`
- **THEN** the system SHALL mark the subscription `revoked_at` and SHALL NOT send further notifications to it

#### Scenario: No consent, no push

- **WHEN** a user has no active, consented subscription
- **THEN** the system SHALL NOT send that user any push notification

### Requirement: Per-Game push toggle

The system SHALL gate push notifications behind a per-Game toggle with a per-Session override, defaulting off so existing games are unaffected and small games can opt in deliberately.

#### Scenario: Feature off by default

- **WHEN** neither the Game nor the Session sets `push_notifications_enabled`
- **THEN** its effective value SHALL be false and the system SHALL send no push notifications for that Session

#### Scenario: Session override wins

- **WHEN** a Game sets `push_notifications_enabled` and a Session overrides it
- **THEN** the system SHALL resolve the effective value with the Session override winning over the Game default (via the effective-value helper)

### Requirement: Event-driven notifications

The system SHALL send push notifications on steal, conquer, and bonus events to consented subscribers whose Session has push enabled and whose per-event toggle is on.

#### Scenario: A tower is stolen or conquered

- **WHEN** a tower is stolen or conquered in a Session whose effective `push_notifications_enabled` is true
- **THEN** the system SHALL send a Web Push / FCM notification to each consented subscriber for that Session whose steal/conquer toggle is on
- **AND** the notification SHALL name the tower and the acting team and SHALL deep-link into the relevant tower/map on tap

#### Scenario: A bonus appears

- **WHEN** a score multiplier / bonus becomes active for a Session with push enabled (see the `score-multipliers` capability)
- **THEN** the system SHALL send a bonus notification to consented subscribers whose bonus toggle is on

#### Scenario: Notification preferences

- **WHEN** a user calls `GET/PATCH /api/push/preferences/`
- **THEN** the system SHALL let them read and set per-event toggles (steal, conquer, bonus) stored in an `organize.NotificationPreference`
- **AND** an event whose toggle is off SHALL NOT be delivered to that user

### Requirement: Best-effort delivery and subscription hygiene

The system SHALL treat push as an advisory, best-effort channel that never replaces the in-app real-time/poll path, and SHALL prune dead subscriptions.

#### Scenario: Pruning gone subscriptions

- **WHEN** the push service reports a subscription as gone (HTTP 404 or 410)
- **THEN** the system SHALL mark that subscription inactive and stop sending to it

#### Scenario: Push is not authoritative

- **WHEN** push delivery fails or is unavailable
- **THEN** the system SHALL still reflect the change through the in-app websocket or polling path (see the `realtime-updates` capability), so no state depends on a notification arriving
