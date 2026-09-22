import { Location } from '@angular/common';
import { Injectable, NgZone, inject } from '@angular/core';
import { Router } from '@angular/router';
import { App } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';

/** Tab-root paths: hardware back exits the app from here instead of going further back. */
const TAB_ROOT_PATHS = ['/', '/team', '/history', '/ledger', '/login', '/pick-session'];

/**
 * Deep links and the Android hardware back button (mobile-app D4/D7):
 * routes `appUrlOpen` (App Links and the `cercetador://` custom scheme)
 * straight into the matching in-app route, and makes back navigate
 * history or exit at a tab root. Native only — started once from the
 * `provideAppInitializer` in `app.config.ts`.
 */
@Injectable({ providedIn: 'root' })
export class DeepLinkService {
  private readonly router = inject(Router);
  private readonly location = inject(Location);
  private readonly zone = inject(NgZone);

  private initialized = false;

  async init(): Promise<void> {
    if (this.initialized || !Capacitor.isNativePlatform()) return;
    this.initialized = true;

    await App.addListener('appUrlOpen', ({ url }) => {
      const path = this.extractPath(url);
      if (!path) return;
      this.zone.run(() => {
        void this.router.navigateByUrl(path);
      });
    });

    await App.addListener('backButton', () => {
      this.zone.run(() => {
        const current = this.location.path(false).split('?')[0] || '/';
        if (TAB_ROOT_PATHS.includes(current)) {
          void App.exitApp();
        } else {
          this.location.back();
        }
      });
    });
  }

  private extractPath(url: string): string | null {
    const scheme = 'cercetador://';
    if (url.startsWith(scheme)) {
      const rest = url.slice(scheme.length);
      return rest.startsWith('/') ? rest : `/${rest}`;
    }
    try {
      const parsed = new URL(url);
      return parsed.pathname + parsed.search;
    } catch {
      return null;
    }
  }
}
