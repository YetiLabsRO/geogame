import { Injectable, inject, signal } from '@angular/core';

import { GameApiService, LocationConfig } from 'shared';

/**
 * Streams the player's position at the game-configured cadence
 * (live-location capability).
 *
 * The interval comes from the Session's effective
 * `location_ping_interval_seconds` — there is deliberately NO
 * player-facing control to change it. Streaming pauses whenever
 * tracking is disabled or consent is absent/withdrawn.
 */
@Injectable({ providedIn: 'root' })
export class LocationStreamService {
  private readonly api = inject(GameApiService);

  readonly config = signal<LocationConfig | null>(null);
  readonly hasConsent = signal(false);
  readonly streaming = signal(false);

  private timer: ReturnType<typeof setInterval> | null = null;

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
    if (this.timer !== null) return;
    const intervalSeconds = this.config()?.ping_interval_seconds || 30;
    this.sendPing();
    this.timer = setInterval(() => this.sendPing(), intervalSeconds * 1000);
    this.streaming.set(true);
  }

  stop(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
    this.streaming.set(false);
  }

  private sendPing(): void {
    if (!this.hasConsent() || !this.config()?.tracking_enabled) {
      this.stop();
      return;
    }
    if (!('geolocation' in navigator)) return;
    navigator.geolocation.getCurrentPosition(
      (position) => {
        this.api
          .sendLocationPing({
            lat: position.coords.latitude,
            lng: position.coords.longitude,
            accuracy: position.coords.accuracy,
            recorded_at: new Date(position.timestamp).toISOString(),
          })
          .subscribe({
            // 403 = consent withdrawn elsewhere; 409 = tracking turned off.
            error: () => this.stop(),
          });
      },
      () => undefined,
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 },
    );
  }
}
