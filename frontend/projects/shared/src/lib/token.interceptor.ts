import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { AuthService } from './auth.service';

/**
 * Adds `Authorization: Token <key>` to outgoing requests when we have one
 * stored. DRF's TokenAuthentication expects this header format (not Bearer).
 */
export const tokenInterceptor: HttpInterceptorFn = (req, next) => {
  const auth = inject(AuthService);
  const token = auth.token();
  if (!token) {
    return next(req);
  }
  return next(
    req.clone({
      setHeaders: { Authorization: `Token ${token}` },
    }),
  );
};
