import { EnvironmentProviders, InjectionToken, makeEnvironmentProviders } from '@angular/core';

/**
 * Runtime app configuration (mobile-app D3): the web build talks to the
 * same origin (`apiBaseUrl: ''`, relative URLs through the dev proxy /
 * same-origin deploy); native builds need an absolute origin because a
 * Capacitor WebView has no same-origin backend to proxy to.
 */
export interface AppConfig {
  production: boolean;
  apiBaseUrl: string;
  nativeApiBaseUrl: string;
}

export const APP_CONFIG = new InjectionToken<AppConfig>('APP_CONFIG');

export function provideAppConfig(config: AppConfig): EnvironmentProviders {
  return makeEnvironmentProviders([{ provide: APP_CONFIG, useValue: config }]);
}
