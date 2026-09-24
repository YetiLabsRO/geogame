import { HttpErrorResponse } from '@angular/common/http';
import { provideZonelessChangeDetection } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthService, DialogService, StaffApiService } from 'shared';

import { SessionsComponent } from './sessions.component';

/**
 * The session list's two jobs after this change (destructive-actions-and-dialogs):
 * narrowing to one game without leaving a heading per game behind, and
 * offering deletion to a superadmin and to nobody else — with a refusal
 * that lands where the action was taken from, rather than as a lost alert.
 */

function game(id: number, name: string) {
  return { id, name, slug: name.toLowerCase(), is_active: true } as never;
}

function session(id: number, gameId: number, name: string, isActive = true) {
  return {
    id,
    game: gameId,
    name,
    slug: `s${id}`,
    state: isActive ? 'RUNNING' : 'FINISHED',
    is_active: isActive,
    start_time: `2026-09-2${id}T10:00:00Z`,
    end_time: `2026-09-2${id}T18:00:00Z`,
  } as never;
}

const GAMES = [game(1, 'Alba'), game(2, 'Brasov')];
const SESSIONS = [
  session(1, 1, 'Alba morning'),
  session(2, 1, 'Alba evening', false),
  session(3, 2, 'Brasov run'),
];

function api(overrides: Record<string, unknown> = {}) {
  return {
    listGames: vi.fn(() => of(GAMES)),
    listSessions: vi.fn(() => of(SESSIONS)),
    createSession: vi.fn(),
    updateSession: vi.fn(),
    deleteSession: vi.fn(() => of(undefined) as Observable<void>),
    ...overrides,
  };
}

function auth(isSuperuser: boolean) {
  return {
    isSuperuser: () => isSuperuser,
    profile: () => ({ current_session: null }),
    fetchProfile: vi.fn(() => of({})),
  };
}

describe('SessionsComponent', () => {
  let stub: ReturnType<typeof api>;
  let dialogs: { confirm: ReturnType<typeof vi.fn> };

  function setup(options: { superuser?: boolean; api?: Record<string, unknown> } = {}) {
    stub = api(options.api);
    dialogs = { confirm: vi.fn(() => Promise.resolve(true)) };
    TestBed.configureTestingModule({
      imports: [SessionsComponent],
      providers: [
        provideZonelessChangeDetection(),
        provideRouter([]),
        { provide: StaffApiService, useValue: stub },
        { provide: AuthService, useValue: auth(options.superuser ?? true) },
        { provide: DialogService, useValue: dialogs },
      ],
    });
    const fixture = TestBed.createComponent(SessionsComponent);
    fixture.detectChanges();
    return fixture;
  }

  function el(fixture: ReturnType<typeof setup>): HTMLElement {
    return fixture.nativeElement as HTMLElement;
  }

  function headings(fixture: ReturnType<typeof setup>): string[] {
    return Array.from(el(fixture).querySelectorAll('h2.h5')).map((h) =>
      (h.textContent ?? '').trim().split(/\s+/)[0],
    );
  }

  /** The slugs of the session rows on screen — names render into inputs. */
  function slugs(fixture: ReturnType<typeof setup>): string[] {
    return Array.from(el(fixture).querySelectorAll('tbody tr td:first-child code')).map(
      (c) => (c.textContent ?? '').trim(),
    );
  }

  function deleteButtons(fixture: ReturnType<typeof setup>): HTMLButtonElement[] {
    return Array.from(el(fixture).querySelectorAll('button[aria-label^="Delete session"]'));
  }

  function component(fixture: ReturnType<typeof setup>) {
    return fixture.componentInstance as unknown as {
      setGameFilter(id: number | null): void;
      setFilter(f: 'all' | 'active' | 'past'): void;
      remove(row: unknown): Promise<void>;
      groups(): { rows: { session: { id: number }; blockers: string[] }[] }[];
    };
  }

  describe('filtering by game', () => {
    it('shows every game by default', () => {
      const fixture = setup();
      expect(headings(fixture)).toEqual(['Alba', 'Brasov']);
    });

    it('narrows to one game, and drops the headings of the others', () => {
      const fixture = setup();
      component(fixture).setGameFilter(2);
      fixture.detectChanges();
      expect(headings(fixture)).toEqual(['Brasov']);
      expect(slugs(fixture)).toEqual(['s3']);
    });

    it('composes with the lifecycle filter rather than replacing it', () => {
      const fixture = setup();
      const c = component(fixture);
      c.setGameFilter(1);
      c.setFilter('past');
      fixture.detectChanges();
      // s2 is Alba's finished run; s1 is its running one.
      expect(slugs(fixture)).toEqual(['s2']);
    });

    it('says which filters emptied the list, instead of showing nothing', () => {
      const fixture = setup();
      const c = component(fixture);
      c.setGameFilter(2);
      c.setFilter('past');
      fixture.detectChanges();
      const text = el(fixture).textContent ?? '';
      expect(text).toContain('No sessions match');
      expect(text).toContain('Brasov');
      expect(text).toContain('past');
    });

    it('clearing the game filter restores every game', () => {
      const fixture = setup();
      const c = component(fixture);
      c.setGameFilter(2);
      fixture.detectChanges();
      c.setGameFilter(null);
      fixture.detectChanges();
      expect(headings(fixture)).toEqual(['Alba', 'Brasov']);
    });
  });

  describe('the delete control', () => {
    it('is there for a superadmin, once per session', () => {
      expect(deleteButtons(setup({ superuser: true }))).toHaveLength(3);
    });

    it('is absent for everyone else — not merely disabled', () => {
      expect(deleteButtons(setup({ superuser: false }))).toHaveLength(0);
    });

    it('asks in the app\'s own dialog before sending anything', async () => {
      const fixture = setup();
      dialogs.confirm.mockResolvedValueOnce(false);
      deleteButtons(fixture)[0].click();
      await Promise.resolve();
      expect(dialogs.confirm).toHaveBeenCalledOnce();
      expect(stub.deleteSession).not.toHaveBeenCalled();
    });

    it('names what goes, and says it cannot be undone', async () => {
      const fixture = setup();
      deleteButtons(fixture)[0].click();
      await Promise.resolve();
      const options = dialogs.confirm.mock.calls[0][0];
      expect(options.title).toContain('Alba morning');
      expect(options.message).toMatch(/cannot be undone/i);
      expect(options.danger).toBe(true);
    });

    it('removes the row on success, without a reload', async () => {
      const fixture = setup();
      deleteButtons(fixture)[0].click();
      await new Promise((r) => setTimeout(r, 0));
      fixture.detectChanges();
      expect(stub.listSessions).toHaveBeenCalledOnce();
      expect(slugs(fixture)).toEqual(['s2', 's3']);
    });

    it('keeps the row and shows the blockers when the run is still live', async () => {
      const refusal = new HttpErrorResponse({
        status: 409,
        error: {
          detail: 'Cannot delete while a run is live.',
          blockers: [
            {
              code: 'session_live',
              session_id: 1,
              message: 'Session "Alba morning" is running. Finish it first.',
            },
          ],
        },
      });
      const fixture = setup({ api: { deleteSession: vi.fn(() => throwError(() => refusal)) } });
      deleteButtons(fixture)[0].click();
      await new Promise((r) => setTimeout(r, 0));
      fixture.detectChanges();
      // Nothing disappeared optimistically — every row is still there.
      expect(slugs(fixture)).toEqual(['s1', 's2', 's3']);
      expect(el(fixture).textContent).toContain('Finish it first.');
      expect(component(fixture).groups()[0].rows[0].blockers).toHaveLength(1);
    });
  });
});
