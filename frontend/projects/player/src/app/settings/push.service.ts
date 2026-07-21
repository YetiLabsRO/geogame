import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, firstValueFrom } from 'rxjs';

/**
 * Web Push opt-in / opt-out (realtime-and-notifications, 6.1).
 *
 * Registering is consent: the backend only ever sends to an active
 * subscription the user created here, and revoking (or clearing browser
 * permission) stops everything. The service worker `push-sw.js`
 * receives the pushes and shows the notifications (6.2).
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

const SERVICE_WORKER_URL = '/push-sw.js';

@Injectable({ providedIn: 'root' })
export class PushService {
  private readonly http = inject(HttpClient);

  /** Browser support for the whole Web Push chain. */
  get supported(): boolean {
    return (
      typeof navigator !== 'undefined' &&
      'serviceWorker' in navigator &&
      typeof window !== 'undefined' &&
      'PushManager' in window &&
      'Notification' in window
    );
  }

  get permission(): NotificationPermission | 'unsupported' {
    return this.supported ? Notification.permission : 'unsupported';
  }

  vapidKey(): Observable<{ public_key: string | null }> {
    return this.http.get<{ public_key: string | null }>('/api/push/vapid-key/');
  }

  subscriptions(): Observable<PushSubscriptionInfo[]> {
    return this.http.get<PushSubscriptionInfo[]>('/api/push/subscriptions/');
  }

  preferences(): Observable<NotificationPreferences> {
    return this.http.get<NotificationPreferences>('/api/push/preferences/');
  }

  updatePreferences(
    patch: Partial<NotificationPreferences>,
  ): Observable<NotificationPreferences> {
    return this.http.patch<NotificationPreferences>('/api/push/preferences/', patch);
  }

  /**
   * Full opt-in flow: explicit permission prompt → service-worker
   * registration → PushManager subscription → register (consent) with
   * the backend. Throws an Error with a user-readable message when any
   * step cannot complete.
   */
  async enable(): Promise<void> {
    if (!this.supported) {
      throw new Error('This browser does not support push notifications.');
    }
    const { public_key: key } = await firstValueFrom(this.vapidKey());
    if (!key) {
      throw new Error('Push notifications are not configured on the server.');
    }
    const permission = await Notification.requestPermission();
    if (permission !== 'granted') {
      throw new Error('Notification permission was not granted.');
    }
    const registration = await navigator.serviceWorker.register(SERVICE_WORKER_URL);
    await navigator.serviceWorker.ready;
    let subscription = await registration.pushManager.getSubscription();
    if (!subscription) {
      subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
    }
    const body = subscription.toJSON();
    await firstValueFrom(
      this.http.post('/api/push/subscriptions/', {
        endpoint: body.endpoint,
        keys: body.keys,
      }),
    );
  }

  /** Revoke consent: unsubscribe in the browser and on the backend. */
  async disable(): Promise<void> {
    let endpoint: string | undefined;
    if (this.supported) {
      const registration = await navigator.serviceWorker.getRegistration(
        SERVICE_WORKER_URL,
      );
      const subscription = await registration?.pushManager.getSubscription();
      if (subscription) {
        endpoint = subscription.endpoint;
        await subscription.unsubscribe();
      }
    }
    await firstValueFrom(
      this.http.delete('/api/push/subscriptions/', {
        body: endpoint ? { endpoint } : {},
      }),
    );
  }
}

/** Decode a base64url VAPID key into the bytes PushManager expects. */
function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64.length % 4)) % 4);
  const normalized = (base64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(normalized);
  const output = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) {
    output[i] = raw.charCodeAt(i);
  }
  return output;
}
