## Why

A Game today can be started with any number of teams of any size, but real events have composition rules: a competitive domination game is meaningless with a single team, while a solo scavenger variant is perfectly playable with one. Teams also need a minimum head-count (and sometimes a cap) before play is fair. Nothing currently stops a runner from starting a Session with zero teams, one team in a two-team game, or half-empty teams. This change adds per-Game team-composition rules — minimum/maximum team count and minimum/optional-maximum members per team — and gates the start of a Session on those thresholds so a run cannot begin under-populated.

## What Changes

- Add per-Game team-composition knobs on `organize.Game` (defaults): `min_teams`, `max_teams`, `min_members_per_team`, `max_members_per_team`. Maxima use `0` to mean "no cap"; defaults preserve today's "any single team of one may play" behaviour.
- Add matching nullable per-Session overrides on `organize.Session` (NULL = inherit the Game default), resolved through the existing `Session.effective(field)` helper, and register the four fields in `OVERRIDABLE_CONFIG_FIELDS`.
- Define **team readiness**: a Team is *ready* when its active `TeamMembership` count is at least the effective `min_members_per_team` and (when capped) at most the effective `max_members_per_team`; expose the active member count and readiness on the teams API.
- Add **start-gating**: the action that moves a Session into active play (RUNNING) SHALL refuse while the number of teams is outside `[min_teams, max_teams]` or any counted team is not ready, returning the specific unmet thresholds as blockers.
- Enforce the per-team maximum at join time so a team cannot grow past `max_members_per_team`.
- Staff/creator API + Angular UI: edit the four knobs on the Game (and per-Session overrides), and surface start-blockers on the Session start control.

## Capabilities

### New Capabilities
<!-- None -->

### Modified Capabilities
- `game-configuration`: a Game gains configurable team-count and per-team member-count rules as defaults.
- `teams-and-groups`: introduces team readiness computed from active-membership counts and exposes it on the teams API.
- `sessions`: adds nullable per-Session overrides for the team rules and gates the Session start transition on team-count and per-team member-count thresholds.

## Impact

- **Models**: `organize.Game` gains `min_teams` (default 1), `max_teams` (default 0 = no cap), `min_members_per_team` (default 1), `max_members_per_team` (default 0 = no cap); `organize.Session` gains four nullable overrides of the same names; the four names are added to `OVERRIDABLE_CONFIG_FIELDS`.
- **APIs**: staff Games/Sessions endpoints accept the new fields; the teams API exposes `active_member_count` and `is_ready`; the Session start action returns `409`/`400` with a `blockers` list when thresholds are unmet; team join/accept flows reject growth past the max.
- **Frontend**: staff Game editor + Session override form gain the four inputs; the Session start control shows why a start is blocked; the player/team view shows how many more members a team needs.
- **Migrations/other**: one schema migration adding the eight fields (all with backward-compatible defaults). No data migration required.
