import { Injectable, effect, inject, signal } from '@angular/core';

import {
  AuthService,
  BackgroundLocationFix,
  BackgroundLocationService,
  GameApiService,
  GeolocationService,
  LocationConfig,
  PlatformService,
} from 'shared';

/**
 * Streams the player's position at the game-configured cadence
 * (live-location capability).
 *
 * The interval comes from the Session's effective
 * `location_ping_interval_seconds` — there is deliberately NO
 * player-facing control to change it. Streaming pauses whenever
 * tracking is disabled or consent is absent/withdrawn.
 *
 * mobile-app 2.4: on native, once tracking + consent are both on, this
 * hands off to the background location watcher (survives the screen
 * turning off / the app backgrounding) instead of a foreground timer,
 * throttling fixes to at most one ping per `ping_interval_seconds`. The
 * web path is unchanged — a foreground `setInterval` timer.
 */
@Injectable({ providedIn: 'root' })
export class LocationStreamService {
  private readonly api = inject(GameApiService);
  private readonly geolocation = inject(GeolocationService);
  private readonly backgroundLocation = inject(BackgroundLocationService);
  private readonly platform = inject(PlatformService);
  private readonly auth = inject(AuthService);

  readonly config = signal<LocationConfig | null>(null);
  readonly hasConsent = signal(false);
  readonly streaming = signal(false);

  private timer: ReturnType<typeof setInterval> | null = null;
  private lastPingAt = 0;

  constructor() {
    // Stop streaming immediately on sign-out — nothing should keep
    // reporting a signed-out player's location in the background.
    effect(() => {
      if (!this.auth.isAuthenticated()) {
        this.markWithdrawn();
      }
    });
  }

  /** Store the Session's effective location config; stop if tracking is off. */
  configure(config: LocationConfig): void {
    this.config.set(config);
    if (!config.tracking_enabled) {
      this.stop();
    } else if (this.hasConsent()) {
      this.start();
    }
  }

  /** Consent granted — begin pacing pings at the game interval. */
  markConsented(): void {
    this.hasConsent.set(true);
    if (this.config()?.tracking_enabled) {
      this.start();
    }
  }

  /** Consent withdrawn — stop streaming immediately. */
  markWithdrawn(): void {
    this.hasConsent.set(false);
    this.stop();
  }

  private start(): void {
    if (this.streaming()) return;
    const intervalSeconds = this.config()?.ping_interval_seconds || 30;
    this.sendPing(); // immediate ping, regardless of transport
    if (this.platform.isNative && this.backgroundLocation.supported) {
      void this.backgroundLocation.start((fix) => this.onBackgroundFix(fix, intervalSeconds), {
        title: 'Tower Rush',
        message: 'Tracking your location for the game.',
      });
    } else {
      this.timer = setInterval(() => this.sendPing(), intervalSeconds * 1000);
    }
    this.streaming.set(true);
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    void this.backgroundLocation.stop();
    this.streaming.set(false);
  }

  /** Background watcher fix: throttle to at most one ping per interval. */
  private onBackgroundFix(fix: BackgroundLocationFix, intervalSeconds: number): void {
    if (!this.hasConsent() || !this.config()?.tracking_enabled) {
      this.stop();
      return;
    }
    const now = Date.now();
    if (now - this.lastPingAt < intervalSeconds * 1000) return;
    this.lastPingAt = now;
    this.api
      .sendLocationPing({
        lat: fix.latitude,
        lng: fix.longitude,
        accuracy: fix.accuracy,
        recorded_at: fix.time ? new Date(fix.time).toISOString() : undefined,
      })
      .subscribe({
        // 403 = consent withdrawn elsewhere; 409 = tracking turned off.
        error: () => this.stop(),
      });
  }

  private sendPing(): void {
    if (!this.hasConsent() || !this.config()?.tracking_enabled) {
      this.stop();
      return;
    }
    this.lastPingAt = Date.now();
    this.geolocation
      .current({ enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 })
      .then((position) => {
        this.api
          .sendLocationPing({
            lat: position.coords.latitude,
            lng: position.coords.longitude,
            accuracy: position.coords.accuracy,
            recorded_at: new Date(position.timestamp).toISOString(),
          })
          .subscribe({
            error: () => this.stop(),
          });
      })
      .catch(() => undefined);
  }
}
