## Context

Base `challenge-submission` accepts an attempt from a single authenticated player who is within the Session's `proximity_meters` of the tower and derives the team from that player's membership. Nothing checks whether teammates are together, and a lone GPS fix is trivially spoofable. The product wants three related controls: (1) require the **whole team together** or explicitly **allow splitting**, (2) let a **challenge** demand a **minimum number of members present** so a split group is still a legitimate, verified presence, and (3) make presence **hard to fake**. Point (3) is where the `live-location` capability (sibling `live-location-tracking` change) matters: because players already stream consented location pings, presence can be checked against a short **window** of recent movement (trajectory + duration) rather than one instantaneous point — much harder to spoof and it averages out GPS jitter. A **photo of the required people** is kept as a fallback but flagged as weaker (AI photo editing is cheap), so it always goes to a human review rather than auto-passing.

This change owns the *rules and verification*; the *streaming and map plotting* stay in `live-location`. Presence-rules also owns the teammate-visibility config knob that `live-location` reads when deciding which other players to plot.

## Goals / Non-Goals

**Goals:**
- Per-game (with per-session override) togetherness: `WHOLE_TEAM_TOGETHER` vs `SPLIT_ALLOWED`.
- Per-challenge `min_members_present` so a split group can be required to keep ≥N people together.
- Geofence-based verification of co-presence, with a photo fallback that is staff-reviewed.
- Continuous-tracking window verification (trajectory/duration) that strengthens the check and corrects GPS error, built on the live-location ping stream.
- Configurable teammate map visibility (own-team / everyone / a select number) as the source of truth the live-location plotting consumes.
- Fully backward compatible: unconfigured games behave exactly as today.

**Non-Goals:**
- The location streaming transport, ping frequency, consent, and after-game replay — owned by `live-location` (sibling `live-location-tracking` change).
- Team head-count / readiness thresholds to *start* a Session — owned by `game-config-team-rules`.
- Tower locking, challenge types, and role-gated challenges — owned by their own changes; presence composes with them but does not define them.
- Anti-cheat beyond geofence + window + photo review (no device attestation, no accelerometer proof-of-walking).

## Decisions

- **Togetherness and visibility are Game config with nullable Session overrides**, resolved through the existing `Session.effective(field)` helper and registered in `OVERRIDABLE_CONFIG_FIELDS`, matching `proximity_meters` and the pause/failure knobs. Alternative considered: a standalone presence-config table — rejected because it fragments a pattern the codebase already applies to every gameplay knob.
- **A reusable `PresenceRequirement` model referenced by a nullable `Challenge.presence_requirement` FK**, rather than inlining fields on `Challenge`. Rationale: the same requirement ("≥2 people, geofence, 30s window") recurs across many challenges in a bank and reads better as a named, reusable row; `NULL` cleanly means "no requirement" so the default is zero behaviour change. Alternative considered: inline nullable fields on `Challenge` — rejected because it bloats the challenge row and can't be shared or named.
- **Effective requirement is resolved, not stored.** At submission the effective minimum = full active team size when the Session's effective `togetherness_mode == WHOLE_TEAM_TOGETHER`, else the requirement's `min_members_present` (default `1`). The geofence radius = requirement's `geofence_radius_meters` or the tower's effective `proximity_meters`. The window = requirement's `window_seconds` or the Session's effective `presence_window_seconds`. Keeping this a pure function of config means changing a knob mid-run takes effect immediately and needs no backfill.
- **Co-presence is evaluated from live-location pings**, not from each member re-submitting. A member counts as present when their most recent ping is fresh (within a staleness bound) and lies inside the geofence. With a window > 0, *all* of that member's pings across the window must lie inside the geofence (trajectory/duration), which is what makes spoofing expensive and simultaneously smooths a single bad fix. The submitter is always counted as one present member from their submission GPS even if their ping is momentarily stale.
- **Photo fallback never auto-passes.** `method = PHOTO` (or `GEOFENCE_OR_PHOTO` when geofence data is unavailable/insufficient) accepts a photo of the required people, marks the submission `PENDING`, and requires staff to confirm the people are present. The spec explicitly records that photo evidence is weaker than geofence + window because it is easily AI-edited. Alternative considered: automatic photo headcount via vision model — rejected as unreliable and out of scope.
- **Presence evidence is persisted** as a `PresenceCheck` row linked to the `TeamTowerChallenge`: the resolved requirement, which member ids were verified, the method used, and whether the window was satisfied. This gives staff review something concrete and makes after-the-fact disputes auditable.
- **Teammate visibility config lives here; plotting lives in `live-location`.** Presence-rules defines `OWN_TEAM` / `EVERYONE` / `SELECT_COUNT(count)`; the live-location plotting reads it to decide whose markers to send a given player. This avoids two capabilities both claiming to define "who can see whom."

## Risks / Trade-offs

- [A required teammate's phone has stale/absent location, blocking a legitimate attempt] → freshness is a bounded staleness window, not "instantaneous"; where the method allows, a photo fallback unblocks the group under staff review; blockers name exactly which member/condition failed so players can react.
- [Continuous-tracking windows depend on live-location being enabled] → when live-location is unavailable or a window is configured with no ping data, the system degrades to the point-in-time geofence check (or the photo fallback) rather than hard-failing, and the `PresenceCheck` records that the window could not be evaluated.
- [Photo fallback is spoofable via AI editing] → it is intentionally the weakest tier, always staff-reviewed, never auto-confirming; the spec states this so operators choose it knowingly.
- [`WHOLE_TEAM_TOGETHER` on a large team makes any submission fragile] → it is opt-in per game/session; operators who want resilience use `SPLIT_ALLOWED` with a modest `min_members_present`; windows can be short (seconds) to bound the co-location requirement.
- [Cross-capability coupling with an in-flight `live-location` spec] → presence-rules only *references* live-location in prose (does not redefine it); co-presence reads are expressed against "the live-location ping stream" so the contract survives that change landing independently.

## Migration Plan

1. Add the four config fields to `organize.Game` (with today's-behaviour defaults) and the four nullable overrides to `organize.Session`; register the names in `OVERRIDABLE_CONFIG_FIELDS`.
2. Add `game.PresenceRequirement`, the nullable `Challenge.presence_requirement` FK, and `game.PresenceCheck`; run one schema migration. No data migration — all existing challenges have `presence_requirement = NULL` (no requirement) and all games default to `SPLIT_ALLOWED` / `OWN_TEAM` / window `0`.
3. Insert the presence evaluation step into the submission flow behind the effective-requirement resolver; when the resolved requirement is the null/default one, the step is a no-op and the flow is byte-for-byte the base behaviour.
4. Wire the teammate-visibility config into the live-location plotting read (delivered with the sibling change); until live-location ships, the config is stored and validated but only consumed once plotting exists.
