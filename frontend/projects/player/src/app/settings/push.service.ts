import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { PushBridge, PushPermission } from 'shared';

/**
 * Web Push / FCM opt-in / opt-out facade (realtime-and-notifications 6.1,
 * mobile-app 2.5).
 *
 * Registering is consent: the backend only ever sends to an active
 * subscription the user created here, and revoking (or clearing OS/browser
 * permission) stops everything. The platform-specific transport — the
 * service worker (`push-sw.js`) + VAPID on the web, `@capacitor/push-notifications`
 * (FCM) on native — lives behind the `PushBridge` picked by
 * `providePushBridge()`; this facade keeps the same public API the
 * settings screen always used.
 */

export interface PushSubscriptionInfo {
  id: number;
  kind: 'WEBPUSH' | 'FCM';
  endpoint: string;
  created_at: string;
  active: boolean;
}

export interface NotificationPreferences {
  enabled: boolean;
  notify_steal: boolean;
  notify_conquer: boolean;
  notify_bonus: boolean;
}

@Injectable({ providedIn: 'root' })
export class PushService {
  private readonly http = inject(HttpClient);
  private readonly bridge = inject(PushBridge);

  /** Platform support for the whole push chain. */
  get supported(): boolean {
    return this.bridge.supported;
  }

  get permission(): PushPermission {
    return this.bridge.permission();
  }

  subscriptions(): Observable<PushSubscriptionInfo[]> {
    return this.http.get<PushSubscriptionInfo[]>('/api/push/subscriptions/');
  }

  preferences(): Observable<NotificationPreferences> {
    return this.http.get<NotificationPreferences>('/api/push/preferences/');
  }

  updatePreferences(patch: Partial<NotificationPreferences>): Observable<NotificationPreferences> {
    return this.http.patch<NotificationPreferences>('/api/push/preferences/', patch);
  }

  /**
   * Full opt-in flow: explicit permission prompt → transport registration
   * → consent recorded with the backend. Throws an Error with a
   * user-readable message when any step cannot complete.
   */
  enable(): Promise<void> {
    return this.bridge.enable();
  }

  /** Revoke consent: unregister the transport and on the backend. */
  disable(): Promise<void> {
    return this.bridge.disable();
  }
}
