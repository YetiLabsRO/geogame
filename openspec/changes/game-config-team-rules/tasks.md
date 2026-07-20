## 1. Model fields & config plumbing

- [ ] 1.1 Add `min_teams` (PositiveSmallIntegerField, default 1), `max_teams` (default 0 = no cap), `min_members_per_team` (default 1), and `max_members_per_team` (default 0 = no cap) to `organize.Game`.
- [ ] 1.2 Add the four matching nullable overrides (`null=True, blank=True`) to `organize.Session`.
- [ ] 1.3 Register the four field names in `OVERRIDABLE_CONFIG_FIELDS` so `Session.effective(field)` resolves override-or-default.
- [ ] 1.4 Generate and apply the schema migration; confirm no data migration is needed (all defaults are backward compatible).

## 2. Readiness & start-gate services

- [ ] 2.1 Add `Team.active_member_count()` (count of `TeamMembership` with `is_active=True`) and `Team.is_ready(when=None)` comparing it against the Session's effective min/max members (0 max = uncapped).
- [ ] 2.2 Add `Session.ready_team_count()` and `Session.start_blockers()` returning tagged, human-readable reasons (too few / too many teams; each under-filled or over-filled team), plus `Session.can_start()` = `not start_blockers()`.
- [ ] 2.3 Enforce `max_members_per_team` at join time: reject invite-accept / admin-add into a team already at the effective maximum with a clear error.

## 3. API

- [ ] 3.1 Expose the four knobs on the staff Games serializer (`POST`/`PATCH /api/staff/games/`) and the four overrides on the staff Sessions serializer.
- [ ] 3.2 Expose `active_member_count` and `is_ready` (read-only) on the teams serializer.
- [ ] 3.3 Gate the Session start action: when `start_blockers()` is non-empty, return `409`/`400` with the `blockers` list and do not transition; otherwise start normally.

## 4. Frontend (Angular v21, standalone / signals / OnPush)

- [ ] 4.1 Add the four team-rule inputs to the staff Game editor and the per-Session override form (blank = inherit).
- [ ] 4.2 On the Session start control, disable/annotate the button with the returned `blockers`; show each team's `active_member_count` vs. the required minimum.
- [ ] 4.3 In the player/team view, show "needs N more members" until the team is ready.

## 5. Tests

- [ ] 5.1 `Session.effective()` resolves each new field: Session override wins, else Game default; unknown field still raises.
- [ ] 5.2 Readiness: a team below `min_members_per_team` is not ready; a team within range is ready; `max=0` means uncapped.
- [ ] 5.3 Start-gate: a Session below `min_teams` (counting only ready teams) is blocked; padding an empty second team does not satisfy `min_teams=2`; over `max_teams` is blocked; all-thresholds-met starts and reports zero blockers.
- [ ] 5.4 Join-cap: accepting into a full team is rejected; joining a team with room succeeds.
- [ ] 5.5 Backward compatibility: a Game/Session left at defaults (`min_teams=1`, maxima `0`, `min_members_per_team=1`) starts with a single one-member team exactly as before.
- [ ] 5.6 API: start endpoint returns the `blockers` payload when unmet and transitions when met; teams endpoint exposes `active_member_count` / `is_ready`. Keep `game` coverage ≥ 80% and ruff-clean.
