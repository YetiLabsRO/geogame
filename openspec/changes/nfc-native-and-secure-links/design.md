## Context

The shipped `rfid-capture` capability lets a player capture an RFID-category tower by opening a public URL, `/tower/rfid/<rfid_code>/`, that resolves the code and (after a proximity check) auto-confirms the capture. It is a plain HTTPS link. That makes it trivially *forwardable*: a player can copy it out of the address bar into a group chat, and a teammate — or an opponent who intercepts the message — can hit it from anywhere. Proximity is the only guard, and GPS can be spoofed. The product goal is the opposite: a tag hidden inside a tree, behind wall plaster, or on a branded sticker somewhere in a park, where the interaction the game rewards is *walking there and physically tapping it*.

This change adds two things. First, **native NFC scanning** in the mobile player app so tapping a phone to a hidden tag is the primary interaction. Second, a **secure-link scheme** where a scanned tag is only actionable *inside* the authenticated app — scanning is the single purpose of the tag, and its contents cannot be copy-pasted into a browser or forwarded to be actioned elsewhere. It deliberately builds *on top of* the RFID mechanic rather than replacing it: RFID URL capture stays as a "legacy convenience" mode, and NFC/secure tokens are the hardened mode a game opts into.

## Goals / Non-Goals

**Goals:**
- Native NFC scan in the mobile player app, with graceful fallback where NFC is unavailable.
- A tag payload that is **only actionable inside the app**: single-purpose, non-forwardable, app-verified.
- Backward compatibility: existing RFID URL tags keep working; the new behavior is opt-in per Game with per-Session override, defaulting to today's behavior.
- Provisioning at scale: staff can mint many tags, bind them to towers, and export the writable NDEF payload plus a printable QR fallback for stickers.
- An explicit, documented threat model that scopes what "secure" means here.

**Non-Goals:**
- Cryptographic unforgeability of a tag. We accept a tag can be read and dumped (see Threat model).
- Replacing RFID capture. RFID stays as the legacy mode of the same tag family.
- BLE proximity, live location, or continuous-presence verification — those are the `mode-dementors-ble`, `live-location-tracking`, and `presence-rules` changes.
- Defining the `NFC_QR` challenge *type* itself; that is introduced by the sibling `challenge-type-system` change. This change provides the *capture channel* that type uses and references it in prose.

## Decisions

- **A tag carries an opaque `token`, not a meaningful URL.** In `SECURE_TOKEN` mode the actionable payload is a random URL-safe token that means nothing on its own; the capture only happens when the authenticated app POSTs the token to `/api/nfc/capture/` with live GPS. Alternative considered: a signed JWT on the tag that a browser could verify — rejected because a self-verifying link is still a forwardable link, which is exactly the failure mode we are removing.
- **The web layer refuses to capture from a plain browser.** `GET /nfc/<token>/` is an app-link (Android App Link / iOS Universal Link). Opened by the app it deep-links into the scan flow; opened by any other browser it returns an "open this in the app" page and performs no capture. This is the enforcement point that makes a forwarded link inert. Alternative considered: a pure custom scheme (`cercetador://…`) with no web fallback — rejected because it gives users without the app a dead tap and no guidance.
- **NDEF, dual-record.** Tags are written as NDEF. Secure tags carry an app-triggering record (custom URI + an Android Application Record) plus the token; legacy tags carry the existing `/tower/rfid/<code>/` URL. Staff fetch the exact bytes to write and a QR image encoding the same app-link, so cheap NTAG stickers and printed QR both work.
- **Native scan with layered fallback.** The player SPA uses the Web NFC `NDEFReader` API where the platform supports it (Android Chrome); a native-shell bridge (Capacitor / Web NFC polyfill) when the app is wrapped natively (the path for iOS, where in-browser Web NFC does not exist); and a **QR-scan or manual code entry** fallback otherwise. The same token flows through all three, so the backend is transport-agnostic.
- **Reuse the config pattern.** `nfc_secure_mode`, `nfc_require_app`, and `nfc_replay_hardening` are Game defaults with nullable Session overrides resolved by an effective-value helper (Session override wins, else Game default), matching `proximity_meters` and the pause/failure knobs. Defaults keep legacy behavior so nothing changes for existing games until a creator opts in.
- **Capture mirrors RFID, then diverges only where needed.** A confirmed secure scan closes and reassigns tower ownership exactly like an RFID capture and reuses `proximity_meters`. Where a tag targets a partner/venue `NFC_QR` challenge instead of a tower, the scan feeds the challenge-submission/review flow (see the `challenge-types` capability, introduced by the sibling `challenge-type-system` change).
- **Optional replay hardening, off by default.** For adversarial games, a tag MAY use a monotonic tap counter (e.g. NTAG 424 DNA-style rolling messages) recorded per scan; a repeated or lower counter is rejected as a replay. This is opt-in via `nfc_replay_hardening`; cooperative games leave it off to keep cheap static NTAG stickers viable.

## Threat model

We state the accepted risk plainly so nobody over-trusts the mechanism.

- **What we defend against:** casual forwarding and copy-paste. A player cannot lift a link out of the app and drop it in a chat for a teammate who never went to the tag; a plain browser hitting the link does nothing; the token is single-purpose (only the capture endpoint consumes it) and requires the app plus live proximity.
- **What we explicitly do NOT defend against:** a motivated attacker with an NFC reader can tap a hidden tag, dump its NDEF, extract the token, and attempt to replay or clone it. GPS can be spoofed, so proximity is a deterrent, not a proof. The tag's contents are considered **extractable and forgeable**. We rely on **app-gating + proximity + audit**, not tag secrecy, for integrity.
- **Why that is acceptable:** most games are cooperative or low-stakes; the cost of physically finding and reading a tag hidden in a tree usually exceeds the reward of cheating, and the `TagScan` audit trail lets a runner spot anomalies after the fact. Games that genuinely need more can enable `nfc_replay_hardening` (rolling counters) and `nfc_require_app`, accepting more expensive tag hardware. Cryptographic unforgeability is a non-goal.

## Risks / Trade-offs

- [iOS browsers have no Web NFC, so in-browser scanning is impossible there] → ship the native-shell bridge for the wrapped app and always provide the QR-scan / manual-entry fallback so no platform is stranded.
- [A forwarded token could still be POSTed directly to `/api/nfc/capture/` by a scripted client, bypassing the "open in app" page] → the endpoint independently enforces auth, Session membership, proximity, freshness, and (when enabled) the replay counter; the browser page is a UX guard, not the security boundary, and the audit log flags suspicious captures.
- [Static NTAG stickers can be cloned] → accepted per the threat model; adversarial games opt into `nfc_replay_hardening` with counter-bearing tags. Documented, not silently assumed away.
- [Two tag modes plus three scan transports risk fragmenting the code] → the backend consumes one opaque token regardless of mode or transport; only provisioning (what to write) and the client scan source differ, keeping a single capture code path.
- [Existing RFID behavior could regress] → `nfc_secure_mode` defaults off; the `/tower/rfid/<code>/` route and its proximity check are unchanged; a regression test asserts a legacy RFID capture still confirms exactly as before.

## Migration Plan

1. Additive migration: create `game.NfcTag` and `game.TagScan`; add nullable `nfc_secure_mode`, `nfc_require_app`, `nfc_replay_hardening` to `organize.Game` and matching nullable overrides to `organize.Session`. No backfill needed — absent values resolve to legacy behavior.
2. For each existing RFID-category tower, optionally create a `NfcTag(mode=LEGACY_URL)` mirroring its current `rfid_code` URL so the provisioning UI and audit cover legacy tags uniformly; this is optional and does not change runtime capture (the `/tower/rfid/<code>/` route still works directly).
3. Ship the capture endpoint and app-link landing behind the default-off `nfc_secure_mode`; creators opt individual Games into secure mode when ready.
4. Add the player-app scan flow and staff provisioning UI; verify Web NFC, native bridge, and QR fallback all resolve to the same token capture.
