import { TestBed } from '@angular/core/testing';

import { APP_CONFIG, AppConfig } from './app-config';
import { PlatformService } from './platform.service';

/**
 * mobile-app 2.11 — `apiBaseUrl()` resolution: web default, and the
 * in-memory debug override taking precedence (persistence to
 * `@capacitor/preferences` only happens on native, which this jsdom
 * test environment never reports as — see `PlatformService.isNative`).
 */
describe('PlatformService', () => {
  const config: AppConfig = {
    production: false,
    apiBaseUrl: '',
    nativeApiBaseUrl: 'http://10.0.2.2:8200',
  };

  function configure(): PlatformService {
    TestBed.configureTestingModule({
      providers: [{ provide: APP_CONFIG, useValue: config }],
    });
    return TestBed.inject(PlatformService);
  }

  it('reports the web platform outside the Capacitor shell', () => {
    const service = configure();
    expect(service.isNative).toBe(false);
    expect(service.platform).toBe('web');
  });

  it('resolves to the configured web apiBaseUrl by default', () => {
    const service = configure();
    expect(service.apiBaseUrl()).toBe(config.apiBaseUrl);
  });

  it('a debug override takes precedence over the platform default', async () => {
    const service = configure();
    await service.setApiBaseUrlOverride('http://192.168.1.50:8200');
    expect(service.apiBaseUrl()).toBe('http://192.168.1.50:8200');
  });

  it('clearing the override falls back to the platform default', async () => {
    const service = configure();
    await service.setApiBaseUrlOverride('http://192.168.1.50:8200');
    await service.setApiBaseUrlOverride(null);
    expect(service.apiBaseUrl()).toBe(config.apiBaseUrl);
  });

  describe('mediaUrl()', () => {
    it('prefixes a relative path with the effective API origin', async () => {
      const service = configure();
      await service.setApiBaseUrlOverride('https://cercetador.albascout.ro');
      expect(service.mediaUrl('/media/towers/1.jpg')).toBe(
        'https://cercetador.albascout.ro/media/towers/1.jpg',
      );
    });

    it('leaves an absolute URL untouched', () => {
      const service = configure();
      expect(service.mediaUrl('https://example.com/x.jpg')).toBe('https://example.com/x.jpg');
    });

    it('leaves a relative path untouched when there is no origin configured', () => {
      const service = configure();
      expect(service.mediaUrl('/media/towers/1.jpg')).toBe('/media/towers/1.jpg');
    });

    it('returns an empty string for a missing path', () => {
      const service = configure();
      expect(service.mediaUrl(null)).toBe('');
      expect(service.mediaUrl(undefined)).toBe('');
    });
  });
});
