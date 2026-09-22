import { TestBed } from '@angular/core/testing';

import { ThemeService } from './theme.service';

/** design-system task 3.6 — ThemeService stamps `data-theme` and persists. */
describe('ThemeService', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
    TestBed.configureTestingModule({});
  });

  afterEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  it('defaults to system with no data-theme attribute stamped', () => {
    const service = TestBed.inject(ThemeService);

    expect(service.preference()).toBe('system');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
  });

  it('stamps data-theme and persists an explicit choice', () => {
    const service = TestBed.inject(ThemeService);

    service.set('dark');

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(localStorage.getItem('tr.theme')).toBe('dark');
    expect(service.effective()).toBe('dark');
  });

  it('removes the attribute when switching back to system', () => {
    const service = TestBed.inject(ThemeService);

    service.set('light');
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    service.set('system');
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false);
    expect(localStorage.getItem('tr.theme')).toBe('system');
  });

  it('restores a persisted preference for a freshly constructed service', () => {
    localStorage.setItem('tr.theme', 'dark');

    const service = TestBed.inject(ThemeService);

    expect(service.preference()).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
  });
});
