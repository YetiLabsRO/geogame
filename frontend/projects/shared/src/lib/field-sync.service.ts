import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import {
  AttachChallengePayload,
  CreateTowerPayload,
  CreateZonePayload,
  StaffApiService,
} from './staff-api.service';

/**
 * Offline capture queue for field authoring (field-authoring-mode tasks
 * 4.1 / 4.2).
 *
 * Edits captured while offline (tower drops, reference photos, zones,
 * challenge links) are persisted client-side and replayed in capture
 * order against the ordinary staff REST APIs when the network returns.
 * An item is never dropped until the server confirms it; failures are
 * kept and surfaced for explicit retry or discard.
 *
 * Persistence is `localStorage` (survives reload; photos are compressed
 * client-side before queueing so entries stay small). design.md names
 * IndexedDB — localStorage keeps the same reload-surviving contract with
 * far less machinery for a single-author queue; see Implementation notes.
 */

export type FieldEditKind =
  | 'create-tower'
  | 'create-zone'
  | 'adjust-zone'
  | 'upload-photo'
  | 'attach-challenge';

export interface FieldEdit {
  /** Client id; also how dependent items reference a queued tower. */
  localId: string;
  kind: FieldEditKind;
  payload: Record<string, unknown>;
  /**
   * For photo / challenge items: the target tower — a server id
   * (number) or the `localId` (string) of a queued create-tower whose
   * server id is not known yet.
   */
  towerRef?: number | string;
  status: 'pending' | 'failed';
  error: string | null;
  queuedAt: string;
}

const STORAGE_KEY = 'cercetador.field-queue.v1';

@Injectable({ providedIn: 'root' })
export class FieldSyncService {
  private readonly api = inject(StaffApiService);

  readonly items = signal<FieldEdit[]>(this.load());
  readonly pendingCount = computed(
    () => this.items().filter((i) => i.status === 'pending').length,
  );
  readonly failedCount = computed(
    () => this.items().filter((i) => i.status === 'failed').length,
  );
  readonly online = signal(typeof navigator === 'undefined' || navigator.onLine);
  readonly syncing = signal(false);

  constructor() {
    if (typeof window !== 'undefined') {
      window.addEventListener('online', () => {
        this.online.set(true);
        void this.sync(); // sync-on-reconnect
      });
      window.addEventListener('offline', () => this.online.set(false));
    }
  }

  enqueue(
    kind: FieldEditKind,
    payload: Record<string, unknown>,
    towerRef?: number | string,
  ): FieldEdit {
    const item: FieldEdit = {
      localId: newLocalId(),
      kind,
      payload,
      towerRef,
      status: 'pending',
      error: null,
      queuedAt: new Date().toISOString(),
    };
    this.items.update((items) => [...items, item]);
    this.persist();
    return item;
  }

  retry(localId: string): void {
    this.items.update((items) =>
      items.map((i) =>
        i.localId === localId ? { ...i, status: 'pending' as const, error: null } : i,
      ),
    );
    this.persist();
    void this.sync();
  }

  discard(localId: string): void {
    this.items.update((items) => items.filter((i) => i.localId !== localId));
    this.persist();
  }

  /**
   * Replay pending items in capture order. A create-tower success
   * rewrites dependent items' `towerRef` to the confirmed server id;
   * dependents whose tower has not synced yet are skipped (they stay
   * pending for the next pass). Failures are marked and kept.
   */
  async sync(): Promise<void> {
    if (this.syncing()) return;
    this.syncing.set(true);
    try {
      // Pull from the live queue each step: a confirmed create-tower
      // remaps its dependents, which makes them processable in the SAME
      // pass. Every step removes or fails one item, so this terminates.
      for (;;) {
        const item = this.items().find(
          (i) => i.status === 'pending' && typeof i.towerRef !== 'string',
        );
        if (!item) break;
        try {
          await this.replay(item);
          this.items.update((items) =>
            items.filter((i) => i.localId !== item.localId),
          );
        } catch (err) {
          this.items.update((items) =>
            items.map((i) =>
              i.localId === item.localId
                ? { ...i, status: 'failed' as const, error: describeError(err) }
                : i,
            ),
          );
        }
        this.persist();
      }
    } finally {
      this.syncing.set(false);
    }
  }

  private async replay(item: FieldEdit): Promise<void> {
    switch (item.kind) {
      case 'create-tower': {
        const tower = await firstValueFrom(
          this.api.createTower(item.payload as unknown as CreateTowerPayload),
        );
        // Local-id → server-id remap for queued photos / challenge links.
        this.items.update((items) =>
          items.map((i) =>
            i.towerRef === item.localId ? { ...i, towerRef: tower.id } : i,
          ),
        );
        break;
      }
      case 'create-zone':
        await firstValueFrom(
          this.api.createZone(item.payload as unknown as CreateZonePayload),
        );
        break;
      case 'adjust-zone': {
        const { id, vertices } = item.payload as {
          id: number;
          vertices: [number, number][];
        };
        await firstValueFrom(this.api.updateZone(id, { vertices }));
        break;
      }
      case 'upload-photo':
        await firstValueFrom(
          this.api.uploadTowerPhoto(
            item.towerRef as number,
            item.payload as { image: string; caption?: string },
          ),
        );
        break;
      case 'attach-challenge':
        await firstValueFrom(
          this.api.attachChallenge(
            item.towerRef as number,
            item.payload as unknown as AttachChallengePayload,
          ),
        );
        break;
    }
  }

  private load(): FieldEdit[] {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? (JSON.parse(raw) as FieldEdit[]) : [];
    } catch {
      return [];
    }
  }

  private persist(): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(this.items()));
    } catch {
      // Storage full/unavailable: the in-memory queue still syncs.
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
          typeof httpError.error === 'string'
            ? httpError.error
            : JSON.stringify(httpError.error);
        return body.slice(0, 300);
      } catch {
        // fall through
      }
    }
    if (httpError.message) return httpError.message;
  }
  return 'Sync failed';
}
