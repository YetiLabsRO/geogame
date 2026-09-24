import { HttpErrorResponse } from '@angular/common/http';
import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthService, DialogService, StaffApiService } from 'shared';

import { GamesComponent } from './games.component';

/**
 * Deleting a game (destructive-actions-and-dialogs).
 *
 * A game is its configuration plus its runs, so the row on screen shows a
 * fraction of what goes. These hold the two things that make that safe:
 * the dialog says how many sessions go and asks for the slug, and a
 * refusal names the live sessions instead of vanishing.
 */

const GAMES = [
  { id: 1, slug: 'alba', name: 'Alba', is_active: true, cloned_from: null, created_by_username: 'ana' },
  { id: 2, slug: 'brasov', name: 'Brasov', is_active: true, cloned_from: null, created_by_username: 'ana' },
] as never[];

function api(overrides: Record<string, unknown> = {}) {
  return {
    listGames: vi.fn(() => of(GAMES)),
    listSessions: vi.fn(() => of([{ id: 10 }, { id: 11 }] as never[])),
    updateGame: vi.fn(),
    cloneGame: vi.fn(),
    pauseAllSessions: vi.fn(),
    deleteGame: vi.fn(() => of(undefined) as Observable<void>),
    ...overrides,
  };
}

describe('GamesComponent', () => {
  let stub: ReturnType<typeof api>;
  let dialogs: { confirm: ReturnType<typeof vi.fn> };

  function setup(options: { superuser?: boolean; api?: Record<string, unknown> } = {}) {
    stub = api(options.api);
    dialogs = { confirm: vi.fn(() => Promise.resolve(true)) };
    TestBed.configureTestingModule({
      imports: [GamesComponent],
      providers: [
        provideZonelessChangeDetection(),
        provideRouter([]),
        { provide: StaffApiService, useValue: stub },
        { provide: AuthService, useValue: { isSuperuser: () => options.superuser ?? true } },
        { provide: DialogService, useValue: dialogs },
      ],
    });
    const fixture = TestBed.createComponent(GamesComponent);
    fixture.detectChanges();
    return fixture;
  }

  function el(fixture: ReturnType<typeof setup>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function deleteButtons(fixture: ReturnType<typeof setup>): HTMLButtonElement[] {
    return Array.from(el(fixture).querySelectorAll('button[aria-label^="Delete game"]'));
  }

  function slugs(fixture: ReturnType<typeof setup>): string[] {
    return Array.from(el(fixture).querySelectorAll('tbody tr td:first-child code')).map(
      (c) => (c.textContent ?? '').trim(),
    );
  }

  /** Click delete and let the dialog promise and the request settle. */
  async function clickDelete(fixture: ReturnType<typeof setup>, index = 0) {
    deleteButtons(fixture)[index].click();
    await new Promise((r) => setTimeout(r, 0));
    fixture.detectChanges();
  }

  it('offers the control to a superadmin', () => {
    expect(deleteButtons(setup({ superuser: true }))).toHaveLength(2);
  });

  it('does not offer it to anyone else', () => {
    expect(deleteButtons(setup({ superuser: false }))).toHaveLength(0);
  });

  it('counts the sessions that would go, and asks for the slug typed', async () => {
    const fixture = setup();
    await clickDelete(fixture);
    const options = dialogs.confirm.mock.calls[0][0];
    expect(options.title).toContain('Alba');
    expect(options.message).toContain('2 sessions');
    expect(options.message).toMatch(/cannot be undone/i);
    expect(options.requireTyping).toBe('alba');
    expect(options.danger).toBe(true);
  });

  it('says what survives, so a shared map is not thought lost', async () => {
    const fixture = setup();
    await clickDelete(fixture);
    expect(dialogs.confirm.mock.calls[0][0].message).toMatch(
      /towers, zones and collections .* shared/i,
    );
  });

  it('phrases a game with no sessions as having none', async () => {
    const fixture = setup({ api: { listSessions: vi.fn(() => of([])) } });
    await clickDelete(fixture);
    expect(dialogs.confirm.mock.calls[0][0].message).toContain('no sessions');
  });

  it('still offers the delete when the session count cannot be fetched', async () => {
    const fixture = setup({
      api: { listSessions: vi.fn(() => throwError(() => new Error('offline'))) },
    });
    await clickDelete(fixture);
    expect(dialogs.confirm).toHaveBeenCalledOnce();
    expect(dialogs.confirm.mock.calls[0][0].message).toMatch(/every session/i);
  });

  it('sends nothing when the dialog is declined', async () => {
    const fixture = setup();
    dialogs.confirm.mockResolvedValueOnce(false);
    await clickDelete(fixture);
    expect(stub.deleteGame).not.toHaveBeenCalled();
  });

  it('drops the row on success without a reload', async () => {
    const fixture = setup();
    await clickDelete(fixture);
    expect(stub.deleteGame).toHaveBeenCalledWith(1);
    expect(stub.listGames).toHaveBeenCalledOnce();
    expect(slugs(fixture)).toEqual(['brasov']);
  });

  it('keeps the row and names the live sessions when refused', async () => {
    const refusal = new HttpErrorResponse({
      status: 409,
      error: {
        detail: 'Cannot delete while a run is live.',
        blockers: [
          { code: 'session_live', session_id: 10, message: 'Session "Morning" is running. Finish it first.' },
          { code: 'session_live', session_id: 11, message: 'Session "Evening" is paused. Finish it first.' },
        ],
      },
    });
    const fixture = setup({ api: { deleteGame: vi.fn(() => throwError(() => refusal)) } });
    await clickDelete(fixture);
    expect(slugs(fixture)).toEqual(['alba', 'brasov']);
    const items = Array.from(el(fixture).querySelectorAll('ul.text-danger li')).map((li) =>
      (li.textContent ?? '').trim(),
    );
    expect(items).toHaveLength(2);
    expect(items[0]).toContain('Morning');
    expect(items[1]).toContain('Evening');
  });
});
