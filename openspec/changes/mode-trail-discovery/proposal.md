## Why

Domination (capture towers, hold zone majorities for floating points) is the only game type the platform supports. The product wants a second, distinct game type built on the **same building blocks** — the repository points/towers, geofencing, and challenges — but with a different core loop: a **trail / discovery** run. Players are given a set of points and must travel from one to the next; each point yields a **clue** to the following point, so the game is about progression and route-finding rather than territorial control. Because it reuses Towers, Collections, proximity checks, and Challenges, it costs far less than a from-scratch mode, and it unlocks scavenger-hunt, orienteering, and story-trail formats for single players or competing teams.

## What Changes

- Add a **game mode** switch: `organize.Game` gains a `mode` of `DOMINATION` (default, current behaviour) or `TRAIL`. A trail-mode Session runs the trail loop instead of zone/floating-point scoring; all existing domination behaviour is untouched when `mode = DOMINATION`.
- Add a **trail structure model** over repository geometry: `game.Trail` (attached to a Game), `game.TrailStep` (a node bound to a repository `Tower`, geofenced), and `game.TrailEdge` (a directed clue-bearing link between steps, enabling branches). A Trail's `structure` is `FIXED_ORDER` (linear 1→2→3→4), `GRAPH` (branching; the team picks the next point from several revealed clues), or `CIRCUIT` (a single loop that every team runs but each team **starts at a different point** and follows the order from its own start).
- Add **starting knowledge** as a Trail knob: `ALL_KNOWN` (every step's point is known up front), `ONE_KNOWN` (only the start point is known), or `NONE_KNOWN` (no point is known — the team must first discover the start).
- Add a **clue / unlock gate** on each step: on arriving at a step's geofenced point the team performs an unlock action — answer a question, read a clue, or submit a team photo — modelled as a `Challenge` and reusing the challenge-type validation flow (see the `challenge-types` capability). Completing the gate reveals the next step(s) and their clue(s) to that team.
- Add **per-team route assignment**: `game.TeamTrailRoute` assigns each team (or solo player) its own start and, for `FIXED_ORDER`/`CIRCUIT`, its own ordered sequence of steps, so different teams walk different routes (e.g. 1-2-3-4 vs 1-3-2-4-7) and do not bump into each other.
- Add **per-team progress + reveal tracking**: `game.TeamTrailProgress` records, per team, which steps are revealed / arrived / unlocked and the current position. Per-team point reveal reuses the discovery/visibility machinery (see the `tower-visibility` capability) so an unrevealed trail point stays hidden on the team's map.
- Add **single-player or multi-team participation**: a Trail's `participation` is `TEAM` or `SOLO`.
- Add **trail completion + ranking**: a team finishes when it reaches its finish step (or has visited all required steps); Sessions rank teams by completion and time. This is trail-mode scoring, distinct from domination floating points.
- Add staff/creator authoring APIs (trails, steps, edges, route assignment) and player APIs (current trail state, revealed clues, branch options).

## Capabilities

### New Capabilities
- `mode-trail-discovery`: a distinct trail/discovery game type on the shared building blocks — a set of geofenced points, variable starting knowledge, clue-driven point-to-point progression (fixed order, branching graph, or start-offset circuit), per-team routes, and single-player or multi-team play.

### Modified Capabilities
<!-- None. Trail mode is additive: it introduces a new capability and only reads existing ones (challenge-types, tower-visibility, geographic-map, challenge-submission) without modifying their requirements. -->

## Impact

- **Models**: new `game.Trail` (1:1 to a trail-mode `Game`), `game.TrailStep`, `game.TrailEdge`, `game.TeamTrailRoute` (+ ordered through-rows for a team's personal sequence), `game.TeamTrailProgress`; new `Game.mode` field (with a nullable per-`Session` override per the effective-value config pattern).
- **APIs**: new `/api/staff/trails/`, `/api/staff/trail-steps/`, `/api/staff/trail-edges/`, and `/api/staff/sessions/{id}/trail-routes/`; new player `GET /api/trail/state/` and `GET /api/trail/next/`; step arrival + gate unlock ride the existing challenge-submission endpoint.
- **Frontend**: player SPA gains a trail view (current point, active clue, branch chooser, progress); staff SPA gains a trail authoring editor (steps on the map, edges/clues, per-team route assignment) and a trail leaderboard.
- **Migrations/other**: additive migration adding `Game.mode` (default `DOMINATION`) and the new trail tables; no change to existing domination data or behaviour.
