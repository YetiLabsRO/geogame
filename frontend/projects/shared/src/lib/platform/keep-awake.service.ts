import { Injectable } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import { KeepAwake } from '@capacitor-community/keep-awake';

/**
 * Keep the screen on (mobile-app D4): `@capacitor-community/keep-awake`
 * on native, `navigator.wakeLock` on the web — re-acquired on
 * `visibilitychange` since the web Wake Lock API silently releases
 * whenever the tab is hidden.
 */
@Injectable({ providedIn: 'root' })
export class KeepAwakeService {
  private readonly isNative = Capacitor.isNativePlatform();

  private webLock: WakeLockSentinel | null = null;
  private wantsAwake = false;
  private listening = false;

  private readonly onVisibility = () => {
    if (this.wantsAwake && document.visibilityState === 'visible') {
      void this.acquireWeb();
    }
  };

  async keepAwake(): Promise<void> {
    this.wantsAwake = true;
    if (this.isNative) {
      await KeepAwake.keepAwake().catch(() => {});
      return;
    }
    this.ensureVisibilityListener();
    await this.acquireWeb();
  }

  async allowSleep(): Promise<void> {
    this.wantsAwake = false;
    if (this.isNative) {
      await KeepAwake.allowSleep().catch(() => {});
      return;
    }
    if (this.webLock) {
      const lock = this.webLock;
      this.webLock = null;
      await lock.release().catch(() => {});
    }
  }

  private ensureVisibilityListener(): void {
    if (this.listening || typeof document === 'undefined') return;
    this.listening = true;
    document.addEventListener('visibilitychange', this.onVisibility);
  }

  private async acquireWeb(): Promise<void> {
    if (typeof navigator === 'undefined' || !('wakeLock' in navigator)) return;
    try {
      this.webLock = await navigator.wakeLock.request('screen');
    } catch {
      this.webLock = null;
    }
  }
}
