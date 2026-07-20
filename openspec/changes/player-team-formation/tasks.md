## 1. Per-game toggle & effective-value resolution

- [x] 1.1 Add `Game.allow_player_team_creation` (`BooleanField`, default `False`) and nullable `Session.allow_player_team_creation` override; migration.
- [x] 1.2 Add `Game.team_join_confirmation` (choices `AUTO_APPROVE`/`CAPTAIN`/`STAFF`) and nullable `Team.team_join_confirmation` override; migration.
- [x] 1.3 Add `effective_allow_player_team_creation(session)` and `effective_team_join_confirmation(team)` helpers (Session/Team override wins, else Game default), mirroring the `proximity_meters` pattern.
- [x] 1.4 Expose both effective values (read-only) on the session/game config serializers consumed by `GET /api/me/` and the current-session payload.

## 2. Player-created teams & captain

- [x] 2.1 Add `Team.captain` FK (creating user) or `TeamMembership.is_captain`; set it when a player creates a team.
- [x] 2.2 `POST /api/teams/` player create: allowed only when the effective toggle is on; creator becomes captain + first member; enforces one-active-membership-per-`(user, game)`.
- [x] 2.3 Keep admin/staff team creation working unconditionally (independent of the toggle) via the existing staff path.
- [x] 2.4 Permission class: a player may create at most one team per Session and only within their current Session's Game.

## 3. Untied QR / join code vs recipient-bound link

- [x] 3.1 Add an untied, rotatable join code/token to `Team` (or an untied `team-invites` token) with a `POST /api/teams/{id}/join-code/` rotate/revoke endpoint (captain or staff).
- [x] 3.2 Extend the `team-invites` token model with `kind` (`QR`/`LINK`) and an optional bound recipient email; migration (default existing rows to `QR`, email-targeted → `LINK`).
- [x] 3.3 Enforce binding at acceptance: `QR` accepted by anyone while valid; `LINK` accepted only when the account email matches the bound recipient, else `403`.

## 4. Join requests (pending / approved / rejected)

- [x] 4.1 Add `organize.TeamJoinRequest` (`team`, `user`, `status`, `source` `BROWSE`/`QR`/`LINK`, `requested_at`, `decided_by`, `decided_at`, `note`); migration + admin.
- [x] 4.2 `GET /api/joinable-teams/`: list teams in the caller's current Session that a player may request to join.
- [x] 4.3 `POST /api/join-requests/`: create a `pending` request (or, when the effective confirmation is `AUTO_APPROVE`, create the membership immediately).
- [x] 4.4 `POST /api/join-requests/{id}/approve/` and `.../reject/`: captain-of-that-team or staff only; approval creates the `TeamMembership`, rejection closes the request; both stamp `decided_by`/`decided_at`.
- [x] 4.5 `GET /api/join-requests/`: a captain sees their team's requests, staff see managed teams', a player sees their own — filterable by status.

## 5. Confirmation-policy routing

- [x] 5.1 Route QR/LINK invite acceptance and browse requests through the effective confirmation policy: `AUTO_APPROVE` → membership; `CAPTAIN`/`STAFF` → `pending` `TeamJoinRequest`.
- [x] 5.2 Surface a clear error when approval/acceptance would violate the one-active-membership-per-game constraint.

## 6. `team-invites` modifications

- [x] 6.1 Allow a team captain/inviter (not only staff) to `POST /api/invites/`, list, revoke, and resend invites for their own team when the toggle is on.
- [x] 6.2 Add `kind` to the create payload and to `GET /api/invites/{token}/` preview output; indicate recipient-bound restriction in the preview.
- [x] 6.3 Replace the unconditional "team creation is staff-only" check with a per-Game-toggle gate (players allowed when enabled; staff always allowed).

## 7. Admin shuffle / balanced-team building (lower priority)

- [x] 7.1 Optional key-value profile attributes on `UserProfile` (JSON) for balancing inputs.
- [x] 7.2 `POST /api/staff/sessions/{id}/shuffle-teams/`: randomly distribute unassigned players into N teams (best-effort, result editable before start).
- [x] 7.3 `POST /api/staff/sessions/{id}/balance-teams/`: bucket unassigned players by chosen attribute key(s) and distribute round-robin to equalise across N teams.

## 8. Frontend (player app + staff)

- [x] 8.1 Player: create-team screen (name + optional TeamGroup) shown only when the effective toggle is on — standalone, signals, `OnPush`.
- [x] 8.2 Player: share screen with the team QR image and a copyable untied join link, plus rotate/revoke for the captain.
- [x] 8.3 Player: browse joinable teams and request to join; show the player's own request status.
- [x] 8.4 Captain: pending-request list with approve/reject actions.
- [x] 8.5 Staff: per-Game / per-Session toggle + confirmation-policy controls, and the shuffle/balance action.

## 9. Tests

- [x] 9.1 Toggle resolution: default `False` keeps team creation staff-only; per-Session override wins; admins can always create teams.
- [x] 9.2 Player create-team: succeeds when enabled, `403` when disabled, and honours one-active-membership-per-game.
- [x] 9.3 Untied QR accepted by any account; recipient-bound `LINK` accepted only by the bound recipient, `403` for a forwarded/mismatched account.
- [x] 9.4 Join-request lifecycle: `pending` → `approved` creates membership; `pending` → `rejected` does not; `AUTO_APPROVE` short-circuits to membership.
- [x] 9.5 Confirmation policy: a QR join under a `CAPTAIN`/`STAFF` team yields a pending request, not an immediate membership.
- [x] 9.6 Scope isolation: a captain cannot manage another team's invites or approve another team's join requests; staff can.
- [x] 9.7 Admin shuffle/balance: shuffle distributes all unassigned players; balance buckets by an attribute key without leaving a team empty when inputs allow.
- [x] 9.8 Coverage stays ≥80% branch and `ruff check .` is clean (single quotes).

## Implementation notes

Implemented 2026-07-21 on branch `impl/player-team-formation`. All 37 tasks done;
280 tests green (208 baseline + 72 new), `ruff check .` clean, both Angular apps
build (`ng build player|staff --configuration development`).

**Interpretations / deviations from design.md (all backward compatible — every
default preserves staff-only behaviour):**

- `Game.team_join_confirmation` defaults to `AUTO_APPROVE` (the design offered
  `AUTO_APPROVE` or `STAFF`). `AUTO_APPROVE` is the value that preserves current
  behaviour: existing invite acceptance keeps creating the membership
  immediately, so the baseline invite tests stay green.
- The untied join code lives on `Team.join_code` (nullable unique UUID) rather
  than as an untied `Invite` row: the team QR must be *multi-use* (a whole
  friend group joins with one code) while `Invite` is single-use by design.
  `Invite.kind` (`QR`/`LINK`) still exists per the design for single-use
  invites: `QR` = untied (anyone may accept once), `LINK` = recipient-bound.
- Invite `kind` defaults to `QR` for *new* rows even when an email is provided
  (binding is opt-in via `kind: 'LINK'`); the data migration backfills
  *existing* email-targeted invites to `LINK` per the design's migration plan.
- Browse endpoints (`GET /api/joinable-teams/`, BROWSE-source
  `POST /api/join-requests/`) are gated by the same effective
  `allow_player_team_creation` toggle ("everything must be opt-in per Game").
  QR-code joins and invite accepts are not toggle-gated — the code/invite only
  exists because a captain/staff deliberately issued it, and codes are
  revocable.
- `CurrentSessionView` (POST + validity check) now lets a **teamless** player
  select/keep an active session whose effective toggle is on ("open session").
  Without this, a walk-up player could never reach the create/browse screens
  (current-session previously required a membership). Toggle off → exact old
  behaviour.
- Extra convenience endpoint (not in the delta spec):
  `GET /api/join-codes/{code}/` (AllowAny) — public preview of a team join
  code so the player app's `/join/:code` screen can render team info before
  login. Harmless read-only surface; can be folded into the spec at archive.
- Approve-when-policy-is-STAFF: the spec's scenario lets "the team captain or a
  staff user" decide, so captains may decide requests even when the policy is
  `STAFF` (the policy controls *whether* confirmation is needed, not *who*).
- Shuffle/balance pool = non-staff `UserProfile`s with `current_session` set to
  the session and no active membership in its game (players enter the pool via
  the open-session flow). Builders create fresh `Team N` teams; result editable
  on the staff Teams page. Balance deals bucket-by-bucket (largest first) with
  one continuing round-robin cursor.
- Wireframe frontend: joining via `/join/:code` requires signing in/registering
  first (links provided); anonymous signup-inside-join-screen only exists for
  the pre-existing invite-accept flow.

**Seam for `team-roles-as-mechanics` (parallel branch):** invite-creation
rights are centralised in `_can_manage_team_invites(user, team)` and
join-request decisions in `_can_decide_join_request(user, team)`
(`organize/api.py`). A role-based INVITER power should plug into those two
helpers at merge; no role models were implemented here.

**Migrations (numbering conflicts with parallel branches expected; merger
renumbers):** `organize/0011_player_team_formation` (schema),
`organize/0012_backfill_invite_kind` (data). The dev database was NOT migrated
(shared with parallel agents); only the isolated test DB ran them.

**Expected merge-conflict hotspots:** `organize/models.py` (new fields +
`TeamJoinRequest` + `OVERRIDABLE_CONFIG_FIELDS` tuple), `organize/api.py`
(invite views rewritten for captain scope; new team-formation section),
`organize/urls.py`, `organize/admin.py`, `game/views.py` (`TeamViewSet.create`
override), `game/admin_api.py` (Admin serializers + session shuffle/balance
actions), `game/serializers.py` (`TeamSerializer.color` optional),
`organize/tests.py` (large append), frontend `shared` lib
(`staff-api.service.ts`, `auth.service.ts`, `game-api.service.ts`,
`invites.service.ts`, `public-api.ts`), player/staff `app.routes.ts` +
`app.html`.
