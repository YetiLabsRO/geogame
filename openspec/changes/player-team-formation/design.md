## Context

The shipped roster model is entirely staff-driven: an administrator creates each `organize.Team` and issues single-use invites, and the `team-invites` capability explicitly denies team creation to non-staff. That is correct for closed, organiser-run events but blocks the open, walk-up scouting game where participants self-organise on the spot. The product wants three player flows on top of the existing account/membership machinery: (a) create a team and share it so friends join, (b) browse the teams already forming and ask to join, and (c) accept a secret invite. Two subtle requirements drive the design: a shared **QR** must be forwardable to a whole friend group (not bound to one person), whereas a personal **invitation link** must be bound to its recipient so it cannot be passed on; and joining must be able to wait for **confirmation** by a captain or staff. Everything must be opt-in per Game so existing events behave exactly as before.

## Goals / Non-Goals

**Goals:**
- Players can create their own teams when the organiser allows it, without ever weakening staff control (admins can always create teams; the default is unchanged staff-only).
- A per-Game toggle with a nullable per-Session override controls player-driven creation, following the established effective-value pattern (Session override wins, else Game default).
- A clean distinction between an **untied QR/join code** (shareable, anyone may use it) and a **recipient-bound invitation link** (non-forwardable).
- First-class **join requests** with `pending` / `approved` / `rejected` states and a configurable confirmation policy (captain/inviter or staff approves, or auto-approve).
- Reuse and extend `team-invites` rather than forking a parallel token system.
- A lightweight admin alternative to shuffle / balance people into teams.

**Non-Goals:**
- Team size limits and start-gating on min/max members — owned by the `game-config-team-rules` change; this change references those thresholds but does not define them.
- Rich role powers (an INVITER role, role-gated actions) — owned by the `team-roles-as-mechanics` change; here "captain" is just the creator with request-management rights.
- Real-time push of new join requests to a captain's device — owned by `realtime-and-notifications`; polling is acceptable here.
- A full profile-attribute schema; balanced builds read arbitrary key-value attributes best-effort and are spec'd lightly.

## Decisions

- **Per-Game toggle + nullable per-Session override.** `Game.allow_player_team_creation` defaults to `False` (today's behaviour); `Session.allow_player_team_creation` is nullable and, when set, wins. Resolved by an `effective_allow_player_team_creation(session)` helper mirroring `proximity_meters` and the pause/failure knobs. Alternative considered: a single Game-level flag with no per-run override — rejected because a creator's template may allow self-forming while a specific run wants a fixed roster (or vice-versa).
- **Invite `kind`: untied `QR` vs recipient-bound `LINK`.** Extend the existing `team-invites` token with a `kind` and an optional bound recipient. A `QR` token has no bound user and any holder may accept it while valid; a `LINK` token is bound to a recipient email and acceptance requires the accepting account's email to match, returning `403` on mismatch so a forwarded link is useless. Alternative considered: two separate models — rejected because preview/accept/expiry/single-use machinery is identical; a discriminator field is simpler and keeps one accept endpoint.
- **`TeamJoinRequest` is a distinct model, not a reused invite.** A request is initiated by the *joiner* (browse-and-ask or a QR scan under a confirming team), carries `status` (`pending`/`approved`/`rejected`), `source` (`BROWSE`/`QR`/`LINK`), and audit fields (`requested_at`, `decided_by`, `decided_at`). Invites are initiated by the *team*; conflating them would overload one model with two opposite directions of intent. A QR/LINK acceptance under a confirming team *creates* a `TeamJoinRequest` rather than a membership.
- **Confirmation policy = per-Game default with per-Team override.** `Game.team_join_confirmation` (e.g. `AUTO_APPROVE` / `CAPTAIN` / `STAFF`) with a nullable `Team.team_join_confirmation` override. `AUTO_APPROVE` turns a request straight into membership; `CAPTAIN`/`STAFF` leave it `pending` until an authorised user approves. This lets an open event auto-join while a semi-managed event still gatekeeps.
- **Captain = the creating user.** Recorded on the team (a `captain` FK, or a `is_captain` flag on the creator's `TeamMembership`). The captain may create/manage that team's invites, rotate/revoke its join code, and approve/reject its join requests. Staff can do all of this for any team. Richer role mechanics are deferred to `team-roles-as-mechanics`.
- **Reuse existing membership invariants.** Creating a team, approving a request, and accepting an invite all funnel through the same `TeamMembership` creation path, so the one-active-membership-per-`(user, game)` constraint (see the `sessions` capability) is enforced uniformly and surfaces a clear error.
- **Admin shuffle/balance reads arbitrary key-value profile attributes.** Balanced builds bucket unassigned players by one or more attribute keys (stored as JSON on `UserProfile`) and distribute round-robin to equalise the buckets across N teams; random shuffle ignores attributes. Spec'd lightly and best-effort — no guaranteed optimality.

## Risks / Trade-offs

- [A shared QR could let unlimited strangers flood a team] → the confirmation policy (`CAPTAIN`/`STAFF`) gates QR joins behind approval, and the join code is rotatable/revocable; size caps come from `game-config-team-rules`.
- [A recipient-bound link is only as strong as the email match, and a user could register the bound email] → binding is enforced at acceptance against the authenticated (or freshly-registered) account's verified email; this raises the bar versus a plain forwardable URL without claiming perfect anti-forwarding.
- [Two invite kinds plus join requests plus a toggle add surface area and states] → all default to preserve staff-only behaviour, the accept endpoint stays single, and states are covered by explicit transition tests.
- [Balanced-team building over free-form attributes can produce lopsided or empty buckets] → it is an admin convenience, explicitly best-effort, and the result is editable before the Session starts.
- [Captains gaining invite-management rights could leak across teams] → captain rights are strictly scoped to their own team; staff scope is unchanged. A test asserts a captain cannot manage another team's invites or requests.

## Migration Plan

1. Additive migration: add `Game.allow_player_team_creation` (default `False`), nullable `Session.allow_player_team_creation`, `Game.team_join_confirmation` (default `AUTO_APPROVE` or `STAFF` — chosen to preserve staff-gated joins), nullable `Team.team_join_confirmation`, and a `Team` captain FK / join-code field.
2. Additive migration: create `organize.TeamJoinRequest`; extend the `team-invites` token model with `kind` (default `QR` for existing rows, matching today's shareable QR image) and an optional bound recipient (existing email-targeted invites become `LINK` where an email was set, else `QR`).
3. No data backfill changes runtime behaviour: with `allow_player_team_creation=False` everywhere, only staff can create teams exactly as today, and existing invites keep working.
4. Wire the effective-value helpers and route team-creation / invite-creation permission checks through them.
