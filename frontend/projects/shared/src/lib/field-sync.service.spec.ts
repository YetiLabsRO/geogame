import 'fake-indexeddb/auto';

import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { IndexedDbQueueStore, LEGACY_STORAGE_KEY, bytesToDataUrl } from './field-queue-store';
import { FieldSyncService } from './field-sync.service';

/**
 * field-authoring-mode task 5.7 — offline-queued field edits persist
 * across reload and sync on reconnect, with failures surfaced for retry.
 *
 * tower-zone-media section 4 — the same contract, now over IndexedDB,
 * for captures far too large to have been base64 in `localStorage`.
 */
describe('FieldSyncService', () => {
  let service: FieldSyncService;
  let http: HttpTestingController;

  function configure(): void {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(FieldSyncService);
    http = TestBed.inject(HttpTestingController);
  }

  /** What a reload does: a fresh injector re-hydrating from disk. */
  async function reload(): Promise<void> {
    TestBed.resetTestingModule();
    configure();
    await service.ready;
  }

  beforeEach(async () => {
    localStorage.clear();
    await new IndexedDbQueueStore().clear();
    configure();
    await service.ready;
  });

  afterEach(async () => {
    http.verify();
    localStorage.clear();
    await new IndexedDbQueueStore().clear();
  });

  it('starts empty', () => {
    expect(service.items()).toEqual([]);
    expect(service.pendingCount()).toBe(0);
  });

  it('persists queued edits across a reload', async () => {
    service.enqueue('create-tower', {
      name: 'Fountain',
      lat: 46.51,
      lng: 23.52,
      authored_accuracy_m: 9.5,
      collection: 3,
      is_active: false,
    });
    expect(service.pendingCount()).toBe(1);

    await reload();

    expect(service.pendingCount()).toBe(1);
    expect(service.items()[0].kind).toBe('create-tower');
    expect(service.items()[0].payload['name']).toBe('Fountain');
  });

  it('replays a queued tower create on sync and confirms it', async () => {
    service.enqueue('create-tower', { name: 'Fountain', lat: 46.5, lng: 23.5 });

    const done = service.sync();
    await settle();
    const req = http.expectOne('/api/staff/towers/');
    expect(req.request.method).toBe('POST');
    expect(req.request.body.name).toBe('Fountain');
    req.flush({ id: 42, name: 'Fountain' });
    await done;

    expect(service.items()).toEqual([]);
    await reload();
    expect(service.items()).toEqual([]);
  });

  it('remaps queued media onto the confirmed server tower id', async () => {
    const towerEdit = service.enqueue('create-tower', {
      name: 'Fountain',
      lat: 46.5,
      lng: 23.5,
    });
    service.enqueue(
      'upload-media',
      { kind: 'IMAGE', caption: 'north face' },
      {
        subjectRef: towerEdit.localId, // tower has no server id while offline
        subject: 'towers',
        bytes: new ArrayBuffer(64),
        contentType: 'image/jpeg',
      },
    );

    const done = service.sync();
    await settle();
    http.expectOne('/api/staff/towers/').flush({ id: 42, name: 'Fountain' });
    await settle();
    const mediaReq = http.expectOne('/api/staff/towers/42/media/');
    expect(mediaReq.request.body.caption).toBe('north face');
    // Encoded at send time, from bytes that were never a string on disk.
    expect(mediaReq.request.body.file).toMatch(/^data:image\/jpeg;base64,/);
    mediaReq.flush({ id: 7, tower: 42 });
    await done;

    expect(service.items()).toEqual([]);
  });

  it('follows a zone drawn offline to its server id', async () => {
    const zoneEdit = service.enqueue('create-zone', {
      name: 'Old town',
      vertices: [
        [23.5, 46.5],
        [23.52, 46.5],
        [23.52, 46.52],
      ],
    });
    service.enqueue(
      'upload-media',
      { kind: 'AUDIO', caption: 'north gate', duration_seconds: 9 },
      {
        subjectRef: zoneEdit.localId,
        subject: 'zones',
        bytes: new ArrayBuffer(128),
        contentType: 'audio/webm',
      },
    );

    const done = service.sync();
    await settle();
    http.expectOne('/api/staff/zones/').flush({ id: 5, name: 'Old town' });
    await settle();
    const mediaReq = http.expectOne('/api/staff/zones/5/media/');
    expect(mediaReq.request.body.kind).toBe('AUDIO');
    expect(mediaReq.request.body.duration_seconds).toBe(9);
    mediaReq.flush({ id: 9, zone: 5 });
    await done;

    expect(service.items()).toEqual([]);
  });

  it('queues and replays a video-sized capture', async () => {
    // 6 MB: comfortably inside the documented video cap, and
    // comfortably outside anything `localStorage` could have held —
    // see the quota test below, which is the reason this store exists.
    const clip = new ArrayBuffer(6 * 1024 * 1024);
    service.enqueue(
      'upload-media',
      { kind: 'VIDEO', duration_seconds: 22 },
      { subjectRef: 12, subject: 'towers', bytes: clip, contentType: 'video/webm' },
    );

    await reload();
    expect(service.pendingCount()).toBe(1);
    expect(service.items()[0].bytes?.byteLength).toBe(6 * 1024 * 1024);

    const done = service.sync();
    await settle();
    const req = http.expectOne('/api/staff/towers/12/media/');
    expect(req.request.body.file).toMatch(/^data:video\/webm;base64,/);
    req.flush({ id: 3, tower: 12 });
    await done;

    expect(service.items()).toEqual([]);
  });

  it('is the point: that capture could not have been a localStorage string', () => {
    // Task 4.6 — the change is about the quota, so this asserts the
    // quota is really what the old implementation would have hit. If
    // `localStorage` ever grew to hold this, the migration to IndexedDB
    // would have been unnecessary and this test should say so.
    const asBase64 = bytesToDataUrl(new ArrayBuffer(6 * 1024 * 1024), 'video/webm');
    expect(() => {
      localStorage.setItem(
        LEGACY_STORAGE_KEY,
        JSON.stringify([{ kind: 'upload-photo', payload: { image: asBase64 } }]),
      );
    }).toThrow();
  });

  it('carries a queue left in localStorage by the old implementation', async () => {
    // Task 4.3 — a curator who updates the app mid-trip keeps their
    // captures; the alternative is silently stranding them.
    localStorage.setItem(
      LEGACY_STORAGE_KEY,
      JSON.stringify([
        {
          localId: 'local-old-1',
          kind: 'create-tower',
          payload: { name: 'Fountain', lat: 46.5, lng: 23.5 },
          status: 'pending',
          error: null,
          queuedAt: '2026-09-01T08:00:00.000Z',
        },
        {
          localId: 'local-old-2',
          kind: 'upload-photo',
          payload: { image: 'data:image/jpeg;base64,/9j/4AAQ', caption: 'north face' },
          towerRef: 'local-old-1',
          status: 'pending',
          error: null,
          queuedAt: '2026-09-01T08:00:05.000Z',
        },
      ]),
    );

    await reload();

    expect(service.pendingCount()).toBe(2);
    const [tower, photo] = service.items();
    expect(tower.kind).toBe('create-tower');
    expect(photo.kind).toBe('upload-media');
    expect(photo.subject).toBe('towers');
    expect(photo.subjectRef).toBe('local-old-1');
    expect(photo.contentType).toBe('image/jpeg');
    expect(photo.payload['caption']).toBe('north face');
    // Drained, not copied: a second reload must not double the queue.
    expect(localStorage.getItem(LEGACY_STORAGE_KEY)).toBeNull();

    await reload();
    expect(service.pendingCount()).toBe(2);
  });

  it('keeps a failed edit, surfaces the error, and retries it', async () => {
    const edit = service.enqueue('create-zone', {
      name: 'Old town',
      vertices: [
        [23.5, 46.5],
        [23.52, 46.5],
        [23.52, 46.52],
      ],
    });

    let done = service.sync();
    await settle();
    http
      .expectOne('/api/staff/zones/')
      .flush(
        { vertices: ['A zone needs at least 3 vertices.'] },
        { status: 400, statusText: 'Bad Request' },
      );
    await done;

    expect(service.failedCount()).toBe(1);
    const failed = service.items()[0];
    expect(failed.status).toBe('failed');
    expect(failed.error).toContain('vertices');

    // The failure survives a reload too — nothing is dropped unconfirmed.
    await reload();
    expect(service.failedCount()).toBe(1);

    done = Promise.resolve(service.retry(edit.localId)) as unknown as Promise<void>;
    await settle();
    http.expectOne('/api/staff/zones/').flush({ id: 5, name: 'Old town' });
    await settle();
    await done;

    expect(service.items()).toEqual([]);
  });

  it('keeps a rejected capture queued with the reason it was refused', async () => {
    // A curator who recorded something once, in a place they have
    // walked away from, must not lose it to a validation error.
    service.enqueue(
      'upload-media',
      { kind: 'VIDEO', duration_seconds: 47 },
      {
        subjectRef: 4,
        subject: 'towers',
        bytes: new ArrayBuffer(1024),
        contentType: 'video/webm',
      },
    );

    const done = service.sync();
    await settle();
    http
      .expectOne('/api/staff/towers/4/media/')
      .flush(
        { duration_seconds: ['Video clip may be at most 30 s; this one is 47 s.'] },
        { status: 400, statusText: 'Bad Request' },
      );
    await done;

    expect(service.failedCount()).toBe(1);
    expect(service.items()[0].error).toContain('at most 30 s');
    expect(service.items()[0].bytes?.byteLength).toBe(1024);

    await reload();
    expect(service.items()[0].bytes?.byteLength).toBe(1024);
  });
});

/**
 * Let the sync loop's pending work run.
 *
 * Yielding the macrotask queue, not just microtasks: each replayed item
 * waits on an IndexedDB write before the loop moves to the next, and
 * IndexedDB callbacks are not microtasks.
 */
async function settle(): Promise<void> {
  for (let i = 0; i < 20; i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}
