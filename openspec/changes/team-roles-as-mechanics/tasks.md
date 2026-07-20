## 1. Role model & assignment

- [x] 1.1 Add `organize.GameRole` (`game` FK `related_name='roles'`, `name`, URL-safe `slug`, optional `description`, `builtin_power` enum with `NONE`/`INVITER` default `NONE`, `created_at`) with unique `(game, slug)`; register in admin.
- [x] 1.2 Add `organize.TeamRole` (`membership` FK to `TeamMembership` `related_name='roles'`, `role` FK to `GameRole` `related_name='assignments'`, `assigned_by` nullable, `assigned_at`) with unique `(membership, role)`; validate `role.game_id == membership.game_id` in `clean()`/`save()`; register in admin.
- [x] 1.3 Add convenience accessors: `TeamMembership.role_slugs()` and `Team.active_role_slugs()` (distinct roles held by the team's active memberships); migrations.

## 2. Challenge role-requirement config

- [x] 2.1 Add to `game.Challenge`: `role_requirement_mode` (`NONE`/`ALL`/`ANY`, default `NONE`), `required_roles` (M2M to `organize.GameRole`, blank), `require_holders_present` (BooleanField default `False`); migration.
- [x] 2.2 Implement `Challenge.team_satisfies_roles(team)` returning `(ok, missing_role_slugs)`: `NONE` → always ok; `ANY` → true if the team's active role holders cover at least one `required_role`; `ALL` → true only if they cover every `required_role`. Count distinct roles covered, never member head-count.
- [x] 2.3 Validation: `required_roles` must belong to the challenge's Game; a non-`NONE` mode with an empty `required_roles` is rejected.

## 3. Built-in INVITER power

- [x] 3.1 Add a helper `UserProfile.can_invite_to(team)` → true if staff, or the user's active `TeamMembership` in that team holds a role with `builtin_power=INVITER`.
- [x] 3.2 Authorize invite creation for `INVITER` holders on their own team, extending the existing staff-only path (coordinate with the `team-invites` / `team-formation` capabilities); non-holders and non-staff still denied.

## 4. Enforcement at submission

- [x] 4.1 In the `TeamTowerChallenge` create path, after deriving the submitting team, call `challenge.team_satisfies_roles(team)`; on failure refuse the submission (HTTP 400) with a reason naming the missing roles. Ordering relative to proximity/cooldown checks documented.
- [x] 4.2 When `require_holders_present` is `True`, defer the "holder present" test to the `presence-rules` capability if available; otherwise treat assignment as sufficient (default path).

## 5. APIs

- [x] 5.1 `GET/POST/PATCH/DELETE /api/staff/game_roles/` scoped to a Game (creator/runner authoring); expose `builtin_power`.
- [x] 5.2 Role assign/unassign actions on a team membership (staff/runner), filtering selectable roles to the membership's Game.
- [x] 5.3 Expose `role_requirement_mode` + `required_roles` (read/write for staff) on challenge endpoints; expose each member's roles on `GET /api/teams/`.
- [x] 5.4 On the player challenge surface, expose the challenge's role requirement and a `team_satisfies` boolean for the caller's team.

## 6. Frontend

- [x] 6.1 Staff: per-Game role editor (name, slug, description, built-in power) and roster role assignment UI.
- [x] 6.2 Staff: challenge editor gains a role-requirement section (mode + role picker + `require_holders_present`).
- [x] 6.3 Player: show own roles; on a challenge show its role requirement and whether the team currently satisfies it; show an "invite" affordance to `INVITER` holders.

## 7. Cloning

- [x] 7.1 Extend the Game-clone routine (see the `game-authoring-roles` capability) to deep-copy `GameRole`s and remap each cloned challenge's `required_roles` to the cloned roles.

## 8. Tests

- [x] 8.1 `GameRole`/`TeamRole` model tests: unique `(game, slug)`, unique `(membership, role)`, and rejection of a `TeamRole` whose role's Game differs from the membership's Game.
- [x] 8.2 `team_satisfies_roles` tests: `NONE` always passes; `ANY` passes on one covered role; `ALL` fails until every role is covered; **one member holding two required roles satisfies `ALL`**; ten members holding none fail.
- [x] 8.3 Submission enforcement: a team missing a required role is refused with the missing roles named; the same team passes after assignment; default (`NONE`) path unchanged.
- [x] 8.4 INVITER power: a member holding an `INVITER` role may create an invite for their own team; a non-holder non-staff member cannot; staff still can; no `INVITER` role defined ⇒ invite creation stays staff-only.
- [x] 8.5 Backward compatibility: a Game with no roles and all challenges at `role_requirement_mode=NONE` yields identical submission, invite, and teams-API behavior to before the change.
- [x] 8.6 Clone test: cloning a Game copies its `GameRole`s and rewires cloned challenges' `required_roles` to the cloned roles (no reference to the original's roles).
- [x] 8.7 Ruff-clean; branch coverage ≥ 80% for the new code.

## Implementation notes

Implemented on branch `impl/team-roles-as-mechanics` (worktree). All 25 tasks done;
260 tests green (`manage.py test game organize`), ruff clean, both Angular apps build.

**Deviations / decisions**

- **2.3 (config validation)** lives in `AdminChallengeSerializer.validate()` (the only
  write surface for role config), not in `Challenge.clean()` — M2M state is not
  reliably visible at model-save time. `team_satisfies_roles` still treats a
  non-NONE mode with an empty set defensively as satisfied.
- **3.2 (INVITER hook)** is deliberately minimal because `player-team-formation`
  is reworking the invite flow in parallel: `InviteListCreate` swaps
  `IsAdminUser` for a small `InviteCreatePermission` (staff: everything;
  authenticated non-staff: POST only) and `perform_create` object-checks
  `organize.models.user_can_invite_to_team(user, team)` (403 otherwise).
  Listing stays staff-only. **The helper is the seam** — the reworked invite
  flow should call `user_can_invite_to_team` / `UserProfile.can_invite_to`
  wherever it authorizes invite creation.
- **4.1 (check order)** documented in `TeamTowerChallengeSerializer`: membership →
  tower/RFID → GPS proximity → role gate → pause → failure lockout. Error is a
  DRF 400 with `detail` (Romanian, matching neighboring messages) plus a
  machine-readable `missing_roles` list. RFID captures carry no `challenge`, so
  no role gate applies to them.
- **4.2 (`require_holders_present`)** is stored and surfaced (staff editor +
  player payload) but only documents intent: presence-rules capability is not
  in the tree, so assignment alone suffices (the specified default path).
- **7.1 (clone)**: there is NO pre-existing Game-clone routine in the codebase
  (`game-authoring-roles` is not implemented anywhere yet), so `Game.clone()`
  was created in `organize/models.py` as the seam. It deep-copies config fields,
  TeamGroups, GameRoles and Challenges, remapping `required_roles` to the
  clone's roles. **Zones/Towers are NOT cloned** (kept out per the coordination
  constraint); tower-linked challenges are copied with `tower=None` so the clone
  never references the original's objects. `game-authoring-roles` should extend
  this routine with zone/tower copying and challenge→tower remapping. No API
  endpoint calls clone yet — it is a model method covered by tests.
- **5.1 URL** is `/api/staff/game_roles/` (underscore, as the delta spec spells
  it), unscoped like `AdminSessionViewSet` with `?game=<id>` filtering; a list
  without the param falls back to the caller's current Session's Game (detail
  routes are unscoped so the Games page can edit any game's roles).
- **5.2** added `/api/staff/memberships/` (session-scoped ReadOnly viewset,
  `?team=` filter) with `assign_role` / `unassign_role` POST actions;
  `assign_role` is idempotent (get_or_create) and records `assigned_by`.
- **5.3** `GET /api/teams/` gained an additive `members` array (user_id,
  username, roles); `GET /api/my-team/` members gained `roles` and the payload
  gained `can_invite`; `GET /api/me/` gained `active_roles`.
- **6.x frontend (Bootstrap wireframe)**: staff Games page has a per-game
  "Roles" expander (`game-roles-panel.component.ts`), Teams page a per-team
  "Roster" expander with badge/assign UI (`team-roster-panel.component.ts`),
  Challenges rows a role-requirement column (mode + role checkboxes + holders
  present; creation defaults to NONE, edited on the row). Player: new `/team`
  page (`my-team.component.ts`, additive route + "Team" nav link) with own
  roles, member role badges and an INVITER-gated invite-link creator;
  tower-detail shows the requirement badges + satisfied/missing state.

**Merge conflict hotspots for the merger**

- `organize/models.py` (new GameRole/TeamRole models, `Game.clone`,
  `UserProfile.can_invite_to`, `user_can_invite_to_team`) — high traffic.
- `organize/api.py` (invite permission swap + serializer role fields) — the
  `player-team-formation` branch WILL conflict here; keep the
  `user_can_invite_to_team` check when merging their reworked flow.
- `game/models.py` (Challenge fields + `team_satisfies_roles`),
  `game/serializers.py` (role gate in validate()), `game/admin_api.py`
  (two new viewsets + challenge serializer), `geogame/urls.py` (two router
  registrations), `game/api.py` (tower-state payload).
- Migrations `organize/0011_gamerole_teamrole.py` and
  `game/0022_challenge_role_requirements.py` — numbering conflicts with
  parallel branches expected; renumber at merge.
- Frontend: `shared/staff-api.service.ts`, `shared/game-api.service.ts`,
  `shared/auth.service.ts` (UserProfile gained `active_roles`),
  `staff app` games/teams/challenges components, player `app.routes.ts` /
  `app.html`.
- `AdminChallenge` TS interface now REQUIRES the three role fields —
  any parallel branch constructing challenge payloads must include them
  (see `challenges.component.ts` create()).
