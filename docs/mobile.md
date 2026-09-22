# Mobile app (Tower Rush)

How to build, run and release the Capacitor-wrapped player app — Android (verified from this
repo) and iOS (scaffolded, needs a Mac). Background: `openspec/changes/mobile-app/design.md`.

---

## Prerequisites

| Tool | Version used in this repo | Notes |
|---|---|---|
| Node | 24 | matches `frontend/package.json` |
| JDK | 21 | **must be a full JDK, not just a JRE** — `javac -version` has to work. Android Studio bundles one; standalone, install `openjdk-21-jdk` (Linux) or use [Eclipse Temurin 21](https://adoptium.net/temurin/releases/?version=21). Point `JAVA_HOME` at it. |
| Android SDK | platforms 35 & 36, build-tools 35.0.0 & 36.0.0, platform-tools, cmdline-tools | `sdkmanager --list` to check; `export ANDROID_HOME=/path/to/Android/Sdk` for every Gradle command |
| Xcode + CocoaPods | latest, macOS only | required to open/build `ios/` — nothing here works without a Mac |

Sanity check before anything else:

```bash
java -version && javac -version   # both must print; javac is the tell for a real JDK
node -v
echo $ANDROID_HOME && ls $ANDROID_HOME/platforms
```

---

## Dev loop

1. Run the Django backend on `:8200` (`python manage.py runserver 8200`).
2. Build the web app for native and sync:
   ```bash
   cd frontend
   npm run cap:sync:dev     # ng build player --configuration development && cap sync
   ```
3. Open the platform project and run from the IDE:
   ```bash
   npm run cap:android      # opens android/ in Android Studio
   npm run cap:ios          # opens ios/App/App.xcworkspace in Xcode (macOS only)
   ```
4. **Emulator**: the Android emulator reaches the host machine's `localhost` at
   `http://10.0.2.2:8200` — that's the default `nativeApiBaseUrl` in
   `frontend/projects/player/src/environments/environment.ts`, so a debug build talks to your
   local Django out of the box.
5. **Physical device on the same LAN**: `10.0.2.2` doesn't exist on real hardware. Two ways to
   point the app at your machine instead of rebuilding:
   - In the app: **Ledger → Settings** has a debug API origin override (`PlatformService.
     setApiBaseUrlOverride()`), persisted via `@capacitor/preferences`. Set it to
     `http://<your-LAN-ip>:8200` and it takes precedence until cleared.
   - Or edit `frontend/projects/player/src/environments/environment.ts`
     (`nativeApiBaseUrl`) and re-run `npm run cap:sync:dev`.
6. Live-reload from the Angular dev server instead of a full rebuild each time: `npx cap run
   android -l --external` (starts `ng serve` and points the WebView at your machine's dev
   server address) — optional, not scripted here.

Every native request whose URL starts with `/` gets prefixed with the effective origin by the
`apiBaseInterceptor` in `shared` (see `frontend/projects/shared/src/lib/platform/`); the web
build is untouched and keeps using the `/api/...` dev proxy.

## Release builds

```bash
cd frontend
npm run cap:sync     # ng build player --configuration production && cap sync — uses
                      # https://cercetador.albascout.ro (environment.prod.ts, via
                      # fileReplacements in angular.json)
npm run android:debug # cd android && ./gradlew assembleDebug
```

Debug APK lands at `frontend/android/app/build/outputs/apk/debug/app-debug.apk`. A signed
release build (`assembleRelease`/`bundleRelease`) needs the keystore from
[Signing](#signing--app-links-verification) below — not scripted here since the keystore
itself must never be committed.

---

## Firebase setup (push notifications)

The backend already stores `FCM`-kind push subscriptions (`organize/push.py`); without
credentials it just logs instead of sending (`LoggingPushSender`), so nothing breaks in dev.

1. Create a Firebase project (console.firebase.google.com).
2. **Android app**: add an Android app with package name `ro.yetilabs.geogame`. Download
   `google-services.json` and save it to `frontend/android/app/google-services.json` (gitignored
   — see `frontend/android/app/google-services.json.example` for the placeholder shape).
   `frontend/android/app/build.gradle` only applies the `com.google.gms.google-services` plugin
   when this file exists, so the project builds fine without it (as verified in this repo).
3. **iOS app** (macOS): add an iOS app with bundle id `ro.yetilabs.geogame`, download
   `GoogleService-Info.plist` into `ios/App/App/`, and upload an APNs authentication key
   (Certificates, Identifiers & Profiles → Keys) to Firebase → Project Settings → Cloud
   Messaging → Apple app configuration.
4. **Backend**: download a service-account JSON (Project Settings → Service accounts →
   Generate new private key), put it somewhere readable by the server process, and set:
   ```bash
   FCM_CREDENTIALS_FILE=/path/to/service-account.json
   ```
   (`GOOGLE_APPLICATION_CREDENTIALS` also works — it's the `firebase-admin` SDK's own default,
   used as a fallback when `FCM_CREDENTIALS_FILE` is unset.) Once set, `get_sender()` in
   `organize/push.py` wires up a real `FcmPushSender` for `FCM`-kind subscriptions; an
   unregistered/invalid token raises `SubscriptionGone` and the subscription is pruned, exactly
   like an expired Web Push endpoint.
5. On native, the app registers a device token through `@capacitor/push-notifications` and
   POSTs it to `/api/push/subscriptions/` as `fcm_token`; Web Push (VAPID) keeps serving the
   browser path unchanged (`WEBPUSH_VAPID_PUBLIC_KEY`/`WEBPUSH_VAPID_PRIVATE_KEY`).

---

## Signing + App Links verification (Android)

App Links (`https://cercetador.albascout.ro/nfc/*`, `/join/*`, `/invite/*` opening the app
instead of the browser) require the app's signing certificate fingerprint to be published at
`/.well-known/assetlinks.json` (served by `geogame/app_links.py` from
`settings.MOBILE_APP_LINKS`, empty by default so the endpoint exists before signing keys do).

1. Create a release keystore (once; guard it like a password — losing it means you can never
   update the app under the same listing again):
   ```bash
   keytool -genkeypair -v -keystore tower-rush-release.jks -alias tower-rush \
     -keyalg RSA -keysize 2048 -validity 10000
   ```
2. Get its SHA-256 certificate fingerprint:
   ```bash
   keytool -list -v -keystore tower-rush-release.jks -alias tower-rush
   # → copy the "SHA256:" line, format AA:BB:CC:... (keep the colons)
   ```
3. Set it on the server (comma-separated if you ever have more than one, e.g. debug + release):
   ```bash
   MOBILE_ANDROID_SHA256_FINGERPRINTS=AA:BB:CC:...
   ```
   `MOBILE_ANDROID_PACKAGE` defaults to `ro.yetilabs.geogame` and rarely needs overriding.
4. Deploy, then verify from a device/emulator with the app installed:
   ```bash
   adb shell pm verify-app-links --re-verify ro.yetilabs.geogame
   adb shell pm get-app-links ro.yetilabs.geogame   # should report "verified" for the domain
   ```
   If it doesn't verify: check `https://cercetador.albascout.ro/.well-known/assetlinks.json`
   is reachable and returns the right `package_name`/fingerprint, and that the fingerprint has
   no stray whitespace.

The custom scheme `cercetador://` (any host/path) works without any of this — it's a second,
always-available intent filter on `MainActivity`, useful as a fallback and for testing deep
links without a signed build.

---

## iOS steps (macOS only)

Nothing below has been run in this environment (no Xcode here) — the `ios/` project is
scaffolded and the manifest/entitlement pieces are pre-filled, but treat all of this as
unverified until someone builds it on a Mac.

1. `cd frontend && npx cap sync ios` (copies the web build in, regenerates
   `capacitor.config.json`).
2. `cd ios/App && pod install` — Capacitor 8 uses Swift Package Manager for its own core
   dependency (see `ios/App/CapApp-SPM/`), but several community plugins
   (`@capacitor-community/*`) still ship CocoaPods podspecs, so a Podfile/`pod install` may
   still be needed the first time `cap sync ios` runs on a Mac; follow whatever `cap sync ios`
   reports.
3. Open `ios/App/App.xcworkspace` (not `.xcodeproj`, once Pods exist) in Xcode.
4. In the target's **Signing & Capabilities** tab:
   - Add **Push Notifications**.
   - Add **Associated Domains** with `applinks:cercetador.albascout.ro` (this is what makes
     `https://cercetador.albascout.ro/nfc/*|/join/*|/invite/*` open the app instead of Safari).
   - Confirm **NFC Tag Reading** is enabled (the `com.apple.developer.nfc.readersession.
     formats = NDEF` entitlement is already in `ios/App/App/App.entitlements`, written
     ahead of time since it doesn't require the Xcode capability toggle).
   Xcode writes both of the first two into `App.entitlements` automatically once you use the
   UI — the file already exists with a comment describing exactly what should land there.
5. Add `GoogleService-Info.plist` (from Firebase, see above) to the `App` target.
6. Set `MOBILE_APPLE_APP_ID=<TEAM_ID>.ro.yetilabs.geogame` on the server (the Team ID is on
   the Apple Developer account's Membership page) — this feeds
   `/.well-known/apple-app-site-association`, which is served with an empty `details` array
   (harmless) until this is set.
7. Build/run on a simulator or device from Xcode.

### iOS BLE advertising — known limitation

`ios/App/App/BleAdvertiserPlugin.swift` is written but **unverified** (no Xcode here). It has
a real, structural limitation vs. Android, documented in the file header too:

- Android (`BleAdvertiserPlugin.java`) puts the player's token directly into the BLE
  advertisement packet as **service data** (`AdvertiseData.addServiceData`) — a scanning
  device reads the token straight off the advertisement, no connection needed.
- **iOS's `CBPeripheralManager` cannot do that.** `startAdvertising()` only accepts a service
  UUID (and optionally a local name) — there is no service-data key in the public API. So the
  iOS plugin advertises the game's service UUID only, and publishes the token as the value of
  a **readable characteristic** on a `CBMutableService` with that UUID. A scanning peer has to
  connect as a BLE central and read the characteristic to learn an iOS device's token, instead
  of reading it out of the advertisement like it does for an Android advertiser.

This asymmetry has to be handled on the scanning side (`BleProximityService`, built on
`@capacitor-community/bluetooth-le`) before iOS-to-iOS or iOS-to-Android proximity detection
works end to end — it's called out as a non-goal here and gated behind the `mode-dementors-ble`
change's iOS pilot. Android-to-Android advertising/scanning has no such limitation.

---

## Store declarations

Both stores ask for justification of sensitive permissions at review time:

- **Background location** (Play Console → App content → Sensitive permissions, and Apple's
  App Review notes): the app streams the player's location while a game session has tracking
  enabled *and* the player has given in-app consent, so their team's map position keeps
  updating while the phone is locked or the app is backgrounded. It stops immediately when
  tracking is turned off, consent is withdrawn, or the player signs out (see
  `BackgroundLocationService` / `LocationStreamService` in `shared`). Android shows the
  required persistent foreground-service notification the whole time (channel name "Tower Rush
  location", see `android/app/src/main/res/values/strings.xml`).
- **Bluetooth** (scan + advertise): used only by the opt-in "Dementors" game mode to detect
  nearby players over BLE for proximity-based gameplay; not used for tracking outside that mode.
- **NFC**: reads NDEF tags physically attached to towers in the field to let a player capture
  them; nothing is written to tags.
- **Camera / Photo Library**: optional, for attaching a photo to a challenge submission.

---

## CORS and native origins

The native shell doesn't serve the app from the backend's own origin, so cross-origin requests
need an explicit allow-list (`django-cors-headers`, configured in `geogame/settings.py`):

| Origin | Where it comes from |
|---|---|
| `https://localhost` | Capacitor's default Android WebView origin (`androidScheme: 'https'` in `capacitor.config.ts`) |
| `capacitor://localhost` | iOS WebView origin (iOS forbids `http(s)` custom schemes) |
| `http://localhost` | `cap run`/live-reload dev loop |
| anything in `CORS_EXTRA_ORIGINS` | comma-separated env var, for e.g. a LAN dev override origin |

Auth is a header token (not cookies), so `CORS_ALLOW_CREDENTIALS` stays `False` — no credentialed
CORS is needed. The Channels websocket stack has no separate origin validator, so native
websocket connections (`/ws/session/<id>/`) work unchanged once the token auth succeeds.

---

## Reference: what's committed vs. generated vs. gitignored

- Committed: `capacitor.config.ts`, `android/` and `ios/` project sources (manifest,
  `MainActivity.java`/`BleAdvertiserPlugin.java`, `Info.plist`/`App.entitlements`/
  `BleAdvertiserPlugin.swift`/`BridgeViewController.swift`, Gradle/Xcode project files),
  `resources/` (icon/splash SVGs + the render script), this doc.
- Regenerated by tooling, also committed (Capacitor's own recommendation — keep native
  projects in version control so manifest/entitlement edits are reviewable): everything `npx
  cap add android|ios` and `npx capacitor-assets generate` produce, minus what's gitignored
  below.
- Gitignored (machine- or secret-specific, see `frontend/.gitignore`):
  `android/local.properties`, `android/app/google-services.json`,
  `android/.gradle/`/`android/build/`/`android/app/build/`, iOS Pods and generated
  `capacitor.config.json`/`config.xml`, `GoogleService-Info.plist`.

## Commands quick reference

```bash
# from frontend/
npm run cap:sync           # production web build + cap sync (both platforms)
npm run cap:sync:dev       # development web build + cap sync
npm run cap:android        # open android/ in Android Studio
npm run cap:ios            # open ios/ in Xcode (macOS only)
npm run android:debug      # cd android && ./gradlew assembleDebug
npm run assets:generate    # regenerate icons/splash from resources/*.png via @capacitor/assets

# Android build verified in this repo with:
#   JDK 21 (Temurin 21.0.12.1), Gradle 8.14.3, AGP 8.13.0, ANDROID_HOME with platforms 35/36
ANDROID_HOME=/path/to/Android/Sdk npm run android:debug
```
