import { inject } from '@angular/core';
import { CanActivateFn, Router, UrlTree } from '@angular/router';

import { AuthService } from './auth.service';

export const staffGuard: CanActivateFn = (_route, state): boolean | UrlTree => {
  const auth = inject(AuthService);
  const router = inject(Router);
  if (!auth.isAuthenticated()) {
    return router.createUrlTree(['/login'], {
      queryParams: { next: state.url },
    });
  }
  if (auth.isStaff()) {
    return true;
  }
  // Authenticated but not staff — send them somewhere safe.
  return router.createUrlTree(['/login'], { queryParams: { reason: 'not-staff' } });
};
