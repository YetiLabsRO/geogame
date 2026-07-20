## Why

Today team creation is staff-only: an administrator must build every roster and invite each scout by hand (see the `team-invites` capability). For open, walk-up events the organiser wants players to form their own teams — one player creates a team and shares it with friends, others browse the teams already forming and ask to join, and a captain or the staff waves people in. The existing invite machinery only issues a QR image of a single-use URL, with no way to tie a link to one recipient so it cannot be forwarded, and no concept of a "request to join" that waits for confirmation. This change adds a player-facing team-formation module, gated by a per-Game toggle so existing staff-run events are unchanged.

## What Changes

- Add a **per-Game toggle** `allow_player_team_creation` (default `False`, preserving today's staff-only behaviour) with a **nullable per-Session override**, resolved by an effective-value helper (Session override wins, else Game default). Administrators can always create teams regardless of the toggle.
- Let a player **create a team** in their current Session when the effective toggle is on; the creator becomes the team **captain** (first member), picks a name and optionally a TeamGroup, and stays subject to the one-active-membership-per-Game rule (see the `sessions` capability).
- Let a captain **share their team** via an **untied QR / join code** (not bound to any user — anyone holding it may join while valid) that can be rotated or revoked, distinct from a **recipient-bound invitation link** (bound to one email so it cannot be forwarded — see the modified `team-invites` capability).
- Let a player **browse joinable teams** in their Session and **request to join**; add `organize.TeamJoinRequest` records with `pending` / `approved` / `rejected` states and the request source (`BROWSE` / `QR` / `LINK`).
- Add a **confirmation policy** (per-Game default with per-Team override): a join request or QR join MAY require approval by the team captain / an authorised inviter or by staff, or MAY auto-approve. Approval creates the `TeamMembership`; rejection closes the request.
- Modify `team-invites` so a captain/inviter (not only staff) can create and manage invites when the toggle is on, and so invites carry a **kind** (untied `QR` vs recipient-bound `LINK`) enforced at acceptance.
- Add a lower-priority **admin alternative**: staff may auto-assign unassigned players into teams by **random shuffle** into N teams, or **balanced build** from arbitrary key-value profile attributes (spec'd lightly).
- Player-app UI (Angular, standalone / signals / `OnPush`) for create-team, share-QR, browse-and-request, and captain approval of pending requests.

## Capabilities

### New Capabilities
- `team-formation`: player-driven team creation gated by a per-Game toggle, shareable untied team QR/join codes, browse-and-request-to-join with `pending`/`approved`/`rejected` join requests and a confirmation policy, plus an admin shuffle/balanced-build alternative.

### Modified Capabilities
- `team-invites`: invites may be created and managed by a team captain/inviter (not only staff) when player-driven team formation is enabled; invites gain a **kind** (untied `QR` that anyone may accept vs recipient-bound `LINK` that only its named recipient may accept, non-forwardable); acceptance MAY route through a pending join request when the team requires confirmation; team creation is gated by the per-Game toggle instead of being unconditionally staff-only.

## Impact

- **Models**: add `Game.allow_player_team_creation` (default `False`) and nullable `Session.allow_player_team_creation` override; add per-Game `team_join_confirmation` default and nullable per-Team override; add `organize.TeamJoinRequest` (`team`, `user`, `status`, `source`, `requested_at`, `decided_by`, `decided_at`, `note`); add a `Team.captain` (FK to the creating user) or captain flag on `TeamMembership`; add an untied join-code/token on `Team` (or reuse an untied `team-invites` token); extend the invite model with a `kind` (`QR`/`LINK`) and a bound-recipient constraint. Optional lightweight `UserProfile` key-value profile attributes (JSON) for balanced builds.
- **APIs**: `POST /api/teams/` (player create), `GET /api/joinable-teams/`, `POST /api/join-requests/`, `GET /api/join-requests/`, `POST /api/join-requests/{id}/approve/`, `POST /api/join-requests/{id}/reject/`, `POST /api/teams/{id}/join-code/` (rotate/revoke); staff `POST /api/staff/sessions/{id}/shuffle-teams/` and `.../balance-teams/`. Modified `team-invites` endpoints gain the `kind` field and captain-scoped access.
- **Frontend**: player module — create team, share QR/link, browse & request to join, captain request-management; staff gains the shuffle/balance action and the per-Game/per-Session toggle controls.
- **Migrations/other**: additive migrations for the new fields and `TeamJoinRequest`; all new knobs default to preserve current staff-only behaviour (backward compatible, opt-in).
