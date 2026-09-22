import { Injectable } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import { NFC } from '@exxili/capacitor-nfc';
import type { NDEFMessages } from '@exxili/capacitor-nfc';

/** One NDEF record, payload already normalised to text. */
export interface NfcTokenRecord {
  type?: string;
  payload: string;
}

/**
 * Pull the capture token out of NDEF records, whichever transport
 * produced them (Web NFC, the native bridge, or a single manually-typed
 * value wrapped as one record): an absolute/relative URL whose path is
 * `/nfc/<token>/`, the custom scheme `cercetador://nfc/<token>`, or a
 * plain text token.
 */
export function extractNfcToken(records: NfcTokenRecord[]): string | null {
  for (const record of records) {
    const token = extractFromValue(record.payload);
    if (token) return token;
  }
  return null;
}

function extractFromValue(raw: string | null | undefined): string | null {
  if (!raw) return null;
  const value = raw.trim();
  if (!value) return null;
  const match = /\/nfc\/([^/?#]+)\/?(?:[?#].*)?$/.exec(value);
  if (match) {
    try {
      return decodeURIComponent(match[1]);
    } catch {
      return match[1];
    }
  }
  // Any other URI (http(s):, a different custom scheme, ...) is not one
  // of our capture links — don't treat the whole string as a token.
  if (/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) return null;
  return value;
}

interface NdefReaderLike {
  scan(options?: { signal?: AbortSignal }): Promise<void>;
  onreading: ((event: NdefReadingEventLike) => void) | null;
  onreadingerror: (() => void) | null;
}

interface NdefReadingEventLike {
  message: { records: { recordType: string; data?: BufferSource }[] };
}

/**
 * NFC tag reading (mobile-app D4/nfc-native-and-secure-links): Web NFC
 * (`NDEFReader`) where it's available (Android Chrome), `@exxili/capacitor-nfc`
 * inside the native shell (iOS + Android). Both resolve the same way — a
 * token string, ready for `POST /api/nfc/capture/`.
 */
@Injectable({ providedIn: 'root' })
export class NfcService {
  private readonly isNative = Capacitor.isNativePlatform();

  readonly supported = this.isNative || (typeof window !== 'undefined' && 'NDEFReader' in window);

  // NFCPlugin's onRead/onError return a plain unsubscribe function (no
  // PluginListenerHandle promise) — see @exxili/capacitor-nfc's definitions.
  private stopNativeRead: (() => void) | null = null;
  private stopNativeError: (() => void) | null = null;

  /** Resolves with the first tag's token; reject/abort via `signal`. */
  async scan(signal?: AbortSignal): Promise<string> {
    if (!this.supported) {
      throw new Error('NFC is not supported on this device.');
    }
    return this.isNative ? this.scanNative(signal) : this.scanWeb(signal);
  }

  async stop(): Promise<void> {
    if (this.isNative) {
      this.stopNativeRead?.();
      this.stopNativeRead = null;
      this.stopNativeError?.();
      this.stopNativeError = null;
      await NFC.cancelScan().catch(() => {});
    }
  }

  private scanNative(signal?: AbortSignal): Promise<string> {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (fn: () => void) => {
        if (settled) return;
        settled = true;
        signal?.removeEventListener('abort', onAbort);
        void this.stop();
        fn();
      };
      const onAbort = () => finish(() => reject(new DOMException('Scan aborted', 'AbortError')));
      signal?.addEventListener('abort', onAbort);

      this.stopNativeRead = NFC.onRead((data) => {
        const token = extractNfcToken(flattenNativeRecords(data.string()));
        if (token) finish(() => resolve(token));
      });
      this.stopNativeError = NFC.onError((error) => {
        finish(() => reject(new Error(error.error)));
      });
      NFC.startScan().catch((error) => finish(() => reject(error)));
    });
  }

  private scanWeb(signal?: AbortSignal): Promise<string> {
    return new Promise((resolve, reject) => {
      try {
        const reader = new (
          window as unknown as { NDEFReader: new () => NdefReaderLike }
        ).NDEFReader();
        reader.onreading = (event) => {
          const token = extractNfcToken(flattenWebRecords(event));
          if (token) resolve(token);
        };
        reader.onreadingerror = () => reject(new Error('NFC read failed.'));
        reader.scan({ signal }).catch((error) => reject(error));
      } catch (error) {
        reject(error as Error);
      }
    });
  }
}

/** Native payloads may arrive as a string, byte array, or `Uint8Array` — normalise to text. */
function normalizeNativePayload(payload: unknown): string {
  if (typeof payload === 'string') return payload;
  if (payload instanceof Uint8Array) return new TextDecoder().decode(payload);
  if (Array.isArray(payload)) return new TextDecoder().decode(Uint8Array.from(payload as number[]));
  return '';
}

function flattenNativeRecords(data: NDEFMessages): NfcTokenRecord[] {
  const records: NfcTokenRecord[] = [];
  for (const message of data.messages ?? []) {
    for (const record of message.records ?? []) {
      records.push({ type: record.type, payload: normalizeNativePayload(record.payload) });
    }
  }
  return records;
}

function flattenWebRecords(event: NdefReadingEventLike): NfcTokenRecord[] {
  const records: NfcTokenRecord[] = [];
  for (const record of event.message.records) {
    if (!record.data) continue;
    try {
      records.push({
        type: record.recordType,
        payload: new TextDecoder().decode(record.data as ArrayBuffer),
      });
    } catch {
      // Undecodable record — skip it, another record may still carry the token.
    }
  }
  return records;
}
