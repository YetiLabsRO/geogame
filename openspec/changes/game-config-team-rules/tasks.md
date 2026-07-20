## 1. Model fields & config plumbing

- [x] 1.1 Add `min_teams` (PositiveSmallIntegerField, default 1), `max_teams` (default 0 = no cap), `min_members_per_team` (default 1), and `max_members_per_team` (default 0 = no cap) to `organize.Game`.
- [x] 1.2 Add the four matching nullable overrides (`null=True, blank=True`) to `organize.Session`.
- [x] 1.3 Register the four field names in `OVERRIDABLE_CONFIG_FIELDS` so `Session.effective(field)` resolves override-or-default.
- [x] 1.4 Generate and apply the schema migration; confirm no data migration is needed (all defaults are backward compatible).

## 2. Readiness & start-gate services

- [x] 2.1 Add `Team.active_member_count()` (count of `TeamMembership` with `is_active=True`) and `Team.is_ready(when=None)` comparing it against the Session's effective min/max members (0 max = uncapped).
- [x] 2.2 Add `Session.ready_team_count()` and `Session.start_blockers()` returning tagged, human-readable reasons (too few / too many teams; each under-filled or over-filled team), plus `Session.can_start()` = `not start_blockers()`.
- [x] 2.3 Enforce `max_members_per_team` at join time: reject invite-accept / admin-add into a team already at the effective maximum with a clear error.

## 3. API

- [x] 3.1 Expose the four knobs on the staff Games serializer (`POST`/`PATCH /api/staff/games/`) and the four overrides on the staff Sessions serializer.
- [x] 3.2 Expose `active_member_count` and `is_ready` (read-only) on the teams serializer.
- [x] 3.3 Gate the Session start action: when `start_blockers()` is non-empty, return `409`/`400` with the `blockers` list and do not transition; otherwise start normally.

## 4. Frontend (Angular v21, standalone / signals / OnPush)

- [x] 4.1 Add the four team-rule inputs to the staff Game editor and the per-Session override form (blank = inherit).
- [x] 4.2 On the Session start control, disable/annotate the button with the returned `blockers`; show each team's `active_member_count` vs. the required minimum.
- [x] 4.3 In the player/team view, show "needs N more members" until the team is ready.

## 5. Tests

- [x] 5.1 `Session.effective()` resolves each new field: Session override wins, else Game default; unknown field still raises.
- [x] 5.2 Readiness: a team below `min_members_per_team` is not ready; a team within range is ready; `max=0` means uncapped.
- [x] 5.3 Start-gate: a Session below `min_teams` (counting only ready teams) is blocked; padding an empty second team does not satisfy `min_teams=2`; over `max_teams` is blocked; all-thresholds-met starts and reports zero blockers.
- [x] 5.4 Join-cap: accepting into a full team is rejected; joining a team with room succeeds.
- [x] 5.5 Backward compatibility: a Game/Session left at defaults (`min_teams=1`, maxima `0`, `min_members_per_team=1`) starts with a single one-member team exactly as before.
- [x] 5.6 API: start endpoint returns the `blockers` payload when unmet and transitions when met; teams endpoint exposes `active_member_count` / `is_ready`. Keep `game` coverage ≥ 80% and ruff-clean.

## Implementation notes

Implemented on branch `impl/game-config-team-rules`. Final state: 245 tests green
(`manage.py test game organize`), ruff clean, coverage 94% total (game + organize),
both Angular apps (`player`, `staff`) build in development configuration.

### Semantics decisions (within design.md's latitude)

- **Gate semantics**: `start_blockers()` blocks when (a) the *ready*-team count is
  below the effective `min_teams` (per-team `team_below_minimum` blockers with the
  exact shortfall are emitted alongside `too_few_teams` to explain which teams don't
  count), (b) the *total* team count exceeds a non-zero `max_teams`, or (c) any team
  is over a non-zero `max_members_per_team` (`team_above_maximum`). A non-ready team
  does NOT by itself block a start when enough other teams are ready — this preserves
  the spec's backward-compat scenario ("startable as soon as it has one team with at
  least one active member") even if a stray empty team exists.
- **Blocker shape**: dicts with machine `code` (`too_few_teams`, `too_many_teams`,
  `team_below_minimum`, `team_above_maximum`), human `message`, and numeric context
  (`required`/`allowed`/`current`/`shortfall`, plus `team_id`/`team_name`).
- **"Start" transition**: with no state machine yet (parallel `game-lifecycle-states`
  change), the start transition is the staff PATCH flipping `Session.is_active`
  False→True in `AdminSessionViewSet.perform_update`. The gate itself lives entirely
  on the model (`Session.start_blockers()` / `can_start()` / `ready_team_count()`) so
  the lifecycle branch can call the same helper from its formal transition. Violations
  return **409** with `{'detail': ..., 'blockers': [...]}` and roll the save back
  (the atomic block re-raises), so overrides sent in the same PATCH are also undone.
- **Session create is NOT gated** (`POST /api/staff/sessions/` with
  `is_active=true` still succeeds with zero teams) to preserve baseline behaviour and
  tests; gating creation is left to the formal lifecycle change.
- **Join-cap**: `invite_accept` raises a 409 `TeamFullError` APIException (so the
  surrounding `@transaction.atomic` rolls back the account created for an anonymous
  acceptor); re-accepting while already an active member of the team is exempt.
  Admin-add is enforced via `TeamMembership.clean()` (runs on the Django admin form's
  `full_clean`); the model-level check excludes `self.pk` so edits of existing rows
  don't trip the cap.
- **Serializer validation** (shared `_validate_team_rules` helper in
  `game/admin_api.py`): minima ≥ 1, and a non-zero maximum may not be smaller than
  its corresponding minimum; the Session serializer validates against *resolved*
  values (payload → instance override → Game default), so an override combination
  that conflicts with inherited values is rejected too.

### Additions beyond the literal task list (all additive)

- `Team.members_needed()` (shortfall — the teams-and-groups delta requires the
  shortfall to be "available to callers") and `Team.active_member_count(when=...)`
  historical variant (tasks.md names `is_ready(when=None)`).
- Read-only `GET /api/staff/sessions/{id}/start_blockers/` action returning
  `{can_start, blockers, min_members_per_team, teams: [{id, name, color,
  active_member_count, is_ready, members_needed}]}` so the staff UI can annotate the
  start control without attempting the transition (needed for task 4.2).
- `members_needed` also exposed next to `active_member_count` / `is_ready` on the
  player teams serializer, the staff teams serializer, and `MyTeamSerializer`
  (`/api/my-team/`) — the player team view is built on the latter.
- New player page `/team` (`frontend/projects/player/src/app/team/team.component.ts`
  + route + navbar link): the player app previously had no team view at all; it shows
  the roster and the "needs N more members" alert (task 4.3).

### Migration

- `organize/migrations/0011_game_team_rules.py` (eight fields, defaults only, no
  data migration). It was validated by the test-DB build but **NOT applied to the
  shared dev database** — sibling branches also create an `0011_*` migration and the
  merger renumbers; applying here would poison the shared dev DB's migration history.

### Expected merge-conflict hotspots

- `organize/models.py` (OVERRIDABLE_CONFIG_FIELDS tuple, Game/Session field blocks,
  new Team/Session methods) — especially vs. `game-lifecycle-states`.
- `game/admin_api.py` (AdminGame/AdminSession serializer `fields` tuples,
  `AdminSessionViewSet.perform_update`, new actions) — the lifecycle branch will
  touch the same activation path; its start transition should call
  `session.start_blockers()` and surface the same payload.
- `organize/migrations/0011_*` numbering vs. sibling branches.
- `game/tests.py` / `organize/tests.py` (appended test classes at EOF).
- Frontend: `shared/staff-api.service.ts` (AdminGame/AdminSession interfaces),
  `staff/admin/sessions.component.ts`, `staff/admin/session-detail.component.ts`,
  `player/app.routes.ts` / `app.html` (additive route + nav link).
