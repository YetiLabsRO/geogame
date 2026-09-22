import { Injectable, NgZone, computed, inject, signal } from '@angular/core';
import { Observable, Subject, filter, map } from 'rxjs';

import { AuthService } from './auth.service';
import { SessionScoreboardEntry } from './game-api.service';
import { PlatformService } from './platform';

/**
 * Realtime websocket client (realtime-and-notifications).
 *
 * Connects to the session-scoped socket (`/ws/session/<id>/?token=…`),
 * dispatches typed envelopes, auto-reconnects with exponential backoff
 * and exposes signals for components to drive their polling fallback:
 * whenever `connected()` is false, the existing REST poll/refresh path
 * remains the source of truth. On every (re)connect `connections()`
 * increments so consumers refetch a fresh REST snapshot to reconcile
 * missed events before applying live ones.
 */

export type RealtimeStatus =
  | 'idle' // no connect() yet, or explicitly disconnected
  | 'connecting'
  | 'connected'
  | 'reconnecting' // socket lost, backoff timer running
  | 'disabled'; // realtime off for the session / rejected by server

export interface RealtimeEnvelope<T = unknown> {
  type: string;
  session: number;
  ts: string;
  payload: T;
}

export interface RealtimeTeamSummary {
  team_id: number;
  team_name: string;
  team_color: string;
}

export interface TowerOwnershipChangedPayload {
  tower_id: number;
  tower_name: string;
  zone_id: number | null;
  zone_name: string | null;
  kind: 'conquered' | 'stolen' | 'released';
  team: RealtimeTeamSummary | null;
  /** Per-TeamGroup controlling team, keyed by group slug. */
  ownership: Record<string, RealtimeTeamSummary | null>;
}

export interface ZoneControlChangedPayload {
  zone_id: number;
  zone_name: string;
  /** Per-TeamGroup zone color, keyed by group slug. */
  colors: Record<string, string>;
}

export interface ScoreboardUpdatedPayload {
  entries: SessionScoreboardEntry[];
}

export interface SessionStateChangedPayload {
  state: string;
  previous: string;
  action: string;
  is_active: boolean;
}

/** mode-dementors-ble 5.3: full role/energy snapshot after a server tick. */
export interface DementorTickPayload {
  totals: { wizards: number; dementors: number; out_of_play: number };
  players: {
    player_id: number;
    role: 'WIZARD' | 'DEMENTOR';
    energy: number;
    alive: boolean;
    last_delta: number;
  }[];
}

/** Application close codes the server uses to refuse a socket for good. */
const FATAL_CLOSE_CODES = [4401, 4403, 4404, 4423];

const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30_000;
const HEARTBEAT_INTERVAL_MS = 25_000;

@Injectable({ providedIn: 'root' })
export class RealtimeService {
  private readonly auth = inject(AuthService);
  private readonly zone = inject(NgZone);
  private readonly platform = inject(PlatformService);

  private socket: WebSocket | null = null;
  private sessionId: number | null = null;
  private attempts = 0;
  private reconnectHandle: ReturnType<typeof setTimeout> | null = null;
  private heartbeatHandle: ReturnType<typeof setInterval> | null = null;
  private readonly _events = new Subject<RealtimeEnvelope>();

  private readonly _status = signal<RealtimeStatus>('idle');
  private readonly _connections = signal(0);

  /** Socket status; drive UI badges from this. */
  readonly status = this._status.asReadonly();
  /** True while the live socket is up (skip the polling fallback). */
  readonly connected = computed(() => this._status() === 'connected');
  /**
   * Increments on every successful (re)connect. Consumers refetch their
   * REST snapshot when this changes to reconcile missed events.
   */
  readonly connections = this._connections.asReadonly();
  /** Every typed envelope from the server. */
  readonly events$: Observable<RealtimeEnvelope> = this._events.asObservable();

  /** Envelopes of one type, payload-typed for convenience. */
  eventsOfType<T>(type: string): Observable<RealtimeEnvelope<T>> {
    return this.events$.pipe(
      filter((envelope) => envelope.type === type),
      map((envelope) => envelope as RealtimeEnvelope<T>),
    );
  }

  /**
   * Open (or re-target) the session socket. Pass `enabled: false` (the
   * effective `realtime_enabled` for the session) to skip the socket
   * entirely — consumers then rely on their existing polling.
   */
  connect(sessionId: number, enabled = true): void {
    if (!enabled) {
      this.disconnect();
      this._status.set('disabled');
      return;
    }
    if (this.sessionId === sessionId && (this.socket || this.reconnectHandle)) {
      return; // already connected / reconnecting to this session
    }
    this.disconnect();
    this.sessionId = sessionId;
    this.attempts = 0;
    this.open();
  }

  /** Close the socket and stop reconnecting. */
  disconnect(): void {
    this.clearTimers();
    if (this.socket) {
      const socket = this.socket;
      this.socket = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.onmessage = null;
      socket.onopen = null;
      socket.close();
    }
    this.sessionId = null;
    this._status.set('idle');
  }

  private open(): void {
    const token = this.auth.token();
    if (this.sessionId === null || !token || typeof WebSocket === 'undefined') {
      this._status.set('disabled');
      return;
    }
    this._status.set(this.attempts === 0 ? 'connecting' : 'reconnecting');
    const { scheme, host } = this.wsOrigin();
    const url =
      `${scheme}://${host}/ws/session/${this.sessionId}/` + `?token=${encodeURIComponent(token)}`;
    // Run the socket outside Angular so heartbeats/reconnect timers do
    // not hold change detection; re-enter the zone per message.
    this.zone.runOutsideAngular(() => {
      const socket = new WebSocket(url);
      this.socket = socket;
      socket.onopen = () => this.zone.run(() => this.onOpen());
      socket.onmessage = (event) => this.zone.run(() => this.onMessage(event));
      socket.onclose = (event) => this.zone.run(() => this.onClose(event));
      socket.onerror = () => {
        // onclose always follows; nothing to do here.
      };
    });
  }

  /**
   * mobile-app D3: on native (and whenever a debug origin override is
   * set) derive `ws(s)://host` from the configured API origin instead of
   * `location`, which is the opaque Capacitor WebView origin and not the
   * Django host. Falls back to `location` when no origin is configured
   * (the ordinary same-origin web deployment / dev proxy).
   */
  private wsOrigin(): { scheme: string; host: string } {
    const base = this.platform.apiBaseUrl();
    if (base) {
      const url = new URL(base);
      return { scheme: url.protocol === 'https:' ? 'wss' : 'ws', host: url.host };
    }
    return { scheme: location.protocol === 'https:' ? 'wss' : 'ws', host: location.host };
  }

  private onOpen(): void {
    this.attempts = 0;
    this._status.set('connected');
    this._connections.update((n) => n + 1);
    this.heartbeatHandle = setInterval(() => {
      if (this.socket?.readyState === WebSocket.OPEN) {
        this.socket.send(JSON.stringify({ type: 'ping' }));
      }
    }, HEARTBEAT_INTERVAL_MS);
  }

  private onMessage(event: MessageEvent): void {
    let envelope: RealtimeEnvelope | { type?: string } | null = null;
    try {
      envelope = JSON.parse(event.data as string);
    } catch {
      return; // not JSON — ignore
    }
    if (!envelope || typeof envelope.type !== 'string' || envelope.type === 'pong') {
      return;
    }
    this._events.next(envelope as RealtimeEnvelope);
  }

  private onClose(event: CloseEvent): void {
    this.socket = null;
    if (this.heartbeatHandle) {
      clearInterval(this.heartbeatHandle);
      this.heartbeatHandle = null;
    }
    if (this.sessionId === null) {
      return; // explicit disconnect()
    }
    if (FATAL_CLOSE_CODES.includes(event.code)) {
      // Unauthorized / not a member / unknown session / realtime off —
      // reconnecting would only repeat the refusal. Fall back to polling.
      this._status.set('disabled');
      this.sessionId = null;
      return;
    }
    // Exponential backoff with jitter, capped.
    this._status.set('reconnecting');
    const delay = Math.min(MAX_RECONNECT_DELAY_MS, BASE_RECONNECT_DELAY_MS * 2 ** this.attempts);
    this.attempts += 1;
    this.reconnectHandle = setTimeout(
      () => {
        this.reconnectHandle = null;
        this.open();
      },
      delay + Math.floor(Math.random() * 500),
    );
  }

  private clearTimers(): void {
    if (this.reconnectHandle) {
      clearTimeout(this.reconnectHandle);
      this.reconnectHandle = null;
    }
    if (this.heartbeatHandle) {
      clearInterval(this.heartbeatHandle);
      this.heartbeatHandle = null;
    }
  }
}

/** Event-type constants mirroring `game/events.py`. */
export const REALTIME_EVENTS = {
  towerOwnershipChanged: 'tower.ownership_changed',
  zoneControlChanged: 'zone.control_changed',
  scoreboardUpdated: 'scoreboard.updated',
  bonusAppeared: 'bonus.appeared',
  sessionStateChanged: 'session.state_changed',
  dementorTick: 'dementor.tick',
} as const;
