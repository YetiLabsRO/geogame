## 1. ASGI + Channels infrastructure

- [ ] 1.1 Add `channels`, `channels-redis`, and a Web Push library (e.g. `pywebpush`) to `requirements.txt`; add `channels` to `INSTALLED_APPS`.
- [ ] 1.2 Create `geogame/asgi.py` with a `ProtocolTypeRouter`: HTTP → the existing Django app; websocket → an auth-middleware-wrapped `URLRouter`. Keep `geogame/wsgi.py` working for non-real-time deployments.
- [ ] 1.3 Configure `CHANNEL_LAYERS`: `channels_redis` for prod (Redis URL from settings/`local_settings.py`), in-memory layer for tests/single-process dev.
- [ ] 1.4 Add a token-auth middleware for the websocket scope that resolves the DRF token (query param or subprotocol) to a user.

## 2. Real-time broadcasting (server)

- [ ] 2.1 Add a session-scoped websocket consumer that, on connect, authenticates the user and admits only members with an active membership on the Session (or staff), then joins group `session.<id>`; leave the group on disconnect.
- [ ] 2.2 Define the typed event envelope `{type, session, ts, payload}` with events `tower.ownership_changed`, `zone.control_changed`, `scoreboard.updated`, `bonus.appeared`.
- [ ] 2.3 Add a single `broadcast_session_event(session, event)` helper that fans out to the Session group via the channel layer; no-op (log + degrade) if the layer is unavailable.
- [ ] 2.4 Wire the ownership/zone-control recompute path (conquer, steal, tower deactivation, zone recontrol) to emit `tower.ownership_changed` / `zone.control_changed` with the affected geometry + per-TeamGroup coloring.
- [ ] 2.5 Emit `scoreboard.updated` with every team's locked + floating totals when scores change; throttle/coalesce to at most once per short window per Session.
- [ ] 2.6 Emit `bonus.appeared` when a score multiplier / bonus pops up (see the `score-multipliers` capability) so clients surface it live.

## 3. Config knobs

- [ ] 3.1 Add `Game.realtime_enabled` (default `True`) and `Game.push_notifications_enabled` (default `False`) with nullable per-`Session` overrides; migrate.
- [ ] 3.2 Resolve both through the existing effective-value helper (Session override wins, else Game default); expose the effective values to clients.

## 4. Real-time frontend (player + staff)

- [ ] 4.1 Add a websocket-client service (Angular signal-based) with auto-reconnect + exponential backoff, subscribed to the current Session socket.
- [ ] 4.2 On (re)connect, fetch a fresh REST snapshot to reconcile missed events before applying live events.
- [ ] 4.3 Apply `tower.ownership_changed` / `zone.control_changed` to recolor the affected zone/tower on the Leaflet map without a full reload.
- [ ] 4.4 Apply `scoreboard.updated` to the player live scoreboard and the staff scoreboard in real time (highlight overtakes).
- [ ] 4.5 Polling fallback: when the socket cannot connect / is down, or `realtime_enabled` is false, fall back to the existing REST poll/refresh path.

## 5. Push notifications (backend)

- [ ] 5.1 Add `organize.PushSubscription` (user, device/endpoint, keys or FCM token, `created_at`, `revoked_at`) and `organize.NotificationPreference` (per-user/per-Session opt-in + per-event toggles); migrate.
- [ ] 5.2 Add `POST/DELETE /api/push/subscriptions/` (register / revoke a subscription, requires consent) and `GET/PATCH /api/push/preferences/`; add a public VAPID key endpoint.
- [ ] 5.3 On steal / conquer / bonus events, send Web Push / FCM to consented subscribers whose Game/Session has `push_notifications_enabled` and whose event toggle is on.
- [ ] 5.4 Prune subscriptions the push service reports as gone (404/410) and never send without an active, consented subscription.

## 6. Push notifications (frontend)

- [ ] 6.1 Player app: a notification-permission opt-in flow (explicit consent) that registers a `PushSubscription`; a settings toggle to revoke.
- [ ] 6.2 Add a service worker to receive Web Push and display steal / conquer / bonus notifications; deep-link the tap into the relevant tower/map.

## 7. Tests

- [ ] 7.1 Consumer test: an authenticated member connects, joins only their Session group, and receives a broadcast; a non-member / unauthenticated socket is rejected.
- [ ] 7.2 Isolation test: an event broadcast to Session A is NOT delivered to a client on Session B.
- [ ] 7.3 Broadcast test: a conquer/steal recompute emits `tower.ownership_changed` (+ `zone.control_changed` when control flips) and `scoreboard.updated` with correct totals.
- [ ] 7.4 Fallback test: with the channel layer unavailable / `realtime_enabled` false, the REST snapshot still returns correct map + scoreboard data (correctness preserved without the socket).
- [ ] 7.5 Config test: Session override of `realtime_enabled` / `push_notifications_enabled` wins over the Game default via the effective-value helper.
- [ ] 7.6 Push test: a consented subscription with `push_notifications_enabled` receives a steal/conquer/bonus push; no subscription / no consent / feature off sends nothing; a gone (410) subscription is pruned.
- [ ] 7.7 ASGI smoke test: HTTP endpoints behave identically served under the ASGI application.
- [ ] 7.8 Ensure ruff-clean and ≥80% branch coverage for the new code.
