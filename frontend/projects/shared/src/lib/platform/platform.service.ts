import { Injectable, computed, inject, signal } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import { Preferences } from '@capacitor/preferences';

import { APP_CONFIG } from './app-config';

/** `@capacitor/preferences` key for the debug API-origin override (D3). */
const OVERRIDE_KEY = 'tr.apiBaseUrl';

export type AppPlatform = 'web' | 'android' | 'ios';

/**
 * Runtime platform facts (mobile-app D2/D3/D4): whether the app is
 * running inside the Capacitor shell, which OS, and the effective API
 * origin every relative request/media URL should resolve against.
 *
 * `apiBaseUrl()` resolves, in order: an in-memory debug override (loaded
 * from `@capacitor/preferences` on native at startup) → the native origin
 * when running inside the shell → the web (same-origin) origin otherwise.
 */
@Injectable({ providedIn: 'root' })
export class PlatformService {
  private readonly config = inject(APP_CONFIG);

  readonly isNative = Capacitor.isNativePlatform();
  readonly platform: AppPlatform = Capacitor.getPlatform() as AppPlatform;

  private readonly _override = signal<string | null>(null);

  constructor() {
    if (this.isNative) {
      void Preferences.get({ key: OVERRIDE_KEY }).then(({ value }) => {
        if (value) {
          this._override.set(value);
        }
      });
    }
  }

  /** The effective origin to prefix relative `/`-URLs with (`''` on the web). */
  readonly apiBaseUrl = computed(
    () =>
      this._override() ?? (this.isNative ? this.config.nativeApiBaseUrl : this.config.apiBaseUrl),
  );

  /**
   * Set (or clear, with `null`) a debug server override. Persisted on
   * native so it survives an app restart; kept in-memory only on the web.
   */
  async setApiBaseUrlOverride(url: string | null): Promise<void> {
    this._override.set(url);
    if (!this.isNative) return;
    if (url) {
      await Preferences.set({ key: OVERRIDE_KEY, value: url });
    } else {
      await Preferences.remove({ key: OVERRIDE_KEY });
    }
  }

  /**
   * Prefix a relative `/`-path (e.g. a tower photo's `/media/...` URL)
   * with the effective API origin. Absolute URLs (and `data:`/`blob:`
   * URIs) pass through unchanged.
   */
  mediaUrl(path: string | null | undefined): string {
    if (!path) return '';
    if (/^[a-z][a-z0-9+.-]*:/i.test(path)) {
      return path; // already absolute (http(s):, data:, blob:, ...)
    }
    const base = this.apiBaseUrl();
    if (!base) return path;
    return path.startsWith('/') ? `${base}${path}` : `${base}/${path}`;
  }
}
