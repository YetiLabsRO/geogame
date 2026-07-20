## Context

Domination is the shipped loop: teams capture Towers by solving Challenges and hold zone majorities for time-based floating points (see `scoring`, `geographic-map`, `challenge-submission`). Trail/discovery is a **second game type on the same primitives**. Instead of contesting territory, a party (a team, or a single player) is handed a set of geofenced points and travels between them; arriving at a point and doing something there (answer, read, photograph) reveals a **clue** to the next point. The clue may fork, so the party chooses where to go; different parties may be routed differently so they spread out; or everyone runs one circuit but each party starts at a different point.

The reconciled core model (Collections → Game template → Session run) already gives us reusable Towers grouped by Collection. Trail mode adds an ordering/graph layer **on top of** those Towers, plus per-team route and progress state. It deliberately reuses:
- geofencing and the proximity check from `challenge-submission` (each step's Tower must be physically reached),
- the pluggable challenge validation from the `challenge-types` capability (a step's unlock gate is a TEXT / PHOTO / read gate),
- the per-team reveal machinery from the `tower-visibility` capability (an unrevealed trail point stays hidden on that team's map).

## Goals / Non-Goals

**Goals:**
- A distinct `TRAIL` game mode selectable on a Game, fully additive and leaving all `DOMINATION` behaviour untouched.
- Express three trail structures — `FIXED_ORDER` (linear), `GRAPH` (branching, party chooses), `CIRCUIT` (single loop, per-party start offset) — over the same TrailStep nodes.
- Three starting-knowledge settings — `ALL_KNOWN`, `ONE_KNOWN`, `NONE_KNOWN`.
- Clue-driven, geofenced, point-to-point progression with an unlock gate per step (answer / read / photo) reusing challenge-types.
- Per-team routes so competing teams walk different orderings and do not collide; per-team reveal so a party only ever sees points it has unlocked.
- Single-player (`SOLO`) or multi-team (`TEAM`) play.
- Trail-mode completion + ranking distinct from domination floating points.

**Non-Goals:**
- Redefining or modifying domination scoring, zones, or floating points (this change does not touch the `scoring` capability's requirements).
- The internal mechanics of challenge-type validation or of tower-visibility reveal — those are owned by their own capabilities; trail mode only consumes them.
- Native NFC unlock and live-location anti-collision routing — future changes (`nfc-native-and-secure-links`, `live-location-tracking`) can layer on.
- Auto-generating balanced non-colliding routes; the first cut lets a creator assign routes explicitly (an optional generator is a later enhancement).

## Decisions

- **Mode is a field on `Game`, not a subclass.** `Game.mode ∈ {DOMINATION, TRAIL}` (default `DOMINATION`), with a nullable per-`Session` override resolved by the effective-value helper. Alternative considered: a separate `TrailGame` model — rejected because Games already own Collections, Challenges, TeamGroups, roles, and the clock, all of which trail mode reuses verbatim; a mode flag keeps one template type.
- **`Trail` is 1:1 with a trail-mode Game; `TrailStep` binds to a repository `Tower`.** The step is the ordering/graph node; the Tower is the shared geometry (still geofenced, still resolved through the Game's Collections). Alternative considered: putting `order`/clue fields directly on Tower — rejected because a Tower is a reusable library asset that must not carry game-specific trail data.
- **`TrailEdge` is a directed, clue-bearing link; branches are just a step with multiple outgoing edges.** For `GRAPH`, edges are authored explicitly and each carries the clue text pointing at its target — a fork is a step with two or more outgoing edges, and the party picks one. For `FIXED_ORDER` and `CIRCUIT`, the linear successor is derived from `TrailStep.order`, so edges are optional there. This one edge model covers all three structures.
- **`CIRCUIT` = shared ordered loop + per-party start offset.** Every party runs the same cyclic order but `TeamTrailRoute.start_step` differs, and the party follows the order from its own start, wrapping around. This is the "single line everyone runs, each team starts from a different point" case.
- **Per-team routes via `TeamTrailRoute` (+ ordered through-rows).** For `FIXED_ORDER`/`CIRCUIT` a route may pin an explicit ordered sequence of steps (so team A gets 1-2-3-4 and team B gets 1-3-2-4-7); for `GRAPH` a route pins only the `start_step` and the party's path emerges from its edge choices. Alternative considered: a single global order for all teams — rejected because anti-collision (teams not bumping into each other) is an explicit product requirement.
- **Reveal is per-team and delegated to tower-visibility.** A `TrailStep`'s Tower starts hidden for a team unless the trail's starting knowledge reveals it; completing the previous step's gate reveals the next step(s) for that team only. `TeamTrailProgress` records `REVEALED → ARRIVED → UNLOCKED` per step. The visible/hidden rendering reuses the `tower-visibility` capability rather than re-implementing map masking.
- **The unlock gate is a `Challenge` and rides existing submission.** A step's `gate_challenge` is an ordinary Challenge whose type (TEXT question, PHOTO submission, or a read-only "acknowledge the clue" gate) is validated by the `challenge-types` capability, and the arrival + submission flows through the existing `POST /api/team_tower_challenges/` proximity-checked endpoint. `NONE_KNOWN` start discovery is just the first step's gate/geofence with no prior reveal.
- **Trail scoring is completion-and-time, kept separate from floating points.** A team's rank is (steps unlocked desc, finish time asc). Domination's zone/floating-point scoring is inert in trail mode. This lives inside the `mode-trail-discovery` capability, not the `scoring` capability.

## Risks / Trade-offs

- [Two scoring paths (domination vs trail) could entangle in shared viewsets/serializers] → Gate trail behaviour on `effective_mode(session) == TRAIL`; domination code paths stay behind `DOMINATION`; add tests that a domination Session exposes no trail state and a trail Session accrues no floating points.
- [A branching `GRAPH` can be authored with a dead-end or an unreachable step] → Validate a Trail on save: every non-start step reachable from a start, at least one finish reachable, no step bound to a Tower outside the Game's Collections; surface warnings in the authoring API.
- [Per-team explicit routes are fiddly to author and easy to make collide] → First cut assigns routes explicitly with a preview; document an optional auto-router as a later enhancement; add a test that two teams' assigned routes yield different step orderings.
- [`NONE_KNOWN` start could soft-lock a party that cannot find the first point] → Allow a creator-supplied out-of-band hint on the start step and a staff "reveal start" override action; covered by a scenario and test.
- [Reveal state could leak one team's discovered points to another] → All reveal/progress rows are `(session, team)`-scoped and filtered per authenticated team, mirroring per-Session ownership isolation; add a leakage test.

## Migration Plan

1. Add `Game.mode` (default `DOMINATION`) and the nullable `Session.mode` override; additive migration, no backfill needed (all existing Games become `DOMINATION` by default).
2. Add `Trail`, `TrailStep`, `TrailEdge`, `TeamTrailRoute` (+ ordered through-rows), and `TeamTrailProgress` tables; all new, no data migration.
3. Register trail viewsets/routes only; existing domination endpoints unchanged.
4. No destructive changes — the change is purely additive and opt-in via `mode = TRAIL`.
