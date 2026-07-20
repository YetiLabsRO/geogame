## Why

Domination is a race: when a rival team steals or conquers a tower, or a bonus multiplier pops up, players and staff want to know **now** — not on the next poll. The shipped specs deliberately took a polling-only stance ("update via polling", "polling every 30s is acceptable; no websockets required") to keep the first cut simple. That stance now blocks the core feeling of the game: a player cannot tell in the moment when they are being overtaken, and the map lags reality by up to a poll interval. This change **supersedes the polling-only stance**: it makes the live map recolor and the live scoreboard push-based over Django Channels websockets, backed by a Redis channel layer, and adds optional Web Push / FCM notifications (steal / conquer / bonus) for players who opt in — valuable especially for small games with only a handful of teams. Polling is retained as a graceful fallback so nothing breaks when websockets or push are unavailable.

## What Changes

- **Adopt Django Channels (ASGI).** Run the project under an ASGI application, add a websocket URL router, and configure a **Redis channel layer** for cross-process fan-out. Keep the WSGI entrypoint working for environments that do not enable real-time.
- **Session-scoped websocket endpoint.** A token-authenticated consumer joins the caller to the group for their current Session and streams game events (ownership changes, scoreboard totals, bonus pop-ups).
- **Broadcast on state change.** When a tower is conquered or stolen, or ownership/zone control is recomputed, or a score multiplier appears, the server broadcasts a typed event to the Session group so every client **recolors the affected zone/tower** and updates the **live scoreboard** in real time.
- **Live scoreboard totals in real time.** Every team's locked + floating totals are pushed so a player can see when they are being overtaken; staff see the same on the scoreboard.
- **Polling fallback.** Clients that cannot open a websocket (or when real-time is disabled) fall back to the existing REST polling/refresh path with no loss of correctness — only of immediacy.
- **Optional push notifications.** Add Web Push (VAPID) and FCM support: a consented, opt-in subscription per user/device, stored server-side, and notifications fired on steal / conquer / bonus events. Users must grant permission; they can revoke it. A per-Game toggle (default off) keeps this opt-in at the game level too.
- **Config knobs** on `Game` with per-`Session` overrides: `realtime_enabled` (default on) and `push_notifications_enabled` (default off), resolved by the effective-value helper.

## Capabilities

### New Capabilities
- `realtime-updates`: Django Channels websocket delivery of live map recolor and live scoreboard events over a Redis channel layer, with polling as a graceful fallback.
- `push-notifications`: opt-in Web Push / FCM notifications for steal / conquer / bonus events, gated on user consent and a per-Game toggle.

### Modified Capabilities
- `geographic-map`: the live map API is complemented by real-time broadcast of ownership/recolor events; map data is now push-first with polling fallback.
- `player-app`: the live map and a live scoreboard update in real time via websockets, with polling as a graceful fallback (supersedes "no websockets required").
- `staff-app`: the live scoreboard updates in real time via websockets, with polling as a graceful fallback (supersedes "polling every 30s ... no websockets required").

## Impact

- **Models**: new `organize.PushSubscription` (user/device subscription: endpoint, keys or FCM token, `created_at`, `revoked_at`) and `organize.NotificationPreference` (per-user/per-Session opt-in + event toggles); new config fields `Game.realtime_enabled`, `Game.push_notifications_enabled` with nullable `Session` overrides.
- **APIs**: new websocket route (e.g. `/ws/session/<id>/`) served by a Channels consumer; REST `POST/DELETE /api/push/subscriptions/` to register/revoke a push subscription and `GET/PATCH /api/push/preferences/`; a public VAPID key endpoint.
- **Frontend**: player and staff SPAs gain a websocket client service with auto-reconnect and polling fallback; the map recolors and the scoreboard updates from pushed events; the player app adds a notification-permission opt-in and a service worker for Web Push.
- **Migrations/other**: migration for the new models and config fields; add `channels`, `channels-redis`, and a Web Push library (e.g. `pywebpush`) to `requirements.txt`; ASGI application + channel-layer settings; Redis becomes a runtime dependency when real-time is enabled (documented in `deployment`).
