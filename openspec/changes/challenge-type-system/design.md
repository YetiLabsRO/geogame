## Context

A `game.Challenge` today has `text`, `difficulty`, a nullable `tower` (null = generic), and a `game` FK. Capture works one of two disjoint ways: a text challenge (`challenge-submission` capability) creates a `TeamTowerChallenge` with outcome `PENDING`, staff read it and confirm/reject, and confirmation runs `tower.assign_to_team(team)`; or an RFID tower (`rfid-capture` capability, `Tower.category == RFID`) is captured by scanning its `rfid_code`, which auto-confirms without a challenge. The next-challenge roster (`challenges` capability) walks tower-specific challenges in ascending difficulty, then generic challenges in ascending difficulty, then replays the hardest generic forever, keyed on the team's highest confirmed difficulty at that tower.

The product wants a challenge to be "anything" — most valuably a **partner-venue validation** (a tower at a bar: the team buys the specified drink, the bartender hands them a QR code or NFC tag, the team scans it in the app and captures the tower). Rather than bolt on a third disjoint capture path, this change makes the *kind* of challenge a first-class, pluggable dimension and pulls RFID into the same model, so all capture paths share one submission pipeline, one roster, and one review surface.

## Goals / Non-Goals

**Goals:**
- A `Challenge` declares a `type` that determines what a submission must supply and how it is reviewed (auto vs manual).
- Ship four types: `TEXT` (current), `PHOTO`, `NFC_QR` (venue/partner code scan), `RFID` (formalize the existing tag capture).
- Make types pluggable via a handler registry, so a fifth type is a new handler class, not a new pipeline.
- Preserve the difficulty roster, generic fallback pool, tower-specific-vs-generic distinction, proximity check, and rejection cooldown, all type-agnostic.
- Zero behavior change for existing text challenges and existing RFID towers.

**Non-Goals:**
- Native in-app NFC scanning and non-forwardable secure links — owned by the separate `nfc-native-and-secure-links` change; this change accepts a scanned code as a string payload and validates it server-side.
- Tower locking / free-for-all award semantics (`tower-locking` change) and role-gated challenges (`team-roles-as-mechanics` change).
- Payment integration with the venue POS — the "team paid for the drink" step is proven by the venue handing out the code, not by a payment API.
- New scoring math — capture still runs the existing `tower.assign_to_team(team)` path.

## Decisions

- **`Challenge.type` is a string enum** (`TEXT`, `PHOTO`, `NFC_QR`, `RFID`), default `TEXT`. Alternative considered: an integer enum mirroring `Tower.category` — rejected because string values keep the API and admin readable and the type list is short and stable.
- **Validation + review flow live in a `ChallengeTypeHandler` registry**, one handler per type, each exposing `review_mode` (`AUTO`/`MANUAL`), the submission payload it requires, and a `validate(submission)` that returns confirmed/rejected/pending. The submission viewset resolves `handler = registry[challenge.type]` and dispatches. Alternative considered: `if type == ...` branches in the viewset — rejected because it re-scatters the exact logic this change is meant to consolidate and makes new types invasive.
- **Auto vs manual is a property of the type, with an optional per-challenge override.** `NFC_QR` and `RFID` handlers are `AUTO`: a submission carrying a `submitted_code` that matches the challenge's `validation_code` (or, for RFID, the tower's `rfid_code`) *and* passing the proximity check is set to `CONFIRMED` immediately and captures the tower; a mismatch is `REJECTED` immediately. `TEXT` and `PHOTO` handlers are `MANUAL`: the submission is `PENDING` and enters the existing staff review surface unchanged. A nullable `Challenge.review_mode` may override the handler default (e.g. force a suspicious NFC_QR to manual review) without changing the type.
- **NFC_QR carries a `validation_code` and `type_config`.** `validation_code` is the code embedded in the QR/NFC the venue hands out; `type_config` (JSON) holds per-type extras such as the partner/venue label and a `single_use` flag. Default `single_use=false` (a code validates the tower for the team that scans it; the venue can hand the same code to every team). When `single_use=true`, a code is consumed on first successful use. Alternative considered: discrete columns per extra — rejected because type-specific config differs per type and a JSON blob keeps the schema stable as types grow.
- **RFID is formalized without breaking the existing route.** The `/tower/rfid/<rfid_code>/` route and printable admin URL stay; internally the route now builds an `RFID`-type submission dispatched through the same auto-validated handler as `NFC_QR`, with the tower's `rfid_code` as the expected code. `TeamTowerChallenge.challenge` remains nullable so an RFID capture needs no `Challenge` row, exactly as today. `Tower.category == RFID` is retained as the trigger for the RFID handler; the two representations stay consistent.
- **The roster is type-agnostic.** Next-challenge selection (`challenges` capability) is unchanged: it orders by `difficulty` and tower-specific-then-generic and ignores `type`. A tower may mix types across difficulties (e.g. a `PHOTO` at difficulty 1, a `TEXT` at difficulty 2). The client reads each returned challenge's `type` and renders the matching submission UI.
- **`submitted_code` on `TeamTowerChallenge`** carries the scanned code for scan-type submissions; it is null for `TEXT`/`PHOTO`. The existing `photo` field carries `PHOTO` evidence.

## Risks / Trade-offs

- [A scannable code is copyable — a team could forward the QR/NFC code to a team not at the venue] → keep the proximity check mandatory for auto types, support `single_use` codes, and allow `review_mode` override to manual; the deeper non-forwardable-link protection is the separate `nfc-native-and-secure-links` change, referenced here.
- [Auto-confirm removes staff from the loop, so a bad code check silently mis-captures] → the handler's `validate` is the single choke point, covered by tests for match/mismatch/proximity-fail/single-use-consumed; auto outcomes are still recorded as `TeamTowerChallenge` rows with `submitted_code` for audit.
- [Adding `type` could leak into the roster and change selection order for existing games] → selection stays keyed only on `difficulty`/tower-specific/generic; a regression test asserts an all-`TEXT` game returns the identical sequence it did before.
- [Two RFID representations (tower category + RFID handler) could drift] → the RFID handler derives its expected code from `tower.rfid_code`; a test asserts the `/tower/rfid/<code>/` route and a manually built `RFID` submission reach the same auto-confirm outcome.

## Migration Plan

1. Add `Challenge.type` (default `TEXT`), `Challenge.validation_code` (nullable), `Challenge.type_config` (JSON, default empty), `Challenge.review_mode` (nullable), and `TeamTowerChallenge.submitted_code` (nullable). Migrate schema.
2. Data migration: stamp every existing `Challenge` with `type=TEXT` (the default already does this; the migration makes it explicit and safe for pre-existing rows).
3. Register the four handlers (`TEXT`, `PHOTO`, `NFC_QR`, `RFID`) in the registry; route the submission viewset and the RFID route through the registry.
4. No backfill needed for RFID towers — they keep working through the RFID handler using `tower.rfid_code`; optionally seed an `RFID`-type generic challenge per RFID tower for authoring visibility (not required for capture).
5. Extend serializers to emit `type` and expected payload; extend the player and staff SPAs with per-type UI. Every new field defaults preserve current behavior, so the change is deployable before the frontend catches up.
