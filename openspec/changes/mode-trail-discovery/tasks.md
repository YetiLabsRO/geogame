## 1. Game mode switch

- [x] 1.1 Add `Game.mode` (`DOMINATION` default / `TRAIL`) and a nullable `Session.mode` override; add an `effective_mode(session)` helper following the effective-value config pattern (Session override wins, else Game default).
- [x] 1.2 Gate runtime behaviour on `effective_mode`: a `TRAIL` Session runs the trail loop and does not accrue zone/floating-point scoring; a `DOMINATION` Session exposes no trail state. Additive migration; admin + serializers expose `mode`.

## 2. Trail structure model

- [x] 2.1 Add `game.Trail` (1:1 to a trail-mode `Game`; fields `structure` = FIXED_ORDER/GRAPH/CIRCUIT, `starting_knowledge` = ALL_KNOWN/ONE_KNOWN/NONE_KNOWN, `participation` = TEAM/SOLO) with migration + admin.
- [x] 2.2 Add `game.TrailStep` (`trail` FK, `tower` FK into the Game's Collections, `order` int, `is_start`, `is_finish`, `gate_challenge` nullable FK, `clue_text`, optional `start_hint`).
- [x] 2.3 Add `game.TrailEdge` (`trail` FK, `from_step`, `to_step`, `clue`) for GRAPH branches; derive linear successors from `order` for FIXED_ORDER/CIRCUIT.
- [x] 2.4 Add a Trail validator (run on save/publish): every non-start step reachable from a start, ≥1 finish reachable, no dead-ends, every step's Tower inside the Game's Collections.

## 3. Per-team routes & participation

- [x] 3.1 Add `game.TeamTrailRoute` (`session`, `team`, `start_step`) plus ordered through-rows for a team's explicit step sequence (FIXED_ORDER/CIRCUIT).
- [x] 3.2 Implement CIRCUIT start-offset resolution: all teams share the cyclic order, each follows it from its own `start_step`, wrapping around.
- [x] 3.3 Support SOLO participation: bind routes/progress to a single player where `participation = SOLO`, else to the team.

## 4. Progression, clues & reveal

- [x] 4.1 Add `game.TeamTrailProgress` (`session`, `team`, `step`, `state` REVEALED/ARRIVED/UNLOCKED, `revealed_at`, `arrived_at`, `unlocked_at`), all `(session, team)`-scoped.
- [x] 4.2 Seed initial reveal from `starting_knowledge` (ALL_KNOWN reveals every step; ONE_KNOWN reveals only the start; NONE_KNOWN reveals nothing until the start is discovered).
- [x] 4.3 On geofenced arrival at a step's Tower (reuse the `challenge-submission` proximity check), mark ARRIVED; on completing the step's `gate_challenge` (validated via the `challenge-types` flow), mark UNLOCKED and reveal the next step(s) + clue(s) to that team only.
- [x] 4.4 Delegate per-team map masking of unrevealed trail points to the `tower-visibility` capability so a party sees only points it has unlocked.
- [x] 4.5 Add a staff "reveal start" override for a stuck `NONE_KNOWN` party.

## 5. Completion & ranking

- [x] 5.1 Mark a team finished when it reaches its finish step (or has visited all required steps); record finish time.
- [x] 5.2 Rank teams by (steps unlocked desc, finish time asc); expose a trail leaderboard for the Session.

## 6. APIs

- [x] 6.1 Staff/creator authoring: `/api/staff/trails/`, `/api/staff/trail-steps/`, `/api/staff/trail-edges/`, and per-session `/api/staff/sessions/{id}/trail-routes/`.
- [x] 6.2 Player: `GET /api/trail/state/` (current position, revealed steps, active clue, progress) and `GET /api/trail/next/` (branch options at the current step); arrival + gate unlock ride the existing `POST /api/team_tower_challenges/`.

## 7. Frontend

- [x] 7.1 Player SPA trail view: current point, active clue, branch chooser, progress, finish state.
- [x] 7.2 Staff SPA trail authoring editor: place steps on the map, draw edges/clues, choose structure + starting knowledge, assign per-team routes; trail leaderboard.

## 8. Tests

- [x] 8.1 Mode isolation: a `DOMINATION` Session exposes no trail state and a `TRAIL` Session accrues no floating points.
- [x] 8.2 Structures: FIXED_ORDER advances 1→2→3→4; GRAPH offers a branch and honours the party's choice; CIRCUIT starts two teams at different points and each follows the order from its own start.
- [x] 8.3 Starting knowledge: ALL_KNOWN / ONE_KNOWN / NONE_KNOWN each seed the correct initial reveal.
- [x] 8.4 Gate + geofence: a distant arrival is rejected; a completed gate reveals the next step's clue; a read-only gate auto-advances on arrival.
- [x] 8.5 Per-team routes: two teams get different step orderings; reveal/progress never leaks across teams.
- [x] 8.6 Completion: finishing marks the team done and ranks it by steps-then-time; Trail validator rejects a dead-end or an out-of-Collection Tower.

## Implementation notes

**Where things live**
- `organize/models.py` — `MODE_DOMINATION`/`MODE_TRAIL` constants, `Game.mode`,
  nullable `Session.mode`, `'mode'` added to `OVERRIDABLE_CONFIG_FIELDS`, and the
  `effective_mode(session)` helper (thin wrapper over `Session.effective('mode')` —
  no parallel mechanism).
- `game/models.py` (end of file) — `Trail` (+ `validate_structure()`), `TrailStep`,
  `TrailEdge`, `TeamTrailRoute` (+ `sequence()` resolution), `TeamTrailRouteStep`
  through-rows, `TeamTrailProgress` (+ monotonic `advance()`), and the
  structure/knowledge/participation choice constants.
- `game/trail.py` (new) — the progression engine: party resolution, initial-reveal
  seeding, `next_steps()` per structure, `clue_for()` (edge clue for GRAPH, target
  step clue for linear), the `on_submission_created` / `on_submission_confirmed`
  hooks, `read_only_gate_step()`, `revealed_tower_ids()` masking, and `ranking()`.
- `game/trail_api.py` (new) — player `GET /api/trail/state|next|leaderboard/` and
  staff `AdminTrail*ViewSet`s + per-session `SessionTrailRoutes(/auto-generate)`,
  `SessionTrailRevealStartView`, `SessionTrailLeaderboardView`.
- Migrations: `organize/0018_game_mode.py`, `game/0028_trail_discovery.py`
  (chained off the 0017/0027 heads; renumber at merge if needed).

**Pipeline decisions the merger should know**
- The submission serializer check order gained ONE insertion:
  after the pause/lockout gates and immediately BEFORE the outcome resolution,
  a challenge-less submission (handler `None`, no challenge) asks
  `game.trail.read_only_gate_step()` whether it acknowledges the party's current
  gate-less trail step; if so the outcome resolves CONFIRMED (system-attributed,
  same stamps as the AUTO types). Everything else (membership → tower/RFID →
  handler/payload → proximity → role gate → pause → lockout → outcome LAST) is
  untouched, so all challenge-type-system invariants hold in TRAIL mode too —
  an auto gate still cannot bypass proximity/pause/lockout.
- Domination capture is gated on effective mode in exactly two places:
  `TeamTowerChallenge.save()` (PENDING→CONFIRMED staff-review transition) and
  `TeamTowerChallengeViewSet.perform_create` (auto-confirm insert). In TRAIL mode
  both call the trail hooks instead of `tower.assign_to_team()`; no ownership rows,
  no initial bonus, no zone/floating points (asserted by tests). REJECTED failure
  consequences (cooldown/lockout/penalty) are NOT mode-gated — they are generic
  anti-brute-force mechanics and trail ranking ignores `Team.score` anyway.
- Progression is strictly structural: a submission at a tower that is not one of
  the party's current `next_steps()` advances nothing (ALL_KNOWN visibility never
  lets a party skip ahead). A confirmed submission at the right tower but with a
  challenge that is not the step's gate counts as arrival only.
- SOLO participation binds route/progress rows to `UserProfile` (`player` FK,
  `team` NULL) via conditional unique constraints; TEAM binds to the team. The
  engine resolves the party from the trail's `participation` +
  `ttc.submitted_by.profile`. Solo players still submit through their (solo) team
  membership — the existing submission pipeline is unchanged.

**Scope notes / deviations**
- Task 4.4: the `tower-visibility` capability is NOT part of this integration
  state (its change is unimplemented), so per-party masking is implemented
  directly: `game.trail.revealed_tower_ids()` filters the player `TowerViewSet`
  queryset on TRAIL sessions. That function is the seam to delegate through when
  tower-visibility ships.
- Task 2.4: the validator runs on every staff API read (`issues` field) plus a
  `GET /api/staff/trails/{id}/validate/` action; the out-of-Collection tower rule
  is additionally enforced as a hard 400 on step create/update. Graph issues
  (unreachable / dead-end / finish-unreachable) are warnings, not save blockers —
  authoring proceeds incrementally, matching design's "surface warnings".
- Route auto-generation (beyond the first-cut non-goal, per the task brief):
  `POST /api/staff/sessions/{id}/trail-routes/auto-generate/` — FIXED_ORDER gives
  each party the base order rotated by an even offset (explicit through-rows),
  CIRCUIT spaces `start_step`s evenly on the loop, GRAPH deals start steps
  round-robin. Replaces existing routes for the session.
- Frontend is wireframe-quality Bootstrap: player `/trail` screen (clue card,
  branch chooser, progress list, finish banner, NONE_KNOWN start hint) and staff
  `/trails` designer (trail list/config + step table + edge table + per-session
  route table with auto-generate/reveal-start + leaderboard). Steps are added by
  tower id in a table — NO map placement / graph canvas (per the reduced
  wireframe scope). Both apps `ng build` green.
- Scoreboard endpoints are untouched: a TRAIL session's team scores stay 0 and
  the trail leaderboard is a separate endpoint; hiding the domination scoreboard
  for TRAIL sessions in the UIs is left to a future polish pass.

**Expected merge conflict hotspots**
- `organize/models.py` (OVERRIDABLE_CONFIG_FIELDS + Game/Session fields),
  `game/models.py` (imports + `TeamTowerChallenge.save()` CONFIRMED branch + new
  models at EOF), `game/serializers.py` (import + outcome-resolution insertion),
  `game/views.py` (imports, TowerViewSet.get_queryset, perform_create),
  `game/admin.py` + `organize/admin.py` (registrations/list_display),
  `game/admin_api.py` (Game/Session serializer field lists), `organize/api.py`
  (CurrentSessionSerializer), `geogame/urls.py` (imports + router + trail paths),
  `game/tests.py` (import block + new section at EOF), migration numbering
  (organize 0018 / game 0028), frontend: `shared/game-api.service.ts`,
  `player/app.routes.ts`, `player/app.html`, `staff/app.routes.ts`,
  `staff/app.html`.
