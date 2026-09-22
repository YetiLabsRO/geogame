import { Injectable } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import { Haptics, ImpactStyle, NotificationType } from '@capacitor/haptics';

export type HapticImpactStyle = 'light' | 'medium' | 'heavy';
export type HapticNotificationType = 'success' | 'warning' | 'error';

/**
 * Tactile feedback for game events (mobile-app D4): `@capacitor/haptics`
 * on native, `navigator.vibrate` on the web where the browser offers it
 * (otherwise a silent no-op — never throws).
 */
@Injectable({ providedIn: 'root' })
export class HapticsService {
  private readonly isNative = Capacitor.isNativePlatform();

  impact(style: HapticImpactStyle): void {
    if (this.isNative) {
      void Haptics.impact({ style: toImpactStyle(style) }).catch(() => {});
      return;
    }
    this.vibrateWeb(style === 'heavy' ? 40 : style === 'medium' ? 25 : 12);
  }

  notify(type: HapticNotificationType): void {
    if (this.isNative) {
      void Haptics.notification({ type: toNotificationType(type) }).catch(() => {});
      return;
    }
    this.vibrateWeb(type === 'error' ? [30, 40, 30] : type === 'warning' ? [20, 30] : 15);
  }

  vibrate(pattern: number | number[]): void {
    if (this.isNative) {
      const duration = Array.isArray(pattern) ? pattern.reduce((sum, ms) => sum + ms, 0) : pattern;
      void Haptics.vibrate({ duration }).catch(() => {});
      return;
    }
    this.vibrateWeb(pattern);
  }

  private vibrateWeb(pattern: number | number[]): void {
    if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
      navigator.vibrate(pattern);
    }
  }
}

function toImpactStyle(style: HapticImpactStyle): ImpactStyle {
  switch (style) {
    case 'light':
      return ImpactStyle.Light;
    case 'medium':
      return ImpactStyle.Medium;
    case 'heavy':
      return ImpactStyle.Heavy;
  }
}

function toNotificationType(type: HapticNotificationType): NotificationType {
  switch (type) {
    case 'success':
      return NotificationType.Success;
    case 'warning':
      return NotificationType.Warning;
    case 'error':
      return NotificationType.Error;
  }
}
