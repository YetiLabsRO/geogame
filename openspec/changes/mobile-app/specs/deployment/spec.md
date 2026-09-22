## ADDED Requirements

### Requirement: Native app origins

The system SHALL accept API and websocket traffic from the native app's WebView origins.

#### Scenario: CORS for the shell

- **WHEN** the native app (origin `https://localhost` on Android, `capacitor://localhost` on iOS) calls the API
- **THEN** Django SHALL answer with CORS headers allowing those origins (plus any listed in `CORS_EXTRA_ORIGINS`) and the token-authenticated websocket SHALL accept the connection

### Requirement: App-link verification files

The system SHALL serve the Android and iOS app-link verification documents from settings.

#### Scenario: Well-known documents

- **WHEN** a client requests `/.well-known/assetlinks.json` or `/.well-known/apple-app-site-association`
- **THEN** Django SHALL return `application/json` documents built from `MOBILE_APP_LINKS` (package `ro.yetilabs.geogame`, configured SHA-256 signing fingerprints, Apple app id) covering the `/nfc/*`, `/join/*` and `/invite/*` paths, with empty fingerprint lists when none are configured yet
