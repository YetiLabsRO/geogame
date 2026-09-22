/**
 * Development environment (mobile-app change).
 *
 * `apiBaseUrl` is empty on the web so the dev proxy / same-origin
 * deployment keeps serving relative `/api/...` URLs. `nativeApiBaseUrl`
 * is what the Capacitor shell talks to when no debug override is set:
 * 10.0.2.2 is the Android emulator's alias for the host machine.
 */
export const environment = {
  production: false,
  apiBaseUrl: '',
  nativeApiBaseUrl: 'http://10.0.2.2:8200',
};
