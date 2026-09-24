import { Injectable, computed, effect, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { NetworkService } from './platform';
import {
  FieldEdit,
  FieldEditKind,
  FieldQueueStore,
  IndexedDbQueueStore,
  MediaSubject,
  bytesToDataUrl,
} from './field-queue-store';
import {
  AttachChallengePayload,
  CreateTowerPayload,
  CreateZonePayload,
  StaffApiService,
  UploadMediaPayload,
} from './staff-api.service';

/**
 * Offline capture queue for field authoring (field-authoring-mode tasks
 * 4.1 / 4.2).
 *
 * Edits captured while offline (tower drops, reference media, zones,
 * challenge links) are persisted client-side and replayed in capture
 * order against the ordinary staff REST APIs when the network returns.
 * An item is never dropped until the server confirms it; failures are
 * kept and surfaced for explicit retry or discard.
 *
 * Persistence is IndexedDB, holding captures as bytes — see
 * `field-queue-store`, which explains why `localStorage` could not
 * survive video. The queue's *semantics* are unchanged by that move.
 */

@Injectable({ providedIn: 'root' })
export class FieldSyncService {
  private readonly api = inject(StaffApiService);
  private readonly network = inject(NetworkService);
  private readonly store: FieldQueueStore = new IndexedDbQueueStore();

  readonly items = signal<FieldEdit[]>([]);
  readonly pendingCount = computed(() => this.items().filter((i) => i.status === 'pending').length);
  readonly failedCount = computed(() => this.items().filter((i) => i.status === 'failed').length);
  /** mobile-app 2.7: sourced from NetworkService (native Network plugin / browser events). */
  readonly online = this.network.online;
  readonly syncing = signal(false);

  /**
   * Resolves once the queue on disk has been read back.
   *
   * Reading IndexedDB is asynchronous, so a freshly constructed service
   * reports an empty queue for a moment. Anything that must not act on
   * that momentary emptiness — a sync, a test asserting what survived a
   * reload — waits on this first.
   */
  readonly ready: Promise<void>;

  private wasOnline = this.network.online();

  constructor() {
    this.ready = this.restore();
    // sync-on-reconnect, on both native (Network plugin) and the web.
    // One source of truth for connectivity: `navigator.onLine` is a lie
    // inside a Capacitor WebView, which is why NetworkService exists.
    effect(() => {
      const isOnline = this.network.online();
      if (isOnline && !this.wasOnline) {
        void this.sync();
      }
      this.wasOnline = isOnline;
    });
  }

  enqueue(
    kind: FieldEditKind,
    payload: Record<string, unknown>,
    options: {
      subjectRef?: number | string;
      subject?: MediaSubject;
      bytes?: ArrayBuffer;
      contentType?: string;
    } = {},
  ): FieldEdit {
    const item: FieldEdit = {
      localId: newLocalId(),
      kind,
      payload,
      subjectRef: options.subjectRef,
      subject: options.subject ?? (options.subjectRef === undefined ? undefined : 'towers'),
      bytes: options.bytes,
      contentType: options.contentType,
      status: 'pending',
      error: null,
      queuedAt: new Date().toISOString(),
    };
    this.items.update((items) => [...items, item]);
    void this.store.put(item);
    return item;
  }

  retry(localId: string): void {
    this.replace(localId, (item) => ({ ...item, status: 'pending', error: null }));
    void this.sync();
  }

  discard(localId: string): void {
    this.items.update((items) => items.filter((i) => i.localId !== localId));
    void this.store.remove(localId);
  }

  /**
   * Replay pending items in capture order. A confirmed create rewrites
   * dependent items' `subjectRef` to the server id it was given;
   * dependents whose subject has not synced yet are skipped and stay
   * pending for the next step of the same pass. Failures are marked and
   * kept.
   */
  async sync(): Promise<void> {
    if (this.syncing()) return;
    this.syncing.set(true);
    try {
      await this.ready;
      // Pull from the live queue each step: a confirmed create remaps
      // its dependents, which makes them processable in the SAME pass.
      // Every step removes or fails one item, so this terminates.
      for (;;) {
        const item = this.items().find(
          (i) => i.status === 'pending' && typeof i.subjectRef !== 'string',
        );
        if (!item) break;
        try {
          await this.replay(item);
          this.items.update((items) => items.filter((i) => i.localId !== item.localId));
          await this.store.remove(item.localId);
        } catch (err) {
          this.replace(item.localId, (i) => ({
            ...i,
            status: 'failed',
            error: describeError(err),
          }));
        }
      }
    } finally {
      this.syncing.set(false);
    }
  }

  private async restore(): Promise<void> {
    const stored = await this.store.load();
    if (stored.length) {
      // Anything captured in this tab before the read finished stays;
      // it is newer than what was on disk.
      const known = new Set(this.items().map((i) => i.localId));
      this.items.update((items) => [...stored.filter((i) => !known.has(i.localId)), ...items]);
    }
  }

  private replace(localId: string, update: (item: FieldEdit) => FieldEdit): void {
    let changed: FieldEdit | null = null;
    this.items.update((items) =>
      items.map((i) => {
        if (i.localId !== localId) return i;
        changed = update(i);
        return changed;
      }),
    );
    if (changed) void this.store.put(changed);
  }

  /** Point every item waiting on `localId` at the id the server gave it. */
  private confirmSubject(localId: string, serverId: number): void {
    const followers = this.items().filter((i) => i.subjectRef === localId);
    if (!followers.length) return;
    this.items.update((items) =>
      items.map((i) => (i.subjectRef === localId ? { ...i, subjectRef: serverId } : i)),
    );
    void this.store.putAll(followers.map((i) => ({ ...i, subjectRef: serverId })));
  }

  private async replay(item: FieldEdit): Promise<void> {
    switch (item.kind) {
      case 'create-tower': {
        const tower = await firstValueFrom(
          this.api.createTower(item.payload as unknown as CreateTowerPayload),
        );
        this.confirmSubject(item.localId, tower.id);
        break;
      }
      case 'create-zone': {
        const zone = await firstValueFrom(
          this.api.createZone(item.payload as unknown as CreateZonePayload),
        );
        // Media captured for a zone drawn offline follows it in, the
        // same way a tower's does.
        this.confirmSubject(item.localId, zone.id);
        break;
      }
      case 'adjust-zone': {
        const { id, vertices } = item.payload as {
          id: number;
          vertices: [number, number][];
        };
        await firstValueFrom(this.api.updateZone(id, { vertices }));
        break;
      }
      case 'upload-media': {
        const payload = { ...item.payload } as UploadMediaPayload;
        // Base64 at send time, not at queue time: the capture sat on
        // disk as bytes, and only the request needs it as a string.
        if (item.bytes) {
          payload.file = bytesToDataUrl(item.bytes, item.contentType ?? '');
        }
        await firstValueFrom(
          this.api.uploadMedia(item.subject ?? 'towers', item.subjectRef as number, payload),
        );
        break;
      }
      case 'attach-challenge':
        await firstValueFrom(
          this.api.attachChallenge(
            item.subjectRef as number,
            item.payload as unknown as AttachChallengePayload,
          ),
        );
        break;
    }
  }
}

function newLocalId(): string {
  return `local-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function describeError(err: unknown): string {
  if (err && typeof err === 'object') {
    const httpError = err as { status?: number; error?: unknown; message?: string };
    if (httpError.error) {
      try {
        const body =
          typeof httpError.error === 'string' ? httpError.error : JSON.stringify(httpError.error);
        return body.slice(0, 300);
      } catch {
        // fall through
      }
    }
    if (httpError.message) return httpError.message;
  }
  return 'Sync failed';
}
