/*
 * Platform layer (mobile-app change): every device capability the apps
 * touch goes through here, so screens never branch on Capacitor or call
 * `navigator.*` directly. Each service picks the native plugin inside
 * the Capacitor shell and the browser API on the web.
 */
export * from './app-config';
export * from './platform.service';
export * from './api-base.interceptor';
export * from './media-url.pipe';
export * from './geolocation.service';
export * from './background-location.service';
export * from './push.bridge';
export * from './nfc.service';
export * from './haptics.service';
export * from './keep-awake.service';
export * from './network.service';
export * from './deep-link.service';
export * from './ble-advertiser';
export * from './ble-proximity.service';
