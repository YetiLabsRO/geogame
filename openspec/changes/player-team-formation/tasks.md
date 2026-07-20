## 1. Per-game toggle & effective-value resolution

- [ ] 1.1 Add `Game.allow_player_team_creation` (`BooleanField`, default `False`) and nullable `Session.allow_player_team_creation` override; migration.
- [ ] 1.2 Add `Game.team_join_confirmation` (choices `AUTO_APPROVE`/`CAPTAIN`/`STAFF`) and nullable `Team.team_join_confirmation` override; migration.
- [ ] 1.3 Add `effective_allow_player_team_creation(session)` and `effective_team_join_confirmation(team)` helpers (Session/Team override wins, else Game default), mirroring the `proximity_meters` pattern.
- [ ] 1.4 Expose both effective values (read-only) on the session/game config serializers consumed by `GET /api/me/` and the current-session payload.

## 2. Player-created teams & captain

- [ ] 2.1 Add `Team.captain` FK (creating user) or `TeamMembership.is_captain`; set it when a player creates a team.
- [ ] 2.2 `POST /api/teams/` player create: allowed only when the effective toggle is on; creator becomes captain + first member; enforces one-active-membership-per-`(user, game)`.
- [ ] 2.3 Keep admin/staff team creation working unconditionally (independent of the toggle) via the existing staff path.
- [ ] 2.4 Permission class: a player may create at most one team per Session and only within their current Session's Game.

## 3. Untied QR / join code vs recipient-bound link

- [ ] 3.1 Add an untied, rotatable join code/token to `Team` (or an untied `team-invites` token) with a `POST /api/teams/{id}/join-code/` rotate/revoke endpoint (captain or staff).
- [ ] 3.2 Extend the `team-invites` token model with `kind` (`QR`/`LINK`) and an optional bound recipient email; migration (default existing rows to `QR`, email-targeted → `LINK`).
- [ ] 3.3 Enforce binding at acceptance: `QR` accepted by anyone while valid; `LINK` accepted only when the account email matches the bound recipient, else `403`.

## 4. Join requests (pending / approved / rejected)

- [ ] 4.1 Add `organize.TeamJoinRequest` (`team`, `user`, `status`, `source` `BROWSE`/`QR`/`LINK`, `requested_at`, `decided_by`, `decided_at`, `note`); migration + admin.
- [ ] 4.2 `GET /api/joinable-teams/`: list teams in the caller's current Session that a player may request to join.
- [ ] 4.3 `POST /api/join-requests/`: create a `pending` request (or, when the effective confirmation is `AUTO_APPROVE`, create the membership immediately).
- [ ] 4.4 `POST /api/join-requests/{id}/approve/` and `.../reject/`: captain-of-that-team or staff only; approval creates the `TeamMembership`, rejection closes the request; both stamp `decided_by`/`decided_at`.
- [ ] 4.5 `GET /api/join-requests/`: a captain sees their team's requests, staff see managed teams', a player sees their own — filterable by status.

## 5. Confirmation-policy routing

- [ ] 5.1 Route QR/LINK invite acceptance and browse requests through the effective confirmation policy: `AUTO_APPROVE` → membership; `CAPTAIN`/`STAFF` → `pending` `TeamJoinRequest`.
- [ ] 5.2 Surface a clear error when approval/acceptance would violate the one-active-membership-per-game constraint.

## 6. `team-invites` modifications

- [ ] 6.1 Allow a team captain/inviter (not only staff) to `POST /api/invites/`, list, revoke, and resend invites for their own team when the toggle is on.
- [ ] 6.2 Add `kind` to the create payload and to `GET /api/invites/{token}/` preview output; indicate recipient-bound restriction in the preview.
- [ ] 6.3 Replace the unconditional "team creation is staff-only" check with a per-Game-toggle gate (players allowed when enabled; staff always allowed).

## 7. Admin shuffle / balanced-team building (lower priority)

- [ ] 7.1 Optional key-value profile attributes on `UserProfile` (JSON) for balancing inputs.
- [ ] 7.2 `POST /api/staff/sessions/{id}/shuffle-teams/`: randomly distribute unassigned players into N teams (best-effort, result editable before start).
- [ ] 7.3 `POST /api/staff/sessions/{id}/balance-teams/`: bucket unassigned players by chosen attribute key(s) and distribute round-robin to equalise across N teams.

## 8. Frontend (player app + staff)

- [ ] 8.1 Player: create-team screen (name + optional TeamGroup) shown only when the effective toggle is on — standalone, signals, `OnPush`.
- [ ] 8.2 Player: share screen with the team QR image and a copyable untied join link, plus rotate/revoke for the captain.
- [ ] 8.3 Player: browse joinable teams and request to join; show the player's own request status.
- [ ] 8.4 Captain: pending-request list with approve/reject actions.
- [ ] 8.5 Staff: per-Game / per-Session toggle + confirmation-policy controls, and the shuffle/balance action.

## 9. Tests

- [ ] 9.1 Toggle resolution: default `False` keeps team creation staff-only; per-Session override wins; admins can always create teams.
- [ ] 9.2 Player create-team: succeeds when enabled, `403` when disabled, and honours one-active-membership-per-game.
- [ ] 9.3 Untied QR accepted by any account; recipient-bound `LINK` accepted only by the bound recipient, `403` for a forwarded/mismatched account.
- [ ] 9.4 Join-request lifecycle: `pending` → `approved` creates membership; `pending` → `rejected` does not; `AUTO_APPROVE` short-circuits to membership.
- [ ] 9.5 Confirmation policy: a QR join under a `CAPTAIN`/`STAFF` team yields a pending request, not an immediate membership.
- [ ] 9.6 Scope isolation: a captain cannot manage another team's invites or approve another team's join requests; staff can.
- [ ] 9.7 Admin shuffle/balance: shuffle distributes all unassigned players; balance buckets by an attribute key without leaving a team empty when inputs allow.
- [ ] 9.8 Coverage stays ≥80% branch and `ruff check .` is clean (single quotes).
