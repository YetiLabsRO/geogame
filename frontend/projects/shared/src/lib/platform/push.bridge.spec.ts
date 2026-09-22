import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';

import { PushBridge, WebPushBridge, providePushBridge } from './push.bridge';

/**
 * mobile-app 2.11 — `providePushBridge()` picks the strategy by
 * `Capacitor.isNativePlatform()`; this jsdom test environment never
 * reports native, so it must resolve to `WebPushBridge`.
 */
describe('providePushBridge', () => {
  it('provides a WebPushBridge outside the Capacitor shell', () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        providePushBridge(),
      ],
    });

    const bridge = TestBed.inject(PushBridge);

    expect(bridge).toBeInstanceOf(WebPushBridge);
  });

  it('exposes the same abstract API regardless of strategy', () => {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        provideRouter([]),
        providePushBridge(),
      ],
    });

    const bridge = TestBed.inject(PushBridge);

    expect(typeof bridge.supported).toBe('boolean');
    expect(typeof bridge.permission).toBe('function');
    expect(typeof bridge.enable).toBe('function');
    expect(typeof bridge.disable).toBe('function');
  });
});
