import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';

import { PlatformService } from './platform.service';

/**
 * Prefixes relative `/`-URLs with the effective API origin (mobile-app
 * D3) so native builds — which have no same-origin backend to proxy to —
 * reach the configured absolute origin. On the web `apiBaseUrl()` is
 * `''`, so requests keep their relative URL and the dev proxy / same-
 * origin deployment is unaffected.
 *
 * Registered BEFORE `tokenInterceptor` in `app.config.ts` so the clone
 * this interceptor produces is what the auth header gets attached to.
 */
export const apiBaseInterceptor: HttpInterceptorFn = (req, next) => {
  const platform = inject(PlatformService);
  const base = platform.apiBaseUrl();
  if (base && req.url.startsWith('/')) {
    return next(req.clone({ url: `${base}${req.url}` }));
  }
  return next(req);
};
