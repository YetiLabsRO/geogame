## 1. Game mode switch

- [ ] 1.1 Add `Game.mode` (`DOMINATION` default / `TRAIL`) and a nullable `Session.mode` override; add an `effective_mode(session)` helper following the effective-value config pattern (Session override wins, else Game default).
- [ ] 1.2 Gate runtime behaviour on `effective_mode`: a `TRAIL` Session runs the trail loop and does not accrue zone/floating-point scoring; a `DOMINATION` Session exposes no trail state. Additive migration; admin + serializers expose `mode`.

## 2. Trail structure model

- [ ] 2.1 Add `game.Trail` (1:1 to a trail-mode `Game`; fields `structure` = FIXED_ORDER/GRAPH/CIRCUIT, `starting_knowledge` = ALL_KNOWN/ONE_KNOWN/NONE_KNOWN, `participation` = TEAM/SOLO) with migration + admin.
- [ ] 2.2 Add `game.TrailStep` (`trail` FK, `tower` FK into the Game's Collections, `order` int, `is_start`, `is_finish`, `gate_challenge` nullable FK, `clue_text`, optional `start_hint`).
- [ ] 2.3 Add `game.TrailEdge` (`trail` FK, `from_step`, `to_step`, `clue`) for GRAPH branches; derive linear successors from `order` for FIXED_ORDER/CIRCUIT.
- [ ] 2.4 Add a Trail validator (run on save/publish): every non-start step reachable from a start, ≥1 finish reachable, no dead-ends, every step's Tower inside the Game's Collections.

## 3. Per-team routes & participation

- [ ] 3.1 Add `game.TeamTrailRoute` (`session`, `team`, `start_step`) plus ordered through-rows for a team's explicit step sequence (FIXED_ORDER/CIRCUIT).
- [ ] 3.2 Implement CIRCUIT start-offset resolution: all teams share the cyclic order, each follows it from its own `start_step`, wrapping around.
- [ ] 3.3 Support SOLO participation: bind routes/progress to a single player where `participation = SOLO`, else to the team.

## 4. Progression, clues & reveal

- [ ] 4.1 Add `game.TeamTrailProgress` (`session`, `team`, `step`, `state` REVEALED/ARRIVED/UNLOCKED, `revealed_at`, `arrived_at`, `unlocked_at`), all `(session, team)`-scoped.
- [ ] 4.2 Seed initial reveal from `starting_knowledge` (ALL_KNOWN reveals every step; ONE_KNOWN reveals only the start; NONE_KNOWN reveals nothing until the start is discovered).
- [ ] 4.3 On geofenced arrival at a step's Tower (reuse the `challenge-submission` proximity check), mark ARRIVED; on completing the step's `gate_challenge` (validated via the `challenge-types` flow), mark UNLOCKED and reveal the next step(s) + clue(s) to that team only.
- [ ] 4.4 Delegate per-team map masking of unrevealed trail points to the `tower-visibility` capability so a party sees only points it has unlocked.
- [ ] 4.5 Add a staff "reveal start" override for a stuck `NONE_KNOWN` party.

## 5. Completion & ranking

- [ ] 5.1 Mark a team finished when it reaches its finish step (or has visited all required steps); record finish time.
- [ ] 5.2 Rank teams by (steps unlocked desc, finish time asc); expose a trail leaderboard for the Session.

## 6. APIs

- [ ] 6.1 Staff/creator authoring: `/api/staff/trails/`, `/api/staff/trail-steps/`, `/api/staff/trail-edges/`, and per-session `/api/staff/sessions/{id}/trail-routes/`.
- [ ] 6.2 Player: `GET /api/trail/state/` (current position, revealed steps, active clue, progress) and `GET /api/trail/next/` (branch options at the current step); arrival + gate unlock ride the existing `POST /api/team_tower_challenges/`.

## 7. Frontend

- [ ] 7.1 Player SPA trail view: current point, active clue, branch chooser, progress, finish state.
- [ ] 7.2 Staff SPA trail authoring editor: place steps on the map, draw edges/clues, choose structure + starting knowledge, assign per-team routes; trail leaderboard.

## 8. Tests

- [ ] 8.1 Mode isolation: a `DOMINATION` Session exposes no trail state and a `TRAIL` Session accrues no floating points.
- [ ] 8.2 Structures: FIXED_ORDER advances 1→2→3→4; GRAPH offers a branch and honours the party's choice; CIRCUIT starts two teams at different points and each follows the order from its own start.
- [ ] 8.3 Starting knowledge: ALL_KNOWN / ONE_KNOWN / NONE_KNOWN each seed the correct initial reveal.
- [ ] 8.4 Gate + geofence: a distant arrival is rejected; a completed gate reveals the next step's clue; a read-only gate auto-advances on arrival.
- [ ] 8.5 Per-team routes: two teams get different step orderings; reveal/progress never leaks across teams.
- [ ] 8.6 Completion: finishing marks the team done and ranks it by steps-then-time; Trail validator rejects a dead-end or an out-of-Collection Tower.
