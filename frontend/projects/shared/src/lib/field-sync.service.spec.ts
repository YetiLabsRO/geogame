import { provideHttpClient } from '@angular/common/http';
import {
  HttpTestingController,
  provideHttpClientTesting,
} from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { FieldSyncService } from './field-sync.service';

/**
 * field-authoring-mode task 5.7 — offline-queued field edits persist
 * across reload and sync on reconnect, with failures surfaced for retry.
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

  beforeEach(() => {
    localStorage.clear();
    configure();
  });

  afterEach(() => {
    http.verify();
    localStorage.clear();
  });

  it('starts empty', () => {
    expect(service.items()).toEqual([]);
    expect(service.pendingCount()).toBe(0);
  });

  it('persists queued edits across a reload', () => {
    service.enqueue('create-tower', {
      name: 'Fountain',
      lat: 46.51,
      lng: 23.52,
      authored_accuracy_m: 9.5,
      collection: 3,
      is_active: false,
    });
    expect(service.pendingCount()).toBe(1);

    // Simulate a reload: a fresh injector re-hydrates from localStorage.
    TestBed.resetTestingModule();
    configure();

    expect(service.pendingCount()).toBe(1);
    expect(service.items()[0].kind).toBe('create-tower');
    expect(service.items()[0].payload['name']).toBe('Fountain');
  });

  it('replays a queued tower create on sync and confirms it', async () => {
    service.enqueue('create-tower', { name: 'Fountain', lat: 46.5, lng: 23.5 });

    const done = service.sync();
    await microtasks();
    const req = http.expectOne('/api/staff/towers/');
    expect(req.request.method).toBe('POST');
    expect(req.request.body.name).toBe('Fountain');
    req.flush({ id: 42, name: 'Fountain' });
    await done;

    expect(service.items()).toEqual([]);
    expect(JSON.parse(localStorage.getItem('cercetador.field-queue.v1')!)).toEqual([]);
  });

  it('remaps queued photos onto the confirmed server tower id', async () => {
    const towerEdit = service.enqueue('create-tower', {
      name: 'Fountain',
      lat: 46.5,
      lng: 23.5,
    });
    service.enqueue(
      'upload-photo',
      { image: 'data:image/jpeg;base64,xxxx', caption: 'north face' },
      towerEdit.localId, // tower has no server id while offline
    );

    const done = service.sync();
    await microtasks();
    http.expectOne('/api/staff/towers/').flush({ id: 42, name: 'Fountain' });
    await microtasks();
    const photoReq = http.expectOne('/api/staff/towers/42/photos/');
    expect(photoReq.request.body.caption).toBe('north face');
    photoReq.flush({ id: 7, tower: 42 });
    await done;

    expect(service.items()).toEqual([]);
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
    await microtasks();
    http
      .expectOne('/api/staff/zones/')
      .flush({ vertices: ['A zone needs at least 3 vertices.'] }, {
        status: 400,
        statusText: 'Bad Request',
      });
    await done;

    expect(service.failedCount()).toBe(1);
    const failed = service.items()[0];
    expect(failed.status).toBe('failed');
    expect(failed.error).toContain('vertices');

    // The failure survives a reload too — nothing is dropped unconfirmed.
    TestBed.resetTestingModule();
    configure();
    expect(service.failedCount()).toBe(1);

    done = Promise.resolve(service.retry(edit.localId)) as unknown as Promise<void>;
    await microtasks();
    http.expectOne('/api/staff/zones/').flush({ id: 5, name: 'Old town' });
    await microtasks();
    await done;

    expect(service.items()).toEqual([]);
  });
});

/** Let queued promise callbacks (sequential sync steps) run. */
async function microtasks(): Promise<void> {
  for (let i = 0; i < 10; i++) {
    await Promise.resolve();
  }
}
