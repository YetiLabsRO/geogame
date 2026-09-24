import { provideZonelessChangeDetection, runInInjectionContext, Injector } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRouteSnapshot, RouterStateSnapshot, UrlTree, provideRouter } from '@angular/router';
import { Observable, of, throwError } from 'rxjs';
import { describe, expect, it } from 'vitest';

import { AuthService, UserProfile } from './auth.service';
import { staffGuard } from './staff.guard';

function profile(isStaff: boolean): UserProfile {
  return {
    id: 1,
    username: 'staffer',
    email: 's@example.com',
    first_name: '',
    last_name: '',
    current_session: null,
    current_game: null,
    active_team_id: null,
    active_roles: [],
    is_staff: isStaff,
    is_superuser: false,
    allow_player_team_creation: false,
    captain_of_team_id: null,
  };
}

/** Minimal AuthService stand-in covering only what the guard reads. */
function fakeAuth(options: {
  token?: string | null;
  loaded?: UserProfile | null;
  ensure?: Observable<UserProfile>;
}) {
  let ensureCalls = 0;
  return {
    calls: () => ensureCalls,
    service: {
      isAuthenticated: () => (options.token ?? null) !== null,
      profile: () => options.loaded ?? null,
      ensureProfile: () => {
        ensureCalls++;
        return options.ensure ?? of(profile(true));
      },
    } as unknown as AuthService,
  };
}

function run(auth: AuthService, url = '/towers') {
  TestBed.resetTestingModule();
  TestBed.configureTestingModule({
    providers: [
      provideZonelessChangeDetection(),
      provideRouter([]),
      { provide: AuthService, useValue: auth },
    ],
  });
  const injector = TestBed.inject(Injector);
  return runInInjectionContext(injector, () =>
    staffGuard({} as ActivatedRouteSnapshot, { url } as RouterStateSnapshot),
  );
}

async function resolve(result: unknown): Promise<boolean | UrlTree> {
  if (result instanceof Observable) {
    return await new Promise((done) => result.subscribe((value) => done(value)));
  }
  return result as boolean | UrlTree;
}

describe('staffGuard', () => {
  it('sends an unauthenticated visitor to login, remembering the target', async () => {
    const { service } = fakeAuth({ token: null });
    const out = await resolve(run(service, '/towers'));
    expect(out).toBeInstanceOf(UrlTree);
    expect(String(out)).toContain('/login');
    expect(String(out)).toContain('next=%2Ftowers');
  });

  it('admits a staff user whose profile is already loaded', async () => {
    const { service } = fakeAuth({ token: 't', loaded: profile(true) });
    expect(await resolve(run(service))).toBe(true);
  });

  it('turns away a signed-in non-staff user', async () => {
    const { service } = fakeAuth({ token: 't', loaded: profile(false) });
    const out = await resolve(run(service));
    expect(String(out)).toContain('reason=not-staff');
  });

  // The regression this guard exists to prevent: a hard refresh restores
  // the token but not the profile, and the guard used to read that as
  // "not staff" and sign the user out.
  it('waits for the profile after a reload instead of signing the user out', async () => {
    const { service, calls } = fakeAuth({
      token: 't',
      loaded: null,
      ensure: of(profile(true)),
    });
    expect(await resolve(run(service))).toBe(true);
    expect(calls()).toBe(1);
  });

  it('still turns away a non-staff user whose profile arrives late', async () => {
    const { service } = fakeAuth({ token: 't', loaded: null, ensure: of(profile(false)) });
    expect(String(await resolve(run(service)))).toContain('reason=not-staff');
  });

  it('falls back to login when the stored token is rejected', async () => {
    const { service } = fakeAuth({
      token: 'stale',
      loaded: null,
      ensure: throwError(() => ({ status: 401 })),
    });
    const out = await resolve(run(service, '/zones'));
    expect(String(out)).toContain('/login');
    expect(String(out)).toContain('next=%2Fzones');
  });
});
