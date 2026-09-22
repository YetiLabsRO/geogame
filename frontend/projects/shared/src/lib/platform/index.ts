/*
 * Platform layer (mobile-app change): every device capability the apps
 * touch goes through here, so screens never branch on Capacitor or call
 * `navigator.*` directly. Each service picks the native plugin inside
 * the Capacitor shell and the browser API on the web.
 */
export {};
