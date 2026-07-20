## Context

The shipped clients keep the map and scoreboard fresh by polling the REST API (or a manual refresh), and the specs explicitly say "no websockets required". That was a deliberate simplification, but domination is a competitive real-time race: stealing and conquering towers, watching a rival's total climb past yours, and reacting to a surprise bonus multiplier are the moment-to-moment hooks of the game, and a poll interval of even a few seconds dulls all of them. The shared architecture brief (Section 2) has since **adopted real-time**: Django Channels (ASGI) + websockets with a Redis channel layer for live updates, and Web Push / FCM for notifications. This change implements that adoption and explicitly supersedes the polling-only stance in `geographic-map`, `player-app`, and `staff-app`, keeping polling only as a fallback.

## Goals / Non-Goals

**Goals:**
- Push tower ownership changes (conquer / steal) to all clients in a Session so the map **recolors** the affected zone/tower immediately.
- Push every team's live scoreboard totals (locked + floating) so a player can see when they are being overtaken and staff see the same on the scoreboard.
- Use Django Channels (ASGI) + websockets with a **Redis channel layer** for cross-process fan-out; authenticate the socket and scope it to one Session.
- Keep **polling as a graceful fallback**: when a websocket cannot be established or real-time is disabled, clients still work via the existing REST path — only immediacy is lost, never correctness.
- Add **optional, opt-in** push notifications (Web Push / FCM) for steal / conquer / bonus, gated on explicit user consent and a per-Game toggle.
- Every new knob defaults to preserve current behavior and is backward compatible.

**Non-Goals:**
- Live location streaming of players/teammates on the map — that is the separate `live-location-tracking` change; this change broadcasts ownership and score events, not positions.
- Chat, presence lists, or arbitrary bidirectional messaging — the websocket is server→client broadcast for game state (plus lightweight client subscribe/heartbeat).
- Changing the scoring formulas or the ownership/lifecycle rules — this change only *transports* the results of those computations.
- Replacing REST reads; the websocket augments them and the REST snapshot remains the source of truth for initial load and reconciliation.

## Decisions

- **Django Channels (ASGI) alongside WSGI.** Introduce `geogame/asgi.py` with a `ProtocolTypeRouter` (HTTP → Django, websocket → auth-middleware-wrapped URL router). WSGI keeps working; real-time is active only when the app is served under ASGI with a channel layer configured. Alternative considered: raw `websockets`/SSE without Channels — rejected because Channels gives us groups, auth middleware, and a Redis-backed layer with far less bespoke plumbing.
- **Redis channel layer for fan-out.** Use `channels_redis` so broadcasts reach clients on any worker/process. Alternative considered: the in-memory layer — rejected for production because it does not fan out across processes; it MAY be used only in tests/single-process dev.
- **One group per Session.** Consumers join `session.<id>` on connect (after auth + membership check) and leave on disconnect. Broadcasts target that group so events never leak across Sessions. Per-TeamGroup coloring is carried in the event payload; the client applies the same coloring logic it already uses for REST.
- **Token-authenticated websocket, membership-scoped.** The socket authenticates with the same DRF token (query param or subprotocol) and is admitted only if the user has an active membership on that Session (players) or is staff. Alternative considered: unauthenticated public map socket — rejected; scope and coloring depend on identity, and it would leak game state.
- **Broadcast at the same seam that recomputes ownership.** The existing ownership/zone-control recompute path (conquer, steal, tower deactivation, zone recontrol) emits a typed event via a single `broadcast_session_event(session, event)` helper (Django signal or explicit call). Alternative considered: DB-polling a change feed — rejected as redundant with the recompute we already do.
- **Typed event envelope.** Every message is `{ "type": <event>, "session": <id>, "ts": <iso8601>, "payload": {...} }` with events `tower.ownership_changed` (conquer/steal/release → recolor), `zone.control_changed` (recolor), `scoreboard.updated` (per-team totals), and `bonus.appeared` (score multiplier pop-up). Clients switch on `type`. This keeps the contract explicit and versionable.
- **Polling fallback is first-class, not an afterthought.** The client opens the websocket; on failure or disconnect it auto-reconnects with backoff and, while down, falls back to the existing poll/refresh. On (re)connect it fetches a fresh REST snapshot to reconcile any missed events. When `realtime_enabled` is false, clients skip the socket entirely and poll.
- **Push is opt-in twice.** Web Push (VAPID) for browsers and FCM for native/where configured. A notification is sent only if (a) the Game/Session has `push_notifications_enabled` and (b) the user has an active, consented `PushSubscription` with the relevant event toggle on. Alternative considered: on-by-default push — rejected; unsolicited notifications require consent by platform policy and are undesirable for large games.
- **Config knobs follow the Game-default + Session-override pattern.** `Game.realtime_enabled` (default `True`) and `Game.push_notifications_enabled` (default `False`) each have a nullable per-`Session` override resolved by the existing effective-value helper, matching `proximity_meters` and the pause/failure knobs.

## Risks / Trade-offs

- [Redis becomes a new runtime dependency for real-time] → Make it required only when `realtime_enabled`; degrade to polling if the channel layer is unavailable, and document the dependency in `deployment`. Dev/tests MAY use the in-memory layer.
- [Websocket auth/scoping bugs could leak another Session's events] → Admit only authenticated users with an active membership (or staff) and join exactly one Session group; cover cross-Session isolation with a consumer test.
- [Broadcast storms on a busy game (many rapid captures)] → Coalesce `scoreboard.updated` (debounce/throttle to at most once per short window per Session) and send compact deltas for ownership events; the client reconciles from a REST snapshot on reconnect.
- [Missed events during a disconnect could desync the map] → On every (re)connect the client pulls a fresh REST snapshot before applying live events, so a dropped socket never leaves a stale map.
- [Push delivery is best-effort and platform-dependent] → Treat push as advisory; the in-app websocket/poll remains the authoritative update path. Prune subscriptions that return 404/410 (gone) from the push service.
- [ASGI migration could regress existing HTTP behavior] → Keep HTTP routed to the existing Django app inside the `ProtocolTypeRouter`; add a smoke test that HTTP endpoints behave identically under ASGI.

## Migration Plan

1. Add `channels`, `channels-redis`, and a Web Push library (e.g. `pywebpush`) to `requirements.txt`; add `channels` to `INSTALLED_APPS`; add `geogame/asgi.py` and `CHANNEL_LAYERS` (Redis in prod, in-memory in tests).
2. Add `Game.realtime_enabled` (default `True`) and `Game.push_notifications_enabled` (default `False`) plus nullable `Session` overrides; migrate. Existing rows keep current behavior (real-time available, push off).
3. Add `PushSubscription` and `NotificationPreference` models; migrate.
4. Wire the ownership/zone-control recompute path to call `broadcast_session_event(...)`; add the websocket consumer, routing, and auth middleware.
5. Add REST endpoints for push subscription register/revoke, preferences, and the public VAPID key.
6. Ship the frontend websocket-client service (auto-reconnect + polling fallback), map recolor/scoreboard wiring, and the player-app notification opt-in + service worker.
7. Document the Redis dependency and ASGI deployment in `deployment`; keep WSGI working for non-real-time deployments.
