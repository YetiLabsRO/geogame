## 1. ASGI + Channels infrastructure

- [x] 1.1 Add `channels`, `channels-redis`, and a Web Push library (e.g. `pywebpush`) to `requirements.txt`; add `channels` to `INSTALLED_APPS`.
- [x] 1.2 Create `geogame/asgi.py` with a `ProtocolTypeRouter`: HTTP → the existing Django app; websocket → an auth-middleware-wrapped `URLRouter`. Keep `geogame/wsgi.py` working for non-real-time deployments.
- [x] 1.3 Configure `CHANNEL_LAYERS`: `channels_redis` for prod (Redis URL from settings/`local_settings.py`), in-memory layer for tests/single-process dev.
- [x] 1.4 Add a token-auth middleware for the websocket scope that resolves the DRF token (query param or subprotocol) to a user.

## 2. Real-time broadcasting (server)

- [x] 2.1 Add a session-scoped websocket consumer that, on connect, authenticates the user and admits only members with an active membership on the Session (or staff), then joins group `session.<id>`; leave the group on disconnect.
- [x] 2.2 Define the typed event envelope `{type, session, ts, payload}` with events `tower.ownership_changed`, `zone.control_changed`, `scoreboard.updated`, `bonus.appeared`.
- [x] 2.3 Add a single `broadcast_session_event(session, event)` helper that fans out to the Session group via the channel layer; no-op (log + degrade) if the layer is unavailable.
- [x] 2.4 Wire the ownership/zone-control recompute path (conquer, steal, tower deactivation, zone recontrol) to emit `tower.ownership_changed` / `zone.control_changed` with the affected geometry + per-TeamGroup coloring.
- [x] 2.5 Emit `scoreboard.updated` with every team's locked + floating totals when scores change; throttle/coalesce to at most once per short window per Session.
- [x] 2.6 Emit `bonus.appeared` when a score multiplier / bonus pops up (see the `score-multipliers` capability) so clients surface it live.

## 3. Config knobs

- [x] 3.1 Add `Game.realtime_enabled` (default `True`) and `Game.push_notifications_enabled` (default `False`) with nullable per-`Session` overrides; migrate.
- [x] 3.2 Resolve both through the existing effective-value helper (Session override wins, else Game default); expose the effective values to clients.

## 4. Real-time frontend (player + staff)

- [x] 4.1 Add a websocket-client service (Angular signal-based) with auto-reconnect + exponential backoff, subscribed to the current Session socket.
- [x] 4.2 On (re)connect, fetch a fresh REST snapshot to reconcile missed events before applying live events.
- [x] 4.3 Apply `tower.ownership_changed` / `zone.control_changed` to recolor the affected zone/tower on the Leaflet map without a full reload.
- [x] 4.4 Apply `scoreboard.updated` to the player live scoreboard and the staff scoreboard in real time (highlight overtakes).
- [x] 4.5 Polling fallback: when the socket cannot connect / is down, or `realtime_enabled` is false, fall back to the existing REST poll/refresh path.

## 5. Push notifications (backend)

- [x] 5.1 Add `organize.PushSubscription` (user, device/endpoint, keys or FCM token, `created_at`, `revoked_at`) and `organize.NotificationPreference` (per-user/per-Session opt-in + per-event toggles); migrate.
- [x] 5.2 Add `POST/DELETE /api/push/subscriptions/` (register / revoke a subscription, requires consent) and `GET/PATCH /api/push/preferences/`; add a public VAPID key endpoint.
- [x] 5.3 On steal / conquer / bonus events, send Web Push / FCM to consented subscribers whose Game/Session has `push_notifications_enabled` and whose event toggle is on.
- [x] 5.4 Prune subscriptions the push service reports as gone (404/410) and never send without an active, consented subscription.

## 6. Push notifications (frontend)

- [x] 6.1 Player app: a notification-permission opt-in flow (explicit consent) that registers a `PushSubscription`; a settings toggle to revoke.
- [x] 6.2 Add a service worker to receive Web Push and display steal / conquer / bonus notifications; deep-link the tap into the relevant tower/map.

## 7. Tests

- [x] 7.1 Consumer test: an authenticated member connects, joins only their Session group, and receives a broadcast; a non-member / unauthenticated socket is rejected.
- [x] 7.2 Isolation test: an event broadcast to Session A is NOT delivered to a client on Session B.
- [x] 7.3 Broadcast test: a conquer/steal recompute emits `tower.ownership_changed` (+ `zone.control_changed` when control flips) and `scoreboard.updated` with correct totals.
- [x] 7.4 Fallback test: with the channel layer unavailable / `realtime_enabled` false, the REST snapshot still returns correct map + scoreboard data (correctness preserved without the socket).
- [x] 7.5 Config test: Session override of `realtime_enabled` / `push_notifications_enabled` wins over the Game default via the effective-value helper.
- [x] 7.6 Push test: a consented subscription with `push_notifications_enabled` receives a steal/conquer/bonus push; no subscription / no consent / feature off sends nothing; a gone (410) subscription is pruned.
- [x] 7.7 ASGI smoke test: HTTP endpoints behave identically served under the ASGI application.
- [x] 7.8 Ensure ruff-clean and ≥80% branch coverage for the new code.

## Implementation notes

- **Channel layer selection (1.3):** Redis (`channels_redis`) is used only when the
  `REDIS_URL` env var is set; otherwise the InMemory layer. The whole test suite runs
  green WITHOUT Redis. `ASGI_APPLICATION` is set unconditionally; `wsgi.py` untouched.
- **Socket auth transport (1.4):** DRF token as a `?token=` query parameter only.
  The subprotocol variant was deliberately not implemented (browser `WebSocket` cannot
  set headers; subprotocol echo breaks intermediaries) — rationale in `game/ws_auth.py`.
- **Event names (2.2):** envelope `{type, session, ts, payload}` with
  `tower.ownership_changed` / `zone.control_changed` / `scoreboard.updated` /
  `bonus.appeared`, plus an extra `session.state_changed` emitted from
  `Session.transition()` (clients ignore unknown types). The consumer additionally
  answers `{"type": "ping"}` with `{"type": "pong"}` (client heartbeat).
- **Emit seams (2.4/2.5):** `Tower.assign_to_team` (conquer/steal + zone flip detection),
  `Tower.unassign` (release; fans out to every Session whose teams were touched, since a
  repository tower can be live in several Sessions), `Team.update_score`, and the
  fail-penalty queryset update in `TeamTowerChallenge._apply_failure_consequences`.
  A capture can emit `scoreboard.updated` more than once (initial-bonus award goes
  through `Team.update_score`); each event is a full snapshot and the per-Session
  throttle (`REALTIME_SCOREBOARD_THROTTLE_SECONDS`, default 2 s, leading edge,
  process-local) coalesces bursts.
- **2.6 (`bonus.appeared`):** `game.events.emit_bonus_appeared` is the ready seam
  (broadcast + push hand-off, covered by tests); no production call site exists yet —
  the multiplier engine lands with the separate `score-multipliers` change.
- **Push sender (5.3):** `BasePushSender` interface; `WebPushSender` (pywebpush+VAPID)
  is selected only when both VAPID keys are configured, otherwise `LoggingPushSender`
  (logs, delivers nothing). FCM subscriptions are accepted and stored but delivery is
  logged-only (`FCM_SERVER_KEY` reserved). Bug fixed during test-writing: the events →
  push hand-off now maps kind `stolen`/`conquered` to push vocabulary `steal`/`conquer`.
- **New dev dependency:** `daphne` in `requirements-dev.txt` only — `channels.testing`
  imports it at module level; runtime does not need it (prod ASGI server choice is a
  deployment concern; WSGI still works).
- **Frontend:** shared `RealtimeService` (signals + RxJS events, exponential backoff
  reconnect, fatal close codes 4401/4403/4404/4423 stop reconnecting, `connections()`
  counter drives snapshot reconciliation). Player map recolors tower markers/zone layers
  in place (score-map mode uses the per-group payload keyed by the route slug; the
  default map colors by the capturing team). Staff scoreboard + player session detail
  apply `scoreboard.updated` live with a transient overtake highlight; both poll every
  30 s ONLY while the socket is down. Player `/settings` route hosts the push consent
  toggle + per-event preferences; `public/push-sw.js` shows notifications and deep-links
  taps. Dev proxy got a `/ws` (ws:true) entry.
- **Expected merge conflict hotspots:** `organize/models.py` (OVERRIDABLE_CONFIG_FIELDS,
  Game/Session knobs, new models at EOF), `organize/urls.py`, `organize/admin.py`,
  `organize/api.py` (CurrentSessionSerializer), `game/models.py` (assign_to_team /
  unassign / update_score seams), `game/admin_api.py` (serializer field lists),
  `geogame/settings.py`, `game/tests.py` + `organize/tests.py` (appended sections),
  frontend `shared/public-api.ts`, player `app.routes.ts`/`app.html`, `proxy.conf.json`.
  Migration `organize/0018_realtime_and_push.py` numbering may collide with parallel
  branches (expected; merger resolves).
