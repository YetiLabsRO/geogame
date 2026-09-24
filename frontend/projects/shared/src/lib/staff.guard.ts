import { inject } from '@angular/core';
import { CanActivateFn, Params, Router, UrlTree } from '@angular/router';
import { Observable, catchError, map, of } from 'rxjs';

import { AuthService } from './auth.service';

/**
 * Staff-only route guard.
 *
 * The subtlety is reload. A page refresh restores the token from
 * `localStorage`, so the user is authenticated immediately — but the
 * profile, and with it `is_staff`, is not restored and has to be
 * fetched. Deciding synchronously in that window reads `is_staff` as
 * false and bounces a perfectly valid staff user to the login page,
 * which is exactly what a hard refresh used to do. So when the profile
 * is not loaded yet, wait for it instead of guessing.
 */
export const staffGuard: CanActivateFn = (
  _route,
  state,
): boolean | UrlTree | Observable<boolean | UrlTree> => {
  const auth = inject(AuthService);
  const router = inject(Router);

  const toLogin = (queryParams: Params): UrlTree =>
    router.createUrlTree(['/login'], { queryParams });

  if (!auth.isAuthenticated()) {
    return toLogin({ next: state.url });
  }

  // Authenticated but not staff — send them somewhere safe.
  const decide = (isStaff: boolean): boolean | UrlTree =>
    isStaff ? true : toLogin({ reason: 'not-staff' });

  const profile = auth.profile();
  if (profile !== null) {
    return decide(profile.is_staff);
  }

  return auth.ensureProfile().pipe(
    map((loaded) => decide(loaded.is_staff)),
    // The token was rejected or the network failed: fall back to the
    // login page, keeping where they were headed.
    catchError(() => of(toLogin({ next: state.url }))),
  );
};
