import { provideHttpClient, withInterceptors } from '@angular/common/http';
import {
  ApplicationConfig,
  inject,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';

import {
  AuthService,
  DeepLinkService,
  apiBaseInterceptor,
  provideAppConfig,
  providePushBridge,
  tokenInterceptor,
} from 'shared';

import { environment } from '../environments/environment';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    // mobile-app D3: apiBaseInterceptor must run BEFORE tokenInterceptor
    // so the native origin is already on the URL when the auth header
    // (and later interceptors) see the request.
    provideHttpClient(withInterceptors([apiBaseInterceptor, tokenInterceptor])),
    provideAppConfig(environment),
    providePushBridge(),
    // mobile-app 2.8/2.9: native only — restore a Preferences-mirrored
    // token before the router's initial navigation, then start the
    // deep-link / back-button listeners.
    provideAppInitializer(() => {
      // Resolve both services synchronously: inject() is only valid before
      // the first await (NG0203 otherwise).
      const auth = inject(AuthService);
      const deepLinks = inject(DeepLinkService);
      return (async () => {
        await auth.restoreToken();
        await deepLinks.init();
      })();
    }),
  ],
};
