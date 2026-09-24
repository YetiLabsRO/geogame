# Design — live game overview

## The question this change actually answers

Not "can we draw a map of a live session" — the replay view already draws almost exactly that picture, and the simulator draws it live. The hard part is that a big screen has **no viewer**. Every access rule in this codebase is written against a caller: `location_visibility` scopes to the caller's team, `teammate_visibility_mode: SELECT_COUNT` scopes to the N players nearest the caller, the websocket admits a caller with a DRF token, and `visible_live_pings()` grants staff a bypass because a staff caller is trusted. A screen on a wall in the base tent is read by whoever walks past it, which is none of those things.

So the design is mostly about what "shared surface" means, and two rules follow from it.

## Decision 1 — a shared surface takes the Session's visibility, not the caller's privilege

`visible_live_pings()` returns every consenting player to any `user.is_staff` caller, regardless of `location_visibility`. That is correct for the staff console and the replay view: one accountable person looking at their own screen, for an operational reason, with the session's history already available to them.

It is wrong here. The overview's audience is the room, and with a share link the caller may be a laptop with no account at all. Carrying the staff bypass onto it would mean that a Game configured `location_visibility = OWN_TEAM` — which is the default, and which exists precisely so players cannot see the other side's positions — leaks every position the moment someone projects the overview.

So the overview resolves dots from the Session's config:

| effective config | dots on the overview |
| --- | --- |
| `location_visibility = NONE` | none — tracking is off or suppressed |
| `location_visibility = OWN_TEAM` (default) | **none** |
| `location_visibility = EVERYONE`, `teammate_visibility_mode` ∈ {OWN_TEAM, EVERYONE} | all consenting players |
| `location_visibility = EVERYONE`, `teammate_visibility_mode = SELECT_COUNT` | **none** |

The two "none" rows are the interesting ones. `OWN_TEAM` and `SELECT_COUNT` are both *caller-relative*: they say "each viewer sees their own team" and "each viewer sees the N nearest to them". Neither has a meaning on a surface with no single viewer, and the only two ways to resolve that are to show everything or to show nothing. Showing everything inverts the setting's intent, so the overview shows nothing, and says so on the page — "Player positions are hidden: this session limits live visibility to own team" — rather than rendering an empty map that looks broken.

The consequence worth stating plainly: **out of the box, the big screen has no player dots.** Towers, zones, standings and the ticker all work; a runner who wants dots sets `location_visibility = EVERYONE` on the Game or overrides it on the Session, which is a decision about that game's players that belongs to a human.

Consent is unchanged and still upstream of all of this: a player who never consented, or who withdrew, is absent from every row above.

## Decision 2 — the share viewer joins the real socket, behind an allowlist

The alternative was to let share viewers poll the snapshot endpoint. Rejected: a capture is the event the screen exists to show, and a 10-second poll makes the wall display visibly lag the shouting in the tent. The events are already being broadcast; the cost of using them is an admission path, not a new pipeline.

`ws_auth.TokenAuthMiddleware` currently maps `?token=` to `scope['user']`. It gains a second, disjoint form: `?overview=<link-token>` resolves an active `SessionOverviewLink` into `scope['overview_link']` and leaves `scope['user']` anonymous. `_admission()` accepts such a scope when the link is active, unexpired, and bound to the session in the URL — and only then. A scope carrying both forms is rejected rather than merged, so a share token can never widen a real user's admission or vice versa.

An admitted share viewer is marked restricted, and `session_event` forwards only:

    tower.ownership_changed · zone.control_changed · scoreboard.updated
    bonus.appeared · session.state_changed

`dementor.tick` is excluded by construction, not by omission: it carries a per-player role and energy snapshot, which the overview never renders and an anonymous viewer has no business receiving. The allowlist is a constant checked on the way out, so a future event type is invisible to share viewers until someone adds it deliberately — the safe direction for a default.

Player positions are deliberately *not* on the socket and never have been. Both the staff and the share view poll the snapshot for dots, at the session's `location_ping_interval_seconds` floor, which also means the dot-visibility rule is enforced in exactly one place (the snapshot assembler) rather than in two.

## Decision 3 — one group at a time, because a tower has one owner *per group*

Found while implementing, and it changes the surface rather than the plumbing. `TeamTowerOwnership` is not "who holds this tower" — several TeamGroups play the same physical map simultaneously, and `game.events._tower_ownership_by_group()` already returns a mapping of group slug → holding team. The same is true of zones (`_zone_colors_by_group`). A single-owner overview would silently paint whichever group happened to be last.

So the snapshot keys tower ownership and zone colour by group slug, exactly as the realtime envelopes already do — which turns out to be the reason a `tower.ownership_changed` event can be applied to a snapshot by swapping one field instead of translating anything — and the view paints one group at a time, with a selector when a Game has more than one. Standings and the ticker follow the same selection, so the three panels always describe the same game.

## Decision 4 — one component, two routes, two auth paths

`/staff/sessions/:id/overview` (behind `staffGuard`) and `/staff/live/:token` (unguarded, alongside `/staff/login`) render the same component against the same snapshot shape. The only difference is which endpoint fills it and whether the share-link controls are present.

The share route lives in the **staff** bundle rather than the player one. nginx already serves `frontend/dist/staff/browser` at `/staff/` with an unauthenticated `try_files` fallback — `/staff/login` proves the path is publicly reachable today — so this needs no deployment change, whereas putting it in the player app would drag it through that app's PWA service worker and session-picker semantics for no benefit.

The snapshot shapes deliberately echo `game/replay.py`'s bundle for teams, towers and zones, so the two map surfaces paint from the same field names and `TeamColorResolver` works unchanged. They are not unified into one function: the replay bundle is a whole-window historical object with frames and intervals, the overview snapshot is a single instant with no history, and collapsing them would give one function two modes and no clear contract.

The share route also needs the app shell to step out of the way. The staff shell renders either a signed-in sidebar or a signed-out bar with a "Sign in" button, and both are wrong above a wall display: the first is staff navigation on an unauthenticated surface, the second invites a viewer to do something they cannot. The shell therefore gains a third, chromeless branch for `/live/` that renders the outlet and nothing else.

## Decision 5 — the token is a bearer capability, so it is scoped and revocable rather than secret

The share URL will be pasted into chats, shown on a screen and photographed. Design accordingly: it grants read-only access to one Session's overview, nothing else — no roster, no submissions, no history, no other session — and it is revocable in one click with immediate effect on both the REST snapshot and any open socket. `expires_at` is optional and defaults unset, because a runner who needs the screen for the afternoon should not have it die mid-game; revocation is the primary control, expiry the convenience.

The token is `secrets.token_urlsafe(24)`, matching `NfcTag`'s generator and its stated posture: the token is the credential, so it is long enough not to be guessable and is never treated as a secret once issued.

Rate limiting applies to the token endpoints because they are the first unauthenticated read of live state; the limit is per-token, so one over-eager display cannot exhaust another's budget. It needs a cache backend, which this project did not configure before — Redis in production (where `REDIS_URL` is already set for the channel layer), local memory otherwise, which makes the limit per-process in development and is stated in the settings comment rather than left to be discovered.

Revocation has to reach a screen that is already showing the overview, not merely the next request for it — a revoke button that leaves the projector running is not a control. A restricted socket therefore joins a second channel-layer group named for its link, and revoking broadcasts a close to it.

One narrowing beyond "no broader than the staff snapshot": the share snapshot carries no usernames. A name is what a staff member needs to act on what they see ("radio Ana"); on a projector it identifies a person to a room that has no use for the name. The dot and the team colour carry everything the display is for.

## Non-goals

- **Spectator interaction.** The overview is read-only. No controls reach game state from it, and the share route renders none.
- **Replacing the scoreboard page.** `/scoreboard` stays: it is the dense, sortable, per-group view for someone at a desk. The overview is for someone across a room.
- **Reconstructing history.** The overview is the present instant. Looking backwards is what `session-replay` is for, and the two link to each other rather than growing each other's features.
- **Multi-session displays.** One screen, one Session. A venue running two sessions opens two links.
