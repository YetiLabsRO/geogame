## Context

The shipped map exposes every active tower and every zone to everyone, and the player app draws them all colored by current control. The two-axis visibility model from the product notes composes two independent questions: **is the tower on the map?** (discoverability) and **is its challenge legible?** (challenge visibility). Because these are orthogonal, a tower can be `HIDDEN` yet `VISIBLE_ANYWHERE` (you cannot see the tower until you find it, but once found its challenge reads from afar) or `VISIBLE` yet `HIDDEN_UNTIL_ARRIVAL` (you see the objective but must walk up to learn the task). Discovery is inherently **per team and per run**, so it lives on a Session-scoped record, not on the shared repository geometry. This change sits on the `points-repository-and-collections` foundation (Towers/Zones are library assets reachable through a Game's Collections) and reuses the standard Game-default + nullable-Session-override config pattern.

## Goals / Non-Goals

**Goals:**
- A clean two-axis model: tower discoverability (`HIDDEN` / `VISIBLE` / `FOG_REVEAL`) × challenge visibility (`HIDDEN_UNTIL_ARRIVAL` / `VISIBLE_ANYWHERE`), configurable per tower with a game-wide default.
- Per-team discovery that persists: a team keeps seeing a tower it discovered even after it is conquered by another team or becomes ownerless.
- Fog-of-war reveal by zone entry **or** by covering more than a per-zone-configurable percentage of the zone.
- A per-game switch for whether the public map reveals other teams' ownership.
- Fully backward-compatible defaults: existing games stay fully visible, no fog, all ownership shown.

**Non-Goals:**
- The continuous location stream itself (consent, frequency, teammate plotting, replay storage) — owned by the `live-location` capability; this change only *consumes* positions to drive discovery and defines a fallback ping.
- Live push of discovery events over websockets — owned by `realtime-and-notifications`; here discovery is delivered via the ping response and polling.
- Locking, scoring multipliers, roles, or challenge typing — separate changes.
- Hiding *zone geometry* for `HIDDEN`/`VISIBLE` towers: a `HIDDEN` tower's zone may still be drawn; only `FOG_REVEAL` fogs the zone itself.

## Decisions

- **Two independent enum fields, not one combined mode.** `Tower.discoverability` and `Tower.challenge_visibility` are separate nullable fields resolving to game-wide defaults. Alternative considered: a single "visibility profile" enum enumerating the 6 combinations — rejected because it hides the orthogonality, bloats the enum, and makes the game-wide default awkward.
- **Per-tower value with a game-wide default, stored on the Tower.** Fields are nullable; a null resolves to the Game's default via an effective-value helper (`Tower.effective_discoverability(game)`, `Tower.effective_challenge_visibility(game)`), mirroring `proximity_meters`. Alternative considered: storing the override on the `Collection`↔`Tower` through-row so a shared tower can differ per game — deferred; the notes say "configurable per tower with a game-wide default", and a repository tower's default visibility is a reasonable property of the tower. The nullable field leaves room for a future per-membership override without a rewrite.
- **Discovery is a Session-scoped `TowerDiscovery` row, append-only.** One row per `(session, team, tower)` created the first time the team reveals the tower; it is never deleted by conquest or loss of ownership. "A team sees a tower" ⇔ the tower is `VISIBLE` **or** a `TowerDiscovery` row exists for that team — decoupling *visibility* from *ownership* entirely. Alternative considered: deriving visibility from ownership history — rejected because a team that merely walked past (never owned) a tower must still keep seeing it, and a team that lost a tower must not lose sight of it.
- **`FOG_REVEAL` has two reveal triggers: zone entry OR coverage threshold.** A member's position falling inside the tower's zone reveals the zone's `FOG_REVEAL` towers immediately; independently, once the team's accumulated coverage of that zone exceeds `Zone.fog_reveal_coverage_pct`, its `FOG_REVEAL` towers reveal even if no one stepped on the exact spot. Coverage = area of the union of buffered visited positions ∩ zone, ÷ zone area.
- **`HIDDEN` reveals by proximity only.** A `HIDDEN` tower reveals when a team member's reported position is within the tower's effective `proximity_meters` (its activation area) — the same radius used for submission. This is the "walk until it pops up" behavior.
- **Ownership visibility is a separate per-game knob.** `reveal_other_teams_ownership` (default `True`) gates whether a returned tower/zone carries *other* teams' control colouring. A team always sees its own control. This composes with discovery: you might see a tower (because you discovered it) but not who currently holds it.
- **Filtering happens server-side.** The towers/zones endpoints resolve the caller's team from the authenticated membership and return only visible geometry, so an undiscovered tower never reaches the client. Staff/omniscient callers (no team, or staff overview) bypass the filter and see everything.
- **Backward-compatible defaults via data migration.** New Game defaults backfill to `VISIBLE` / `VISIBLE_ANYWHERE` / `reveal_other_teams_ownership=True`; per-tower and per-zone override fields default null. With no `HIDDEN`/`FOG_REVEAL` towers, no discovery is ever required and every tower is `VISIBLE`, so migrated games render identically.

## Risks / Trade-offs

- [Coverage computation over raw GPS pings is expensive and noisy] → Compute coverage incrementally (accumulate a buffered visited geometry per `(session, team, zone)`), cap resolution, and short-circuit once the threshold is crossed; the zone-entry trigger means coverage is only needed for teams that skirt a zone without entering it.
- [Discovery depends on a position stream this change does not own] → Consume `live-location` positions when present; provide `POST /api/discovery/ping/` as a self-contained fallback so discovery works even before `live-location` ships. Both funnel through one `evaluate_discovery(session, team, point)` routine.
- [A leaked towers endpoint could reveal hidden towers] → Visibility is enforced in the queryset, not the serializer; tests assert an undiscovered `HIDDEN`/`FOG_REVEAL` tower is absent from the payload, not merely unstyled.
- [Per-tower visibility on a shared repository tower could surprise a second game reusing it] → It resolves to that game's default when null; only an explicit per-tower override is shared, and the staff UI shows which Games reference a tower before editing (see the `collections` capability). A per-membership override remains a clean future extension.
- [Turning a running game's towers HIDDEN mid-session could strand teams] → Discovery is append-only, so already-revealed towers stay revealed; only not-yet-discovered teams are affected.

## Migration Plan

1. Add `TowerDiscovery`; add nullable `Tower.discoverability`, `Tower.challenge_visibility`, `Zone.fog_reveal_coverage_pct`; add `Game` defaults `tower_discoverability_default`, `challenge_visibility_default`, `fog_reveal_coverage_pct_default`, `reveal_other_teams_ownership` with nullable per-Session overrides. Migrate schema.
2. Data migration: set every existing Game's `tower_discoverability_default=VISIBLE`, `challenge_visibility_default=VISIBLE_ANYWHERE`, `reveal_other_teams_ownership=True`, `fog_reveal_coverage_pct_default=60` (inert until a tower opts into fog). Leave per-tower/per-zone overrides null.
3. Add effective-value resolvers and route the towers/zones querysets through the visibility filter; keep results identical for all-`VISIBLE` games (regression test).
4. Add the discovery ping + evaluation routine and the discovered-towers query API.
5. Wire the player app map/tower-detail and staff config surfaces to the new knobs.
