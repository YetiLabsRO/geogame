import { Injectable } from '@angular/core';
import { Capacitor, registerPlugin } from '@capacitor/core';
import type { BackgroundGeolocationPlugin } from '@capacitor-community/background-geolocation';

/**
 * `@capacitor-community/background-geolocation` ships no JS bundle — it
 * is used purely through `registerPlugin`, typed from its `definitions.d.ts`
 * (see its README).
 */
const BackgroundGeolocation = registerPlugin<BackgroundGeolocationPlugin>('BackgroundGeolocation');

export interface BackgroundLocationFix {
  latitude: number;
  longitude: number;
  accuracy: number;
  time: number | null;
}

export interface BackgroundLocationOptions {
  title?: string;
  message?: string;
}

/**
 * Background location watcher (mobile-app D4/live-location): native
 * only — the OS keeps delivering fixes while the app is backgrounded or
 * the screen is locked, showing the required Android foreground-service
 * notification. `supported` is `false` on the web; `LocationStreamService`
 * falls back to its foreground timer there.
 */
@Injectable({ providedIn: 'root' })
export class BackgroundLocationService {
  readonly supported = Capacitor.isNativePlatform();

  private watcherId: string | null = null;

  async start(
    onFix: (fix: BackgroundLocationFix) => void,
    options: BackgroundLocationOptions = {},
  ): Promise<void> {
    if (!this.supported) return;
    await this.stop();
    this.watcherId = await BackgroundGeolocation.addWatcher(
      {
        backgroundTitle: options.title ?? 'Tower Rush',
        backgroundMessage: options.message ?? 'Tracking your location for the game.',
        requestPermissions: true,
        stale: false,
        distanceFilter: 0,
      },
      (location, error) => {
        if (error || !location) return;
        onFix({
          latitude: location.latitude,
          longitude: location.longitude,
          accuracy: location.accuracy,
          time: location.time,
        });
      },
    );
  }

  async stop(): Promise<void> {
    if (!this.supported || !this.watcherId) return;
    const id = this.watcherId;
    this.watcherId = null;
    await BackgroundGeolocation.removeWatcher({ id }).catch(() => {});
  }
}
