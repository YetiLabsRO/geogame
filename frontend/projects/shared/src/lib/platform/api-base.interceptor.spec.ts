import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { apiBaseInterceptor } from './api-base.interceptor';
import { PlatformService } from './platform.service';

/**
 * mobile-app 2.11 — the native origin gets prefixed onto relative
 * `/`-URLs; the web path (empty `apiBaseUrl()`) is untouched so the dev
 * proxy / same-origin deployment keeps working.
 */
describe('apiBaseInterceptor', () => {
  function configure(apiBaseUrl: string): { http: HttpClient; backend: HttpTestingController } {
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([apiBaseInterceptor])),
        provideHttpClientTesting(),
        { provide: PlatformService, useValue: { apiBaseUrl: () => apiBaseUrl } },
      ],
    });
    return {
      http: TestBed.inject(HttpClient),
      backend: TestBed.inject(HttpTestingController),
    };
  }

  it('prefixes a relative request URL with the native origin', () => {
    const { http, backend } = configure('http://10.0.2.2:8200');
    http.get('/api/current-session/').subscribe();
    const req = backend.expectOne('http://10.0.2.2:8200/api/current-session/');
    expect(req.request.method).toBe('GET');
    req.flush({});
    backend.verify();
  });

  it('leaves the request URL untouched on the web (empty apiBaseUrl)', () => {
    const { http, backend } = configure('');
    http.get('/api/current-session/').subscribe();
    const req = backend.expectOne('/api/current-session/');
    req.flush({});
    backend.verify();
  });

  it('does not prefix an already-absolute URL', () => {
    const { http, backend } = configure('http://10.0.2.2:8200');
    http.get('https://example.com/other/').subscribe();
    const req = backend.expectOne('https://example.com/other/');
    req.flush({});
    backend.verify();
  });
});
