## ADDED Requirements

### Requirement: Native shell packaging

The system SHALL package the player Angular app as native Android and iOS applications with Capacitor, from the same source and build output that serves the web app.

#### Scenario: Building the Android app

- **WHEN** a developer runs the web production build followed by `cap sync` and the Android Gradle debug build
- **THEN** the system SHALL produce an installable APK with application id `ro.yetilabs.geogame` and display name "Tower Rush" whose WebView loads the built player app
- **AND** the web build output SHALL remain deployable unchanged as the browser app

#### Scenario: iOS project scaffold

- **WHEN** the repository is checked out on macOS
- **THEN** it SHALL contain a generated `ios/` Capacitor project with the same application id, plugin registrations and a documented procedure (CocoaPods install, Associated Domains, push capability) to build it

### Requirement: Platform abstraction layer

The system SHALL expose device capabilities to the player app through platform services in the shared library that choose a native plugin implementation when running inside the Capacitor shell and the browser implementation otherwise, so screens never branch on the runtime themselves.

#### Scenario: Geolocation on native and web

- **WHEN** a screen asks the geolocation service for the current position or a position watch
- **THEN** on native it SHALL use the Capacitor geolocation plugin and on the web `navigator.geolocation`, returning the same position shape to the caller

#### Scenario: Capability not available

- **WHEN** a capability (NFC, BLE, background location, push) is unsupported on the current runtime
- **THEN** the corresponding service SHALL report it as unsupported and the screen SHALL fall back to its existing degraded path (manual entry, simulator, foreground timer, no push) without error

### Requirement: Configurable API origin

The system SHALL let the native app reach the backend at a configured absolute origin while the web app keeps using same-origin relative URLs.

#### Scenario: Native request prefixing

- **WHEN** the app runs inside the native shell and issues a request whose URL starts with `/`
- **THEN** the interceptor SHALL prefix it with the configured native API origin (production `https://cercetador.albascout.ro`, development the emulator host) before the auth token is attached
- **AND** the realtime websocket URL and relative media URLs SHALL use the same origin

#### Scenario: Web request untouched

- **WHEN** the app runs in a browser
- **THEN** requests SHALL keep their relative URLs so the dev proxy and same-origin deployment work unchanged

#### Scenario: Debug origin override

- **WHEN** a tester sets a server override in a development native build
- **THEN** the override SHALL persist across restarts and take precedence over the built-in native origin until cleared

### Requirement: Native push registration

The system SHALL register native devices for push notifications through the platform push service using FCM device tokens.

#### Scenario: Opting in on a native device

- **WHEN** a player enables notifications inside the native app and grants the OS permission
- **THEN** the app SHALL obtain an FCM device token and POST it to `/api/push/subscriptions/` as `fcm_token`
- **AND** disabling notifications SHALL revoke that subscription

#### Scenario: Handling a received notification

- **WHEN** a push notification arrives while the native app is in the foreground
- **THEN** the app SHALL show it as an in-app toast
- **AND** tapping a notification from the tray SHALL navigate to the `url` carried in the payload

### Requirement: Native NFC scanning

The system SHALL read NDEF tags through the native NFC plugin on both Android and iOS inside the shell, feeding the same token into the existing capture endpoint.

#### Scenario: Scanning inside the shell

- **WHEN** a player starts a scan on a native device with NFC hardware
- **THEN** the app SHALL open the OS NFC reader session, extract the tag token from the NDEF payload (URI or custom-scheme record) and POST it to `/api/nfc/capture/` with live GPS, exactly as the Web NFC path does

#### Scenario: Web NFC still used in the browser

- **WHEN** the app runs in Android Chrome
- **THEN** it SHALL keep using the Web NFC `NDEFReader` path

### Requirement: Background location on native

The system SHALL keep streaming location pings on native while the app is in the background, subject to the Session's tracking configuration and the player's consent.

#### Scenario: App backgrounded during a tracked session

- **WHEN** tracking is enabled, consent is granted and the native app moves to the background or the screen locks
- **THEN** the app SHALL keep sending pings at the Session's `ping_interval_seconds` through the background location watcher, showing the OS-required foreground-service notification on Android

#### Scenario: Tracking stops

- **WHEN** tracking is disabled, consent is withdrawn, or the player signs out
- **THEN** the background watcher SHALL be removed and no further pings sent

### Requirement: Haptics and keep-awake

The system SHALL give tactile feedback for game events and keep the screen on where a mode needs it.

#### Scenario: Capture feedback

- **WHEN** a capture is confirmed, a tower is stolen from the player's team, or a bonus pop-up arrives
- **THEN** the app SHALL trigger a haptic pattern on native (`@capacitor/haptics`) and `navigator.vibrate` on the web where available

#### Scenario: Dementors screen

- **WHEN** the Dementors screen is open on native
- **THEN** the app SHALL keep the screen awake through the native keep-awake plugin and release it on leave

### Requirement: Deep links and app links

The system SHALL open the app from tag, join and invite links and route them to the matching screen.

#### Scenario: Universal/App Link opened

- **WHEN** the installed app receives `https://cercetador.albascout.ro/nfc/<token>/`, `/join/<code>` or `/invite/<token>`, or the custom scheme `cercetador://nfc/<token>`
- **THEN** the app SHALL navigate to the corresponding in-app route without loading the web landing page

#### Scenario: Android back button

- **WHEN** the player presses the hardware back button
- **THEN** the app SHALL navigate back in history, or exit when already at a tab root

### Requirement: BLE proximity bridge

The system SHALL provide a BLE advertise/scan bridge for the proximity substrate inside the native shell.

#### Scenario: Native advertise and scan

- **WHEN** the Dementors screen runs on a native device with BLE and the bridge reports it capable
- **THEN** the app SHALL advertise the player's ephemeral token in service data under the game's service UUID and scan for peers' tokens with RSSI, posting observations to `/api/proximity/reports/` at the configured cadence

#### Scenario: Web runtime

- **WHEN** the screen runs in a browser
- **THEN** the bridge SHALL report `capable() === false` and the simulator panel SHALL remain the only input

### Requirement: Build and release plumbing

The system SHALL document and script the native build so a developer can go from checkout to an installable Android debug build and knows the external prerequisites for release.

#### Scenario: Scripts and runbook

- **WHEN** a developer reads `docs/mobile.md` and the npm scripts
- **THEN** they SHALL find the commands for syncing, opening and building each platform, where to place `google-services.json`, how to configure signing and verify App Links, and the macOS-only iOS steps
