import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  BundleImportMode,
  BundleInspection,
  StaffApiService,
} from 'shared';

import { BundlesComponent } from './bundles.component';

/**
 * The step in the middle (content-portability).
 *
 * The thing that must not regress is the order: a bundle comes from
 * somewhere else, so the page has to say what is in it before it offers
 * a button that rewrites the map. These tests hold that order, and that
 * changing the mode re-reads the preview rather than leaving the other
 * mode's numbers on screen.
 */

const GAME = {
  id: 1,
  slug: 'alba-iulia',
  name: 'Alba Iulia',
  collections: [7],
} as never;

const COLLECTION = {
  id: 7,
  name: 'Alba Iulia',
  slug: 'alba-iulia',
  towers: [1, 2],
  zones: [3],
} as never;

function inspection(mode: BundleImportMode): BundleInspection {
  return {
    format_version: 1,
    exported_at: '2026-09-24T00:00:00+00:00',
    selection: { games: ['alba-iulia'], collections: ['alba-iulia'] },
    mode,
    kinds: [
      {
        kind: 'towers',
        label: 'towers',
        in_bundle: 48,
        already_here: mode === 'copy' ? 0 : 48,
        would_create: mode === 'copy' ? 48 : 0,
        would_update: mode === 'copy' ? 0 : 48,
      },
    ],
    slug_collisions: [],
    media_files: 0,
  };
}

function api() {
  return {
    listGames: vi.fn(() => of([GAME])),
    listCollections: vi.fn(() => of([COLLECTION])),
    exportBundle: vi.fn(),
    inspectBundle: vi.fn((_file: File, mode: BundleImportMode) =>
      of(inspection(mode)),
    ),
    importBundle: vi.fn(),
  };
}

describe('BundlesComponent', () => {
  let stub: ReturnType<typeof api>;

  beforeEach(() => {
    stub = api();
    TestBed.configureTestingModule({
      imports: [BundlesComponent],
      providers: [
        provideZonelessChangeDetection(),
        { provide: StaffApiService, useValue: stub },
      ],
    });
  });

  function render() {
    const fixture = TestBed.createComponent(BundlesComponent);
    fixture.detectChanges();
    return fixture;
  }

  function importButton(fixture: ReturnType<typeof render>): HTMLButtonElement {
    const buttons = Array.from(
      (fixture.nativeElement as HTMLElement).querySelectorAll('button'),
    ) as HTMLButtonElement[];
    const found = buttons.find((b) => /^Import/.test(b.textContent?.trim() ?? ''));
    expect(found, 'no import button rendered').toBeTruthy();
    return found as HTMLButtonElement;
  }

  function chooseBundle(fixture: ReturnType<typeof render>) {
    const component = fixture.componentInstance as unknown as {
      chooseFile(event: Event): void;
    };
    const file = new File([new Uint8Array([1, 2, 3])], 'bundle.zip');
    component.chooseFile({
      target: { files: [file] } as unknown as HTMLInputElement,
    } as unknown as Event);
    fixture.detectChanges();
  }

  it('does not offer import before a bundle has been read', () => {
    const fixture = render();
    expect(importButton(fixture).disabled).toBe(true);
    expect((fixture.nativeElement as HTMLElement).textContent).toContain(
      'Choose a bundle first',
    );
    expect(stub.importBundle).not.toHaveBeenCalled();
  });

  it('inspects as soon as a bundle is chosen, and then offers import', () => {
    const fixture = render();
    chooseBundle(fixture);
    expect(stub.inspectBundle).toHaveBeenCalledTimes(1);
    expect(stub.inspectBundle.mock.calls[0][1]).toBe('sync');
    expect(importButton(fixture).disabled).toBe(false);
  });

  it('shows what the bundle holds and what would change', () => {
    const fixture = render();
    chooseBundle(fixture);
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('48');
    expect(text).toContain('Would create');
    expect(text).toContain('format version 1');
  });

  it('re-reads the preview when the mode changes', () => {
    const fixture = render();
    chooseBundle(fixture);
    const component = fixture.componentInstance as unknown as {
      setMode(mode: BundleImportMode): void;
    };
    component.setMode('copy');
    fixture.detectChanges();
    expect(stub.inspectBundle).toHaveBeenCalledTimes(2);
    expect(stub.inspectBundle.mock.calls[1][1]).toBe('copy');
    expect(importButton(fixture).textContent).toContain('separate copy');
  });

  it('warns about name collisions rather than letting the import fail', () => {
    stub.inspectBundle = vi.fn(() =>
      of({
        ...inspection('sync'),
        slug_collisions: [
          {
            kind: 'games',
            slug: 'alba-iulia',
            name: 'Someone else',
            incoming_uuid: 'abc',
          },
        ],
      }),
    );
    const fixture = render();
    chooseBundle(fixture);
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(text).toContain('alba-iulia');
    expect(text).toContain('Someone else');
    expect(text).toMatch(/separate copy/i);
  });

  it('does not ask the server for collections a chosen game already carries', () => {
    const fixture = render();
    const component = fixture.componentInstance as unknown as {
      toggleGame(id: number): void;
      toggleCollection(id: number): void;
      downloadBundle(): void;
    };
    component.toggleGame(1);
    component.toggleCollection(7);
    stub.exportBundle = vi.fn(() => of({ body: null, headers: new Map() }));
    component.downloadBundle();
    expect(stub.exportBundle).toHaveBeenCalledWith([1], []);
  });
});
