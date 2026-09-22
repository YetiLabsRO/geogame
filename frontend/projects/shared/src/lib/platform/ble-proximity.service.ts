import { Injectable } from '@angular/core';
import { BleClient } from '@capacitor-community/bluetooth-le';
import { Capacitor } from '@capacitor/core';

import { BleAdvertiser } from './ble-advertiser';

/** Fixed 128-bit service UUID the game's proximity substrate advertises under. */
export const PROXIMITY_SERVICE_UUID = '6f3a2b10-9c4d-4e7f-8a21-5d2c1e0b4a77';

export interface BleProximityBridge {
  capable(): Promise<boolean>;
  startAdvertising(token: string): Promise<void>;
  stopAdvertising(): Promise<void>;
  startScan(onSeen: (token: string, rssi: number) => void): Promise<void>;
  stopScan(): Promise<void>;
}

class WebBleProximityBridge implements BleProximityBridge {
  async capable(): Promise<boolean> {
    return false;
  }
  async startAdvertising(): Promise<void> {
    // Web Bluetooth cannot advertise — the Dementors screen keeps its
    // simulator panel as the only input.
  }
  async stopAdvertising(): Promise<void> {}
  async startScan(): Promise<void> {}
  async stopScan(): Promise<void> {}
}

class NativeBleProximityBridge implements BleProximityBridge {
  private initialized: Promise<void> | null = null;

  async capable(): Promise<boolean> {
    try {
      const { supported } = await BleAdvertiser.isSupported();
      if (!supported) return false;
      await this.ensureInitialized();
      return true;
    } catch {
      return false;
    }
  }

  async startAdvertising(token: string): Promise<void> {
    await BleAdvertiser.start({ serviceUuid: PROXIMITY_SERVICE_UUID, token });
  }

  async stopAdvertising(): Promise<void> {
    await BleAdvertiser.stop().catch(() => {});
  }

  async startScan(onSeen: (token: string, rssi: number) => void): Promise<void> {
    await this.ensureInitialized();
    await BleClient.requestLEScan(
      { services: [PROXIMITY_SERVICE_UUID], allowDuplicates: true },
      (result) => {
        const data = result.serviceData?.[PROXIMITY_SERVICE_UUID];
        if (!data || typeof result.rssi !== 'number') return;
        const token = decodeUtf8(data);
        if (token) onSeen(token, result.rssi);
      },
    );
  }

  async stopScan(): Promise<void> {
    await BleClient.stopLEScan().catch(() => {});
  }

  private ensureInitialized(): Promise<void> {
    if (!this.initialized) {
      this.initialized = BleClient.initialize();
    }
    return this.initialized;
  }
}

function decodeUtf8(data: DataView): string {
  return new TextDecoder().decode(
    data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength),
  );
}

/**
 * BLE proximity substrate bridge (mobile-app D4/5.3, `ble-proximity`):
 * web reports `capable() === false` and no-ops everything else; native
 * advertises through the local `BleAdvertiser` plugin and scans through
 * `@capacitor-community/bluetooth-le`, both scoped to `PROXIMITY_SERVICE_UUID`.
 */
@Injectable({ providedIn: 'root' })
export class BleProximityService implements BleProximityBridge {
  private readonly impl: BleProximityBridge = Capacitor.isNativePlatform()
    ? new NativeBleProximityBridge()
    : new WebBleProximityBridge();

  capable(): Promise<boolean> {
    return this.impl.capable();
  }

  startAdvertising(token: string): Promise<void> {
    return this.impl.startAdvertising(token);
  }

  stopAdvertising(): Promise<void> {
    return this.impl.stopAdvertising();
  }

  startScan(onSeen: (token: string, rssi: number) => void): Promise<void> {
    return this.impl.startScan(onSeen);
  }

  stopScan(): Promise<void> {
    return this.impl.stopScan();
  }
}
