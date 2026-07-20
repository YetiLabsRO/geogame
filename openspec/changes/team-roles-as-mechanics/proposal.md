## Why

Today a Team is a flat bag of members: everyone inside a team is interchangeable, and the only "roles" in the system are staff/admin permissions outside of gameplay. The product direction is that **roles inside a team are part of the game**. A creator wants to define an arbitrary set of per-Game roles (COOK, NAVIGATOR, MEDIC, INVITER, …), hand them out to members, give some of them known built-in powers (e.g. an INVITER who can bring new players into the team), and — crucially — let the **rules use them**: a challenge or tower may require a specific role to be present, or one-of-each of several roles, independent of how many people are physically standing there. This change adds per-Game role definitions, role assignment on the roster, and role-requirement gating on challenges, all opt-in so that a Game defining no roles behaves exactly as today.

## What Changes

- Introduce `organize.GameRole`: a per-Game role definition (`name`, URL-safe `slug`, optional `description`, unique per Game) with an optional **built-in power** flag. The first built-in power is `INVITER` (its holder MAY invite others into the team); other roles are arbitrary and carry no built-in power.
- Introduce `organize.TeamRole`: a role assignment attached to a `TeamMembership`, so a specific member of a specific team holds zero or more of that Game's roles. A role MAY be held by several members and a member MAY hold several roles.
- Add **role-requirement config on challenges** (`game.Challenge`): a `role_requirement_mode` of `NONE` (default) / `ALL` / `ANY` plus a `required_roles` set of `GameRole`s, so a Challenge can require a specific role present or one-of-each of several roles. Evaluation is against the submitting team's active role holders and is **independent of head-count**.
- Wire the `INVITER` built-in power into invite creation: a player holding an `INVITER` role MAY create invites for their own team, extending the current staff-only invite path (coordinate with the `team-invites` and forthcoming `team-formation` capabilities).
- Enforce role requirements at challenge submission: a submission is refused when the submitting team does not satisfy the challenge's role requirement, with a clear reason.
- Staff/creator API + admin to define roles per Game, assign roles to members, and set role requirements on challenges; player app surfaces a member's roles, a challenge's role requirement, and whether the team currently satisfies it.
- Fully backward compatible: a Game that defines no roles and sets no challenge role requirement (the default) has **no behavior change**.

## Capabilities

### New Capabilities
- `team-roles`: arbitrary per-Game role definitions with optional built-in powers, role assignment on the roster, and roles usable as challenge/tower requirements independent of head-count.

### Modified Capabilities
- `teams-and-groups`: a `TeamMembership` MAY hold one or more of its Game's roles; the teams API exposes each member's roles.
- `challenge-submission`: a submission is additionally gated by the challenge's role requirement (default: no requirement, unchanged).

## Impact

- **Models**: new `organize.GameRole` (`game` FK, `name`, `slug`, `description`, `builtin_power`; unique `(game, slug)`); new `organize.TeamRole` (`membership` FK, `role` FK, `assigned_by`, `assigned_at`; unique `(membership, role)`); add to `game.Challenge` a `role_requirement_mode` enum (default `NONE`), a `required_roles` M2M to `GameRole`, and a `require_holders_present` flag (default `False`).
- **APIs**: new `/api/staff/game_roles/` (per-Game role CRUD); role assign/unassign actions on team memberships; `required_roles` + `role_requirement_mode` exposed on challenge endpoints; each member's roles exposed on `GET /api/teams/`; player-facing "team satisfies requirement?" hint on the challenge surface; invite creation authorized for holders of an `INVITER` role.
- **Frontend**: staff role editor per Game, roster role assignment, challenge role-requirement editor; player view of own roles, challenge role requirements, and an invite affordance for `INVITER` holders.
- **Migrations/other**: additive schema migration only (new tables + three nullable/defaulted `Challenge` fields); no data backfill — defaults preserve current behavior.
