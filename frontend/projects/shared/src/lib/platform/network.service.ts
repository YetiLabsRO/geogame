import { Injectable, signal } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import { Network } from '@capacitor/network';

/**
 * Connectivity signal (mobile-app D4): `@capacitor/network` on native,
 * the browser `online`/`offline` events on the web. `FieldSyncService`
 * flushes its offline queue whenever `online` flips to `true`.
 */
@Injectable({ providedIn: 'root' })
export class NetworkService {
  private readonly isNative = Capacitor.isNativePlatform();

  private readonly _online = signal(typeof navigator === 'undefined' || navigator.onLine);
  readonly online = this._online.asReadonly();

  constructor() {
    if (this.isNative) {
      void Network.getStatus().then((status) => this._online.set(status.connected));
      void Network.addListener('networkStatusChange', (status) =>
        this._online.set(status.connected),
      );
    } else if (typeof window !== 'undefined') {
      window.addEventListener('online', () => this._online.set(true));
      window.addEventListener('offline', () => this._online.set(false));
    }
  }
}
