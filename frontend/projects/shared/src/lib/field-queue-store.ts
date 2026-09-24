/**
 * Durable storage for the field-authoring capture queue.
 *
 * The queue used to persist to `localStorage` as base64 JSON. That was
 * the right trade while the only capture was a photo the client had
 * already downscaled. Video ends it: `localStorage` is a ~5 MB
 * per-origin quota of *strings*, and base64 inflates by about a third,
 * so a single short clip does not fit. The failure mode is the worst
 * kind — a `QuotaExceededError` thrown at the moment a curator saves,
 * in a field, offline, with nowhere to put the capture that was the
 * whole point of the queue.
 *
 * So captures live here as raw bytes in IndexedDB, and are
 * base64-encoded at *send* time rather than at queue time. One record
 * per edit, keyed by its local id, so adding one capture does not
 * rewrite the others.
 *
 * The bytes are an `ArrayBuffer` rather than a `Blob`. A `Blob` would
 * be the more natural shape — lazily backed, never fully in memory —
 * but it only survives IndexedDB where structured clone knows about
 * it, which is not everywhere this code runs. An `ArrayBuffer` is
 * cloneable everywhere, and at a 48 MB ceiling the laziness buys
 * nothing worth an environment dependency.
 *
 * Where IndexedDB is unavailable — a locked-down private window, a
 * server-side render — every method degrades to a no-op and `load()`
 * returns nothing. The in-memory queue still syncs for as long as the
 * tab lives; what is lost is only surviving a reload, which is exactly
 * what was unavailable anyway.
 */

export type FieldEditKind =
  | 'create-tower'
  | 'create-zone'
  | 'adjust-zone'
  | 'upload-media'
  | 'attach-challenge';

/** Which endpoint family an edit's subject lives under. */
export type MediaSubject = 'towers' | 'zones';

export interface FieldEdit {
  /** Client id; also how dependent items reference a queued subject. */
  localId: string;
  kind: FieldEditKind;
  payload: Record<string, unknown>;
  /**
   * For media / challenge items: the target tower or zone — a server id
   * (number) or the `localId` (string) of a queued create whose server
   * id is not known yet.
   */
  subjectRef?: number | string;
  /** Which of the two `subjectRef` names. Defaults to a tower. */
  subject?: MediaSubject;
  /**
   * `upload-media` only: the capture itself. Held as bytes rather than
   * as a base64 string — see this module's note on quota.
   */
  bytes?: ArrayBuffer;
  /** The captured bytes' media type, e.g. `audio/webm`. */
  contentType?: string;
  status: 'pending' | 'failed';
  error: string | null;
  queuedAt: string;
}

const DB_NAME = 'cercetador-field';
const DB_VERSION = 1;
const STORE = 'queue';

/** Where the queue lived before IndexedDB; drained once, on first load. */
export const LEGACY_STORAGE_KEY = 'cercetador.field-queue.v1';

export interface FieldQueueStore {
  load(): Promise<FieldEdit[]>;
  put(item: FieldEdit): Promise<void>;
  putAll(items: FieldEdit[]): Promise<void>;
  remove(localId: string): Promise<void>;
  clear(): Promise<void>;
}

export class IndexedDbQueueStore implements FieldQueueStore {
  private opening: Promise<IDBDatabase | null> | null = null;

  async load(): Promise<FieldEdit[]> {
    const carried = drainLegacyQueue();
    if (carried.length) {
      await this.putAll(carried);
    }
    const db = await this.open();
    if (!db) return carried;
    const stored = await request<FieldEdit[]>(
      db,
      'readonly',
      (store) => store.getAll() as IDBRequest<FieldEdit[]>,
    );
    // Capture order is the replay order, and `getAll` returns rows in
    // key order, which is not it.
    return (stored ?? []).sort((a, b) => a.queuedAt.localeCompare(b.queuedAt));
  }

  async put(item: FieldEdit): Promise<void> {
    const db = await this.open();
    if (!db) return;
    await request(db, 'readwrite', (store) => store.put(item));
  }

  async putAll(items: FieldEdit[]): Promise<void> {
    if (!items.length) return;
    const db = await this.open();
    if (!db) return;
    await transaction(db, 'readwrite', (store) => {
      for (const item of items) store.put(item);
    });
  }

  async remove(localId: string): Promise<void> {
    const db = await this.open();
    if (!db) return;
    await request(db, 'readwrite', (store) => store.delete(localId));
  }

  async clear(): Promise<void> {
    const db = await this.open();
    if (!db) return;
    await request(db, 'readwrite', (store) => store.clear());
  }

  private open(): Promise<IDBDatabase | null> {
    if (this.opening) return this.opening;
    this.opening = new Promise((resolve) => {
      if (typeof indexedDB === 'undefined') {
        resolve(null);
        return;
      }
      let open: IDBOpenDBRequest;
      try {
        open = indexedDB.open(DB_NAME, DB_VERSION);
      } catch {
        resolve(null);
        return;
      }
      open.onupgradeneeded = () => {
        const db = open.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE, { keyPath: 'localId' });
        }
      };
      open.onsuccess = () => resolve(open.result);
      open.onerror = () => resolve(null);
      open.onblocked = () => resolve(null);
    });
    return this.opening;
  }
}

function transaction(
  db: IDBDatabase,
  mode: IDBTransactionMode,
  work: (store: IDBObjectStore) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    work(tx.objectStore(STORE));
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

function request<T>(
  db: IDBDatabase,
  mode: IDBTransactionMode,
  work: (store: IDBObjectStore) => IDBRequest,
): Promise<T | undefined> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const req = work(tx.objectStore(STORE));
    req.onsuccess = () => resolve(req.result as T);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

/**
 * Take over a queue left in `localStorage` by the previous
 * implementation, once, and clear it.
 *
 * A curator who updates the app mid-trip has captures in the old place
 * and no way to get them back if this does not run. Photos were stored
 * as data URLs, which decode straight to the blob the new shape wants;
 * anything that will not decode is carried across as it is rather than
 * dropped, so it surfaces as a sync failure the curator can see instead
 * of vanishing quietly.
 */
export function drainLegacyQueue(): FieldEdit[] {
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(LEGACY_STORAGE_KEY);
  } catch {
    return [];
  }
  if (!raw) return [];

  let parsed: LegacyEdit[];
  try {
    parsed = JSON.parse(raw) as LegacyEdit[];
  } catch {
    parsed = [];
  }
  try {
    localStorage.removeItem(LEGACY_STORAGE_KEY);
  } catch {
    // Nothing to do: worst case it is read again and re-put by localId.
  }
  return parsed.map(carryOver).filter((item): item is FieldEdit => item !== null);
}

interface LegacyEdit {
  localId: string;
  kind: string;
  payload: Record<string, unknown>;
  towerRef?: number | string;
  status: 'pending' | 'failed';
  error: string | null;
  queuedAt: string;
}

function carryOver(old: LegacyEdit): FieldEdit | null {
  if (!old || typeof old.localId !== 'string') return null;
  const base: FieldEdit = {
    localId: old.localId,
    kind: old.kind as FieldEditKind,
    payload: old.payload ?? {},
    subjectRef: old.towerRef,
    subject: old.towerRef === undefined ? undefined : 'towers',
    status: old.status === 'failed' ? 'failed' : 'pending',
    error: old.error ?? null,
    queuedAt: old.queuedAt ?? new Date().toISOString(),
  };
  if (old.kind !== 'upload-photo') return base;

  const image = old.payload?.['image'];
  const decoded = typeof image === 'string' ? dataUrlToBytes(image) : null;
  return {
    ...base,
    kind: 'upload-media',
    bytes: decoded?.bytes,
    contentType: decoded?.contentType,
    payload: {
      kind: 'IMAGE',
      caption: old.payload?.['caption'] ?? '',
      // A capture whose data URL will not decode keeps it, so the
      // server refuses it out loud rather than it disappearing here.
      ...(decoded ? {} : { file: image }),
    },
  };
}

/** Decode a `data:<type>;base64,...` URL, or null if it is not one. */
export function dataUrlToBytes(
  dataUrl: string,
): { bytes: ArrayBuffer; contentType: string } | null {
  const match = /^data:([^;,]*)(;[^,]*)?,(.*)$/s.exec(dataUrl);
  if (!match) return null;
  const [, contentType, parameters, body] = match;
  if (!parameters?.includes('base64')) return null;
  try {
    const binary = atob(body);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return {
      bytes: bytes.buffer,
      contentType: contentType || 'application/octet-stream',
    };
  } catch {
    return null;
  }
}

/**
 * Encode captured bytes as the `data:` URL the upload endpoint accepts.
 *
 * Chunked, because `String.fromCharCode(...bytes)` on a video-sized
 * array is a call with several million arguments, which overflows the
 * stack on the exact input this whole change exists to support.
 */
export function bytesToDataUrl(bytes: ArrayBuffer, contentType: string): string {
  const view = new Uint8Array(bytes);
  const CHUNK = 0x8000;
  let binary = '';
  for (let i = 0; i < view.length; i += CHUNK) {
    binary += String.fromCharCode(...view.subarray(i, i + CHUNK));
  }
  return `data:${contentType || 'application/octet-stream'};base64,${btoa(binary)}`;
}

/** Read a picked file or a recorder's output into the bytes the queue holds. */
export async function captureToBytes(
  blob: Blob,
): Promise<{ bytes: ArrayBuffer; contentType: string }> {
  return { bytes: await blob.arrayBuffer(), contentType: blob.type };
}
