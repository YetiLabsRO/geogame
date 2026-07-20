## Context

Teams today are flat: `organize.Team` has `members` (an M2M through `organize.TeamMembership`) and no notion of who does what inside the team. The word "role" in the shipped system means a staff/admin permission (creator vs runner, `is_staff`), never an in-game function. The product wants roles to be a **gameplay mechanic**: a creator defines an arbitrary set of roles per Game, assigns them to members, some roles carry known powers (an `INVITER` who can pull new players in), and the rule engine can require roles to be present as a gate on challenges and towers — where "present" is about the team holding the role, not about how many bodies are on the ground.

This sits on top of the reconciled model: `organize.Game` is the creator-authored **template** (owns rules, the challenge bank, the TeamGroup taxonomy, and now the role taxonomy); `organize.Session` is the **run**. Roles are defined on the Game (template) so they clone with it, and assigned per `TeamMembership` so they live on the concrete roster of a run.

## Goals / Non-Goals

**Goals:**
- An arbitrary, creator-defined set of roles per Game, some with optional built-in powers.
- Roles assignable to individual team members; a member MAY hold several, a role MAY be held by several members.
- The rule mechanism can require roles: a specific role present, or one-of-each of several roles, on a challenge — independent of head-count.
- A first concrete built-in power, `INVITER`, that lets its holder invite others into the team.
- Strict backward compatibility: no roles defined and no requirement set ⇒ identical behavior to today.

**Non-Goals:**
- Presence/geofencing verification of role holders (who is physically where) — that is the `presence-rules` capability. This change gates on role **assignment**; it only exposes an optional `require_holders_present` hook that defers the "present" test to that capability when enabled.
- Player-driven team formation and the QR/invite-link distinction — that is `team-formation`/`team-invites`. This change only grants the `INVITER` power the right to create an invite; it does not redesign the invite flow.
- Tower-level (as opposed to challenge-level) role requirements as a distinct model — a tower's requirement is expressed through its challenges' requirements; a dedicated tower-scoped requirement can be a later refinement.
- Staff/admin RBAC — unchanged; `GameRole` is an in-game concept, not a Django permission.

## Decisions

- **`GameRole` lives in `organize`, scoped to the Game (template), unique on `(game, slug)`.** It mirrors `TeamGroup`'s shape (per-Game, named, slugged) so the authoring surface and cloning behave consistently. Alternative considered: a global role catalog reused across Games — rejected because role vocabularies are game-specific and a global list would force awkward namespacing.
- **Built-in power as an enum flag on `GameRole` (`builtin_power`, default `NONE`).** Most roles are arbitrary flavor with no engine behavior; a few opt into a known power. Starting set: `NONE`, `INVITER`. New powers are added as new enum values, not new models. Alternative considered: a boolean per power (`can_invite`, …) — rejected because it does not scale and conflates orthogonal powers; a single enum keeps "this role's special power" one field. A role MAY still be required by the rules regardless of its power (an arbitrary `NAVIGATOR` with `builtin_power=NONE` can gate a challenge).
- **Assignment attaches to `TeamMembership`, not to `Team` or `UserProfile`.** `TeamRole(membership, role)` means "this member, in this team, in this run, holds this role." It travels with the roster, respects the per-run membership lifecycle (`is_active`, `left_at`), and cannot leak across Sessions. A `TeamRole`'s `role.game` MUST equal `membership.game` (validated on save). Unique `(membership, role)`.
- **Role requirement is authored on `Challenge` (template-owned), three modes.** `role_requirement_mode`: `NONE` (default, no gate), `ALL` (the team must have, among its active members, at least one holder for **each** role in `required_roles` — "one of each"), `ANY` (at least one of the `required_roles` is held by some active member — covers "a specific role present" when the set is a singleton). Alternative considered: a free-form boolean expression over roles — rejected as over-engineered for the stated need (specific-role / one-of-each).
- **Head-count independence is explicit.** The evaluation counts distinct roles covered by the team's active role holders, never the number of members. One member holding two required roles satisfies an `ALL` requirement over those two roles by themselves; ten members holding none fail. This is the crux of "independent of how many people are physically there."
- **`INVITER` extends, not replaces, staff invite creation.** A player whose active membership holds a role with `builtin_power=INVITER` MAY call the invite-creation endpoint for their own team; staff retain their existing power. Without any `INVITER` role defined/assigned, invite creation stays staff-only exactly as today. This is the coordination point with `team-invites` / `team-formation`.
- **Optional holder-presence hook, default off.** `Challenge.require_holders_present` (default `False`) records the creator's intent that the required role's holder must additionally be present; the actual presence test is delegated to the `presence-rules` capability. Default `False` keeps this change's enforcement purely about assignment.

## Risks / Trade-offs

- [Role requirement could silently block a legitimate team mid-game if a role holder leaves] → the submission rejection SHALL state which roles are missing so staff/players can reassign; role assignment is a cheap staff action; requirement modes are opt-in per challenge.
- [Cross-app M2M from `game.Challenge` to `organize.GameRole` couples the two apps] → the apps already reference each other (`Challenge.game` → `organize.Game`); the M2M follows the same direction and adds no cycle.
- [A `TeamRole` could reference a `GameRole` from a different Game than the membership] → enforce `role.game_id == membership.game_id` in `TeamRole.save()`/clean and cover with a test; the assignment API filters selectable roles to the membership's Game.
- [Cloning a Game must carry its roles and challenge role requirements] → clone deep-copies `GameRole`s and remaps each cloned `Challenge`'s `required_roles` to the cloned roles (extends the clone routine from the `game-authoring-roles` capability); covered by a clone test.
- [Built-in powers growing into a grab-bag] → keep `builtin_power` a small, documented enum; anything that is pure flavor stays `NONE` and is used only via rule requirements.

## Migration Plan

1. Add `organize.GameRole` and `organize.TeamRole` tables (additive).
2. Add to `game.Challenge`: `role_requirement_mode` (default `NONE`), `required_roles` (M2M to `GameRole`, blank), `require_holders_present` (default `False`). All defaulted, so existing rows require no backfill.
3. No data migration: with zero roles defined and every challenge at `role_requirement_mode=NONE`, submission, invites, and the teams API behave identically to before this change.
4. Extend the Game-clone routine (see the `game-authoring-roles` capability) to copy `GameRole`s and remap cloned challenges' `required_roles`.
