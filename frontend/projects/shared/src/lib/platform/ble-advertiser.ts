import { registerPlugin } from '@capacitor/core';

/**
 * Local Capacitor plugin (mobile-app D4/5.3, `mode-dementors-ble`): no
 * maintained Capacitor plugin advertises over BLE, so the native
 * advertise loop is a small first-party plugin. This file only declares
 * its TypeScript contract — the Android/iOS implementation is written
 * against exactly this interface by the native-projects worker.
 */
export interface BleAdvertiserPlugin {
  isSupported(): Promise<{ supported: boolean }>;
  start(options: { serviceUuid: string; token: string }): Promise<void>;
  stop(): Promise<void>;
}

export const BleAdvertiser = registerPlugin<BleAdvertiserPlugin>('BleAdvertiser');
