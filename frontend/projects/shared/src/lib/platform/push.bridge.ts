import { HttpClient } from '@angular/common/http';
import { Injectable, Provider, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Capacitor } from '@capacitor/core';
import { PushNotifications } from '@capacitor/push-notifications';
import { Subject, firstValueFrom } from 'rxjs';

export type PushPermission = NotificationPermission | 'unsupported';

/** A push payload, normalised across the web and native transports. */
export interface PushBridgeNotification {
  title?: string;
  body?: string;
  data?: Record<string, unknown>;
}

const SERVICE_WORKER_URL = '/push-sw.js';

/**
 * Push transport abstraction (mobile-app D4/realtime-and-notifications):
 * `WebPushBridge` is today's service-worker + VAPID flow, `NativePushBridge`
 * registers for FCM through `@capacitor/push-notifications`. The player
 * `PushService` is a thin facade over whichever bridge `providePushBridge()`
 * picked, so the settings screen never branches on the runtime.
 */
@Injectable()
export abstract class PushBridge {
  abstract readonly supported: boolean;

  /** Native only: most recent foreground push — drive an in-app toast from it. */
  readonly lastNotification = signal<PushBridgeNotification | null>(null);
  /** Emits when the user taps a notification from the tray. */
  readonly notificationOpened = new Subject<PushBridgeNotification>();

  abstract permission(): PushPermission;
  abstract enable(): Promise<void>;
  abstract disable(): Promise<void>;
}

/** Web strategy: service worker (`/push-sw.js`) + VAPID `PushManager` subscription. */
@Injectable()
export class WebPushBridge extends PushBridge {
  private readonly http = inject(HttpClient);

  readonly supported =
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    typeof window !== 'undefined' &&
    'PushManager' in window &&
    'Notification' in window;

  permission(): PushPermission {
    return this.supported ? Notification.permission : 'unsupported';
  }

  async enable(): Promise<void> {
    if (!this.supported) {
      throw new Error('This browser does not support push notifications.');
    }
    const { public_key: key } = await firstValueFrom(
      this.http.get<{ public_key: string | null }>('/api/push/vapid-key/'),
    );
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

  async disable(): Promise<void> {
    let endpoint: string | undefined;
    if (this.supported) {
      const registration = await navigator.serviceWorker.getRegistration(SERVICE_WORKER_URL);
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

/** Native strategy: FCM device token through `@capacitor/push-notifications`. */
@Injectable()
export class NativePushBridge extends PushBridge {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  readonly supported = true;

  private _permission: PushPermission = 'default';
  private currentToken: string | null = null;
  private listenersReady: Promise<void> | null = null;

  constructor() {
    super();
    void PushNotifications.checkPermissions()
      .then((status) => (this._permission = toWebPermission(status.receive)))
      .catch(() => {});
  }

  permission(): PushPermission {
    return this._permission;
  }

  async enable(): Promise<void> {
    await this.ensureListeners();
    const status = await PushNotifications.requestPermissions();
    this._permission = toWebPermission(status.receive);
    if (status.receive !== 'granted') {
      throw new Error('Notification permission was not granted.');
    }
    await PushNotifications.register();
  }

  async disable(): Promise<void> {
    await firstValueFrom(
      this.http.delete('/api/push/subscriptions/', {
        body: this.currentToken ? { fcm_token: this.currentToken } : {},
      }),
    );
    await PushNotifications.unregister();
    this.currentToken = null;
  }

  private ensureListeners(): Promise<void> {
    if (!this.listenersReady) {
      this.listenersReady = this.registerListeners();
    }
    return this.listenersReady;
  }

  private async registerListeners(): Promise<void> {
    await PushNotifications.addListener('registration', (token) => {
      this.currentToken = token.value;
      this.http
        .post('/api/push/subscriptions/', { fcm_token: token.value })
        .subscribe({ error: () => {} });
    });
    await PushNotifications.addListener('registrationError', () => {
      // Async event with no pending caller to reject — the settings
      // screen re-checks `permission()`/`subscriptions()` after enable().
    });
    await PushNotifications.addListener('pushNotificationReceived', (notification) => {
      this.lastNotification.set({
        title: notification.title,
        body: notification.body,
        data: notification.data as Record<string, unknown> | undefined,
      });
    });
    await PushNotifications.addListener('pushNotificationActionPerformed', (action) => {
      const data = action.notification.data as { url?: string } | undefined;
      const payload: PushBridgeNotification = {
        title: action.notification.title,
        body: action.notification.body,
        data,
      };
      this.notificationOpened.next(payload);
      if (data?.url) {
        void this.router.navigateByUrl(data.url);
      }
    });
  }
}

/** Picks `NativePushBridge` inside the Capacitor shell, `WebPushBridge` otherwise. */
export function providePushBridge(): Provider {
  return {
    provide: PushBridge,
    useFactory: () => (Capacitor.isNativePlatform() ? new NativePushBridge() : new WebPushBridge()),
  };
}

function toWebPermission(receive: string): PushPermission {
  if (receive === 'granted') return 'granted';
  if (receive === 'denied') return 'denied';
  return 'default';
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
