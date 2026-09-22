import { Injectable } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import {
  Geolocation,
  Position as CapPosition,
  PositionOptions as CapPositionOptions,
} from '@capacitor/geolocation';

/** Browser `GeolocationPosition`-shaped result, from either backend. */
export interface PlatformPosition {
  coords: {
    latitude: number;
    longitude: number;
    accuracy: number;
  };
  timestamp: number;
}

export interface PlatformPositionOptions {
  enableHighAccuracy?: boolean;
  timeout?: number;
  maximumAge?: number;
}

export type GeolocationWatchCallback = (position: PlatformPosition) => void;
export type GeolocationErrorCallback = (error: unknown) => void;

/**
 * Foreground geolocation (mobile-app D4): `@capacitor/geolocation` on
 * native (prompting for permission first when needed), `navigator.geolocation`
 * on the web. Callers get the same `{coords:{latitude,longitude,accuracy},
 * timestamp}` shape either way and never branch on the runtime themselves.
 */
@Injectable({ providedIn: 'root' })
export class GeolocationService {
  private readonly isNative = Capacitor.isNativePlatform();

  private readonly webWatches = new Map<string, number>();
  private readonly nativeWatches = new Map<string, Promise<string>>();
  private nextId = 0;

  async current(options?: PlatformPositionOptions): Promise<PlatformPosition> {
    if (this.isNative) {
      await this.ensurePermission();
      const position = await Geolocation.getCurrentPosition(options as CapPositionOptions);
      return toPlatformPosition(position);
    }
    return new Promise((resolve, reject) => {
      if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
        reject(new Error('Geolocation is not available.'));
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (position) => resolve(toPlatformPositionFromWeb(position)),
        (error) => reject(error),
        options,
      );
    });
  }

  /** Start a position watch; returns an id to pass to `clearWatch()`. */
  watch(
    callback: GeolocationWatchCallback,
    errorCallback?: GeolocationErrorCallback,
    options?: PlatformPositionOptions,
  ): string {
    const id = `w${this.nextId++}`;
    if (this.isNative) {
      const promise = this.ensurePermission().then(() =>
        Geolocation.watchPosition(options as CapPositionOptions, (position, error) => {
          if (error) {
            errorCallback?.(error);
            return;
          }
          if (position) {
            callback(toPlatformPosition(position));
          }
        }),
      );
      promise.catch((error) => errorCallback?.(error));
      this.nativeWatches.set(id, promise);
      return id;
    }
    if (typeof navigator === 'undefined' || !('geolocation' in navigator)) {
      errorCallback?.(new Error('Geolocation is not available.'));
      return id;
    }
    const browserId = navigator.geolocation.watchPosition(
      (position) => callback(toPlatformPositionFromWeb(position)),
      (error) => errorCallback?.(error),
      options,
    );
    this.webWatches.set(id, browserId);
    return id;
  }

  clearWatch(id: string): void {
    const browserId = this.webWatches.get(id);
    if (browserId !== undefined) {
      this.webWatches.delete(id);
      navigator.geolocation.clearWatch(browserId);
      return;
    }
    const promise = this.nativeWatches.get(id);
    if (promise) {
      this.nativeWatches.delete(id);
      void promise.then((callbackId) => Geolocation.clearWatch({ id: callbackId })).catch(() => {});
    }
  }

  private async ensurePermission(): Promise<void> {
    const status = await Geolocation.checkPermissions();
    if (status.location === 'granted') return;
    await Geolocation.requestPermissions();
  }
}

function toPlatformPosition(position: CapPosition): PlatformPosition {
  return {
    coords: {
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      accuracy: position.coords.accuracy,
    },
    timestamp: position.timestamp,
  };
}

function toPlatformPositionFromWeb(position: GeolocationPosition): PlatformPosition {
  return {
    coords: {
      latitude: position.coords.latitude,
      longitude: position.coords.longitude,
      accuracy: position.coords.accuracy,
    },
    timestamp: position.timestamp,
  };
}
