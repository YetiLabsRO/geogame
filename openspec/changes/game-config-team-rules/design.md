## Context

`organize.Game` is the reusable template and already carries a family of gameplay knobs as
**defaults**, each shadowed by a **nullable per-Session override** and resolved through
`Session.effective(field)` against the `OVERRIDABLE_CONFIG_FIELDS` allow-list (this is how the
Phase 10 pause and challenge-failure knobs work). `organize.Team` owns its members through the
`TeamMembership` through-model, whose `is_active=True` rows are the live roster and are already
uniquely constrained per `(team, user)` and per `(user, game)`.

There is currently **no gate on starting a run**: a Session begins play by being activated, and
nothing checks how many teams exist or how full they are. Competitive domination is meaningless
with one team, while some variants are fine with one; team sizes likewise need a floor and
sometimes a cap. This change adds the composition rules and the start-gate, reusing the
established defaults-plus-override pattern so it stays consistent with every other knob.

## Goals / Non-Goals

**Goals:**
- Let a creator declare, per Game, the minimum and maximum number of teams and the minimum and
  optional-maximum number of members per team.
- Resolve those rules per Session via nullable overrides, exactly like the existing config knobs.
- Refuse to move a Session into active play (RUNNING) until the team-count and per-team
  member-count thresholds are satisfied, reporting the specific unmet thresholds.
- Default every knob so that existing Games and Sessions keep starting exactly as they do today.

**Non-Goals:**
- The formal Session lifecycle state machine (DRAFT → OPEN_FOR_PARTICIPANTS → RUNNING ⇄ PAUSED →
  FINISHED). That is the `game-lifecycle-states` change; here the start-gate simply attaches to
  whatever transition begins play, referenced as "start / move to RUNNING".
- Player-created teams and join-request flows (`player-team-formation`).
- Role-based composition rules such as "one INVITER present" — that is `team-roles-as-mechanics`.
- Balancing team sizes across teams, waitlists, or auto-assignment.

## Decisions

- **Four knobs on Game, four nullable overrides on Session, added to `OVERRIDABLE_CONFIG_FIELDS`.**
  Mirrors `proximity_meters` and the pause/failure knobs so `Session.effective('min_teams')` etc.
  resolve override-or-default with zero new machinery. Alternative considered: a separate
  `TeamRuleSet` model — rejected because it fragments the config pattern for four scalar fields.
- **Maxima use `0` to mean "no cap", minima default to `1`.** `max_teams` and
  `max_members_per_team` default to `0`. This keeps NULL free to mean "inherit" at the Session
  level without a three-valued muddle (NULL = inherit, `0` = explicitly uncapped, `n>0` = capped).
  `min_teams` and `min_members_per_team` default to `1`. Alternative considered: nullable maxima
  where NULL means "no cap" — rejected because then NULL would mean both "inherit" (Session) and
  "no cap" (Game), so a Session could not distinguish the two.
- **Defaults preserve current behaviour.** With `min_teams=1`, `max_teams=0`,
  `min_members_per_team=1`, `max_members_per_team=0`, the gate only ever blocks a genuinely
  unstartable run (no teams, or a team with no members). A creator opts into competitiveness by
  raising `min_teams` to `2` (or higher) and into size floors/caps by setting the member fields.
- **Team readiness is derived, not stored.** `Team.is_ready(when=None)` counts active memberships
  and compares against the effective min/max. Storing readiness would drift as members join/leave;
  computing it on read is cheap and always correct.
- **Which teams count toward the team-count threshold.** A Session's team count for gating is the
  number of its `Team` rows that are *ready* (satisfy the per-team member rule). This makes the two
  thresholds compose: "≥2 teams" means "≥2 teams that each meet the member minimum", so a second
  empty team cannot satisfy a two-team requirement. Alternative considered: count all teams
  regardless of readiness — rejected because it lets a padding team unlock the start.
- **Start-gate is a single service.** `Session.start_blockers()` returns an ordered list of
  human-readable, machine-tagged blockers (empty ⇒ startable); `Session.can_start()` is
  `not start_blockers()`. The start endpoint calls it and returns the blockers instead of
  transitioning when non-empty. Centralising it keeps the API, admin, and any future lifecycle
  transition consistent.
- **Enforce `max_members_per_team` at join time too.** Accepting an invite or an admin add into a
  team already at the effective maximum is rejected with a clear error, so a team cannot exceed its
  cap between the start-gate check and the actual start.

## Risks / Trade-offs

- [A Session-level "inherit" (NULL) cannot express "uncapped here even though the Game caps"] →
  Accepted: use the `0` sentinel at whichever level actually holds the value; a runner who wants no
  cap for one run sets the Session override to `0` explicitly rather than NULL.
- [Counting only ready teams could confuse a runner who sees N teams but a blocked start] →
  Mitigation: `start_blockers()` names each under-filled team and the exact shortfall, and the API
  exposes `active_member_count` / `is_ready` per team so the UI can highlight the offending teams.
- [A team could drop below the minimum after the Session starts (a member leaves mid-run)] →
  Accepted as out of scope: the gate governs the *start* transition only; mid-run composition is
  not re-validated here.
- [Existing Sessions might sit at `min_teams=1` with zero teams and now fail to start] → This is
  correct behaviour (an empty run should not start); it is not a regression because no real run
  starts with zero teams, and the blocker message explains it.

## Migration Plan

1. Add the four default fields to `organize.Game` (`min_teams=1`, `max_teams=0`,
   `min_members_per_team=1`, `max_members_per_team=0`) and the four nullable overrides to
   `organize.Session`; add all four names to `OVERRIDABLE_CONFIG_FIELDS`.
2. Generate one schema migration. All fields have backward-compatible defaults, so existing rows
   need no data migration and resolve to the current "single team of one may play" behaviour.
3. Add `Team.active_member_count()` / `Team.is_ready()` and `Session.start_blockers()` /
   `Session.can_start()`; route the Session start action and team join/accept flows through them.
