## 1. Role model & assignment

- [ ] 1.1 Add `organize.GameRole` (`game` FK `related_name='roles'`, `name`, URL-safe `slug`, optional `description`, `builtin_power` enum with `NONE`/`INVITER` default `NONE`, `created_at`) with unique `(game, slug)`; register in admin.
- [ ] 1.2 Add `organize.TeamRole` (`membership` FK to `TeamMembership` `related_name='roles'`, `role` FK to `GameRole` `related_name='assignments'`, `assigned_by` nullable, `assigned_at`) with unique `(membership, role)`; validate `role.game_id == membership.game_id` in `clean()`/`save()`; register in admin.
- [ ] 1.3 Add convenience accessors: `TeamMembership.role_slugs()` and `Team.active_role_slugs()` (distinct roles held by the team's active memberships); migrations.

## 2. Challenge role-requirement config

- [ ] 2.1 Add to `game.Challenge`: `role_requirement_mode` (`NONE`/`ALL`/`ANY`, default `NONE`), `required_roles` (M2M to `organize.GameRole`, blank), `require_holders_present` (BooleanField default `False`); migration.
- [ ] 2.2 Implement `Challenge.team_satisfies_roles(team)` returning `(ok, missing_role_slugs)`: `NONE` → always ok; `ANY` → true if the team's active role holders cover at least one `required_role`; `ALL` → true only if they cover every `required_role`. Count distinct roles covered, never member head-count.
- [ ] 2.3 Validation: `required_roles` must belong to the challenge's Game; a non-`NONE` mode with an empty `required_roles` is rejected.

## 3. Built-in INVITER power

- [ ] 3.1 Add a helper `UserProfile.can_invite_to(team)` → true if staff, or the user's active `TeamMembership` in that team holds a role with `builtin_power=INVITER`.
- [ ] 3.2 Authorize invite creation for `INVITER` holders on their own team, extending the existing staff-only path (coordinate with the `team-invites` / `team-formation` capabilities); non-holders and non-staff still denied.

## 4. Enforcement at submission

- [ ] 4.1 In the `TeamTowerChallenge` create path, after deriving the submitting team, call `challenge.team_satisfies_roles(team)`; on failure refuse the submission (HTTP 400) with a reason naming the missing roles. Ordering relative to proximity/cooldown checks documented.
- [ ] 4.2 When `require_holders_present` is `True`, defer the "holder present" test to the `presence-rules` capability if available; otherwise treat assignment as sufficient (default path).

## 5. APIs

- [ ] 5.1 `GET/POST/PATCH/DELETE /api/staff/game_roles/` scoped to a Game (creator/runner authoring); expose `builtin_power`.
- [ ] 5.2 Role assign/unassign actions on a team membership (staff/runner), filtering selectable roles to the membership's Game.
- [ ] 5.3 Expose `role_requirement_mode` + `required_roles` (read/write for staff) on challenge endpoints; expose each member's roles on `GET /api/teams/`.
- [ ] 5.4 On the player challenge surface, expose the challenge's role requirement and a `team_satisfies` boolean for the caller's team.

## 6. Frontend

- [ ] 6.1 Staff: per-Game role editor (name, slug, description, built-in power) and roster role assignment UI.
- [ ] 6.2 Staff: challenge editor gains a role-requirement section (mode + role picker + `require_holders_present`).
- [ ] 6.3 Player: show own roles; on a challenge show its role requirement and whether the team currently satisfies it; show an "invite" affordance to `INVITER` holders.

## 7. Cloning

- [ ] 7.1 Extend the Game-clone routine (see the `game-authoring-roles` capability) to deep-copy `GameRole`s and remap each cloned challenge's `required_roles` to the cloned roles.

## 8. Tests

- [ ] 8.1 `GameRole`/`TeamRole` model tests: unique `(game, slug)`, unique `(membership, role)`, and rejection of a `TeamRole` whose role's Game differs from the membership's Game.
- [ ] 8.2 `team_satisfies_roles` tests: `NONE` always passes; `ANY` passes on one covered role; `ALL` fails until every role is covered; **one member holding two required roles satisfies `ALL`**; ten members holding none fail.
- [ ] 8.3 Submission enforcement: a team missing a required role is refused with the missing roles named; the same team passes after assignment; default (`NONE`) path unchanged.
- [ ] 8.4 INVITER power: a member holding an `INVITER` role may create an invite for their own team; a non-holder non-staff member cannot; staff still can; no `INVITER` role defined ⇒ invite creation stays staff-only.
- [ ] 8.5 Backward compatibility: a Game with no roles and all challenges at `role_requirement_mode=NONE` yields identical submission, invite, and teams-API behavior to before the change.
- [ ] 8.6 Clone test: cloning a Game copies its `GameRole`s and rewires cloned challenges' `required_roles` to the cloned roles (no reference to the original's roles).
- [ ] 8.7 Ruff-clean; branch coverage ≥ 80% for the new code.
