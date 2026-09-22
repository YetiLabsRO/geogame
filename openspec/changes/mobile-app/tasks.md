## 1. Backend: native origins, app links, FCM

- [x] 1.1 Add `django-cors-headers` to `requirements.txt`, `corsheaders` app + middleware, `CORS_ALLOWED_ORIGINS` = `https://localhost`, `capacitor://localhost`, `http://localhost` plus the `CORS_EXTRA_ORIGINS` env list; test that a preflight from `https://localhost` is allowed and an unknown origin is not.
- [x] 1.2 Add `MOBILE_APP_LINKS` setting (`android_package='ro.yetilabs.geogame'`, `android_sha256_fingerprints=[]`, `apple_app_id=''`, `paths=['/nfc/*','/join/*','/invite/*']`, env-overridable) and views for `/.well-known/assetlinks.json` and `/.well-known/apple-app-site-association` (`application/json`, no auth); tests for shape and empty-fingerprint default.
- [x] 1.3 Add `firebase-admin` to `requirements.txt`; implement `FcmPushSender` (HTTP v1 message from the existing payload dict, `UnregisteredError`/`SenderIdMismatchError` → `SubscriptionGone`, else `PushSendError`), `DispatchingPushSender` by subscription kind, `get_sender()` composing WebPush/FCM/Logging from `WEBPUSH_*` and `FCM_CREDENTIALS_FILE`/`GOOGLE_APPLICATION_CREDENTIALS`; update `organize/push.py` docstring.
- [x] 1.4 Tests in `organize/tests.py`: FCM send maps title/body/data/url, unregistered token revokes the subscription, no credentials → logging for FCM while Web Push still sends; `ruff check .` clean and coverage ≥ 80%.

## 2. Shared platform layer and API origin

- [x] 2.1 Add `APP_CONFIG` injection token + `AppConfig` interface in `shared/src/lib/platform/app-config.ts`; player `environments/environment.ts` (`nativeApiBaseUrl: 'http://10.0.2.2:8200'`) and `environment.prod.ts` (`https://cercetador.albascout.ro`) with `fileReplacements` in `angular.json`; provide it in `app.config.ts`.
- [x] 2.2 `PlatformService` (`isNative`, `platform`, `apiBaseUrl()`, `mediaUrl()`, debug override persisted with `@capacitor/preferences`); `apiBaseInterceptor` prefixing `/`-relative requests on native, registered before `tokenInterceptor`; `RealtimeService` builds the websocket URL from the effective origin; audit templates for relative `/media/` `src` and route them through `mediaUrl()`.
- [x] 2.3 `GeolocationService` (`current()`, `watch()`, `clearWatch()`) over `@capacitor/geolocation` / `navigator.geolocation`; migrate `map.component`, `tower-detail.component`, `location-stream.service`, `nfc-scan.component`.
- [x] 2.4 `BackgroundLocationService` over `@capacitor-community/background-geolocation` (native only); `LocationStreamService` uses it on native, throttled to `ping_interval_seconds`, removed on stop/withdraw/sign-out; web path unchanged.
- [x] 2.5 `PushBridge` with web strategy (current service-worker + VAPID flow) and native strategy (`@capacitor/push-notifications`: permission, `register`, `registration` → POST `{fcm_token}`, `pushNotificationReceived` → toast, `pushNotificationActionPerformed` → navigate to `data.url`); player `PushService` and settings screen use the bridge.
- [x] 2.6 `NfcService` (`supported`, `scan()` → token) with Web NFC and `@exxili/capacitor-nfc` strategies sharing one NDEF token extractor (`/nfc/<token>` URI, `cercetador://nfc/<token>`, plain text); `nfc-scan.component` uses it and keeps the QR/manual fallbacks.
- [x] 2.7 `HapticsService`, `KeepAwakeService`, `NetworkService`; wire haptics on capture confirmed / steal / bonus events, keep-awake on the Dementors screen, `FieldSyncService` flush on reconnect.
- [x] 2.8 `DeepLinkService`: `App.appUrlOpen` → strip origin or `cercetador://` scheme → `router.navigateByUrl`; Android `backButton` → history back or `App.exitApp()` at a tab root; started from an `APP_INITIALIZER`.
- [x] 2.9 Token durability: `AuthService` mirrors the token to `@capacitor/preferences` on native; `APP_INITIALIZER` restores it into `localStorage` before routing.
- [x] 2.10 `BleProximityBridge` interface + `BleProximityService` (web: `capable()` false; native: scan through `@capacitor-community/bluetooth-le` filtered on the game service UUID, advertise through the local `BleAdvertiser` plugin from 5.3); Dementors screen advertises/scans through the bridge when capable and reports observations at the configured cadence, keeping the simulator panel otherwise.
- [x] 2.11 Vitest specs: interceptor prefixing (native vs web), platform origin resolution + override, NDEF token extraction, push bridge strategy selection; export everything from `public-api.ts`.

## 3. Design system in `shared`

- [x] 3.1 Add `@fontsource-variable/playfair-display` and `@fontsource-variable/plus-jakarta-sans`; write `shared/src/lib/theme/tokens.scss` (Light on `:root`, Dark under `prefers-color-scheme` guard and `[data-theme="dark"]`, spacing/radius/elevation/typography tokens, `--team-color` slot) and `ThemeService` (system/light/dark, persisted, sets `data-theme`, syncs `@capacitor/status-bar` on native).
- [x] 3.2 Download the 16 icon SVGs from the Figma Icon Set into `shared/src/lib/ui/icons/` and build `ui-icon` (name input, `currentColor`, size input).
- [x] 3.3 `ui-button` (primary/secondary/tinted, sm/md/lg, icon slot, loading, block, `type`), `ui-chip` (brand/solid/slate/neutral, `teamColor`), `ui-field` + `uiInput` directive (label, help, error, id wiring).
- [x] 3.4 `ui-card`, `ui-stat-tile`, `ui-progress-meter` (value/max, tone), `ui-avatar` (initials/image, team colour ring).
- [x] 3.5 `ui-top-app-bar` (title, leading/trailing slots, safe-area top), `ui-bottom-nav` (items with icon/label/route, active by URL prefix, safe-area bottom), `ui-toast` + `ToastService`, `ui-empty-state`.
- [x] 3.6 Export from `public-api.ts`; add a dev-only `/dev/gallery` route in the player showing every component in both themes; vitest smoke specs for button, chip, bottom-nav active state, theme service.

## 4. Player shell and screens

- [x] 4.1 Player `styles.scss`: import tokens + fonts, Bootstrap grid and utilities SCSS only, global resets, safe-area variables; remove `bootstrap.bundle.min.js` and the full Bootstrap CSS from `angular.json` for the player; `index.html` title "Tower Rush", `viewport-fit=cover`, theme-color meta.
- [ ] 4.2 Shell: `app.html` → `ui-top-app-bar` (session name, avatar → Ledger) + `<main>` + `ui-bottom-nav` (Journey `/`, Society `/team`, Chronicle `/history`, Ledger `/ledger`), hidden on auth/session-picker routes; routes add `/ledger` and `/journey`, `/society`, `/chronicle` redirects; all existing paths preserved.
- [ ] 4.3 Ledger screen: live scoreboard (per-TeamGroup standings from `RealtimeService`/API), my team's locked + floating score as stat tiles, Dementors status row, links to Trail, Rules, notification + location settings, theme setting, sign out.
- [ ] 4.4 Journey: full-bleed map under the app bar with a floating Scan action; tower detail rebuilt after the Figma Tower Challenge (Trial) screen (hero, distance + `ui-progress-meter`, challenge card, photo capture, disabled-out-of-range submit, cooldown ring); NFC scan and trail screens restyled.
- [x] 4.5 Society: my team, browse teams, create team, join by code, join requests, share (QR) restyled with cards, chips (team colour), avatars and buttons.
- [ ] 4.6 Chronicle: my sessions list and session detail restyled.
- [ ] 4.7 Auth (login/register/reset/invite), session picker, location consent, notification settings, Dementors, rules screens restyled; toasts replace `alert` boxes.
- [ ] 4.8 Gate: `grep` shows no Bootstrap component classes left in player templates; `ng build player` passes budgets; `ng build staff` still passes; Playwright smoke (login → map) runs against the dev stack.

## 5. Capacitor native projects

- [x] 5.1 Install `@capacitor/{core,cli,android,ios,app,geolocation,push-notifications,haptics,preferences,network,status-bar,splash-screen}`, `@capacitor-community/{keep-awake,background-geolocation,bluetooth-le}`, `@exxili/capacitor-nfc`; write `frontend/capacitor.config.ts` (`ro.yetilabs.geogame`, "Tower Rush", `webDir: 'dist/player/browser'`); npm scripts `cap:sync`, `cap:android`, `cap:ios`, `android:debug`; gitignore `android/local.properties`, `android/app/google-services.json`, build outputs.
- [x] 5.2 `npx cap add android`; manifest permissions (fine/coarse/background location, foreground service location, NFC, Bluetooth scan/advertise/connect, internet, vibrate, post notifications), `<uses-feature>` NFC/BLE not required, intent filters (`autoVerify` https `cercetador.albascout.ro` for `/nfc/`, `/join/`, `/invite/`; `cercetador://` scheme), `google-services.json.example`, `variables.gradle` SDK 35/36 aligned with the installed SDK.
- [x] 5.3 Local `BleAdvertiser` Capacitor plugin: Android (`BluetoothLeAdvertiser`, service data = token under the game UUID, start/stop/isSupported) registered in `MainActivity`; iOS Swift counterpart (`CBPeripheralManager`) written and registered but marked unverified; TypeScript `registerPlugin` definition in `shared/src/lib/platform/ble-advertiser.ts`.
- [x] 5.4 `npx cap add ios`; `Info.plist` usage strings (NFC reader, location when-in-use + always, Bluetooth, camera, photo library), `NFCReaderUsageDescription`, background modes (location, remote-notification), Associated Domains and push entitlement documented.
- [x] 5.5 App icon + splash: `frontend/resources/icon.svg` and `splash.svg` (castle mark on brand sienna) rendered with `@capacitor/assets` for Android and iOS.
- [x] 5.6 `npm run cap:sync` then `cd android && ./gradlew assembleDebug` with `ANDROID_HOME=~/Android/Sdk` succeeds; record the APK path and the Gradle/AGP/JDK versions used.
- [x] 5.7 `docs/mobile.md` runbook: prerequisites, dev loop (emulator host, LAN override), Firebase setup (`google-services.json`, APNs key, `FCM_CREDENTIALS_FILE`), signing + `assetlinks.json` fingerprints + `adb shell pm verify-app-links`, iOS macOS steps, store declarations for background location.

## 6. Verification and wrap-up

- [ ] 6.1 Backend: `coverage run manage.py test game organize --noinput && coverage report --fail-under=80`, `ruff check .`.
- [ ] 6.2 Frontend: `npx vitest run`, `npm run build:all`, `npx cap sync android`, Android debug build.
- [ ] 6.3 Update `CLAUDE.md` / `.claude/guidelines.md` with the mobile commands and the platform-layer rule ("screens use the platform services, never `navigator.*` or `Capacitor` directly"); commit per milestone on `feature/mobile-app`.
