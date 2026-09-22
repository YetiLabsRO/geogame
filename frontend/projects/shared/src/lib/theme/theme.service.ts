import { Injectable, computed, effect, signal } from '@angular/core';
import { Capacitor } from '@capacitor/core';
import { Style, StatusBar } from '@capacitor/status-bar';

/** `system` follows the OS; `light`/`dark` are explicit player overrides. */
export type ThemePreference = 'system' | 'light' | 'dark';

const STORAGE_KEY = 'tr.theme';
const DARK_QUERY = '(prefers-color-scheme: dark)';

// Kept in sync with --color-bg-canvas in theme/_tokens.scss — the native
// status bar can't read CSS custom properties, so the colours are mirrored.
const CANVAS_LIGHT = '#fcf9f2';
const CANVAS_DARK = '#121416';

/**
 * Tower Rush theme (mobile-app D8): tracks the player's `system | light |
 * dark` preference, persists it, and stamps `data-theme` on `<html>` so
 * theme/_tokens.scss can re-theme every token without component changes.
 *
 * `system` never stamps an attribute — the CSS `prefers-color-scheme`
 * media query alone drives that case. An explicit `light`/`dark` choice
 * stamps `data-theme` so it overrides the OS preference.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly media = this.createMediaQuery();
  private readonly systemPrefersDark = signal(this.media?.matches ?? false);

  readonly preference = signal<ThemePreference>(this.readStoredPreference());

  /** The theme actually in effect once `system` is resolved. */
  readonly effective = computed<'light' | 'dark'>(() => {
    const preference = this.preference();
    return preference === 'system' ? (this.systemPrefersDark() ? 'dark' : 'light') : preference;
  });

  constructor() {
    this.media?.addEventListener('change', (event) => this.systemPrefersDark.set(event.matches));

    // Apply the stored/default preference immediately so the DOM reflects
    // it before first paint, without waiting on the effect scheduler.
    this.applyDomAttribute(this.preference());

    // The native status bar has no "follow system" mode of its own, so it
    // needs an explicit call whenever the effective theme changes.
    effect(() => this.syncStatusBar(this.effective()));
  }

  /** Change the preference; persists it and re-stamps `data-theme` synchronously. */
  set(preference: ThemePreference): void {
    this.preference.set(preference);
    this.applyDomAttribute(preference);
    try {
      localStorage.setItem(STORAGE_KEY, preference);
    } catch {
      // Storage unavailable (private mode, disabled site data) — the
      // in-memory preference signal still works for this session.
    }
  }

  private readStoredPreference(): ThemePreference {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored === 'light' || stored === 'dark' || stored === 'system') {
        return stored;
      }
    } catch {
      // ignore — fall back to 'system' below.
    }
    return 'system';
  }

  private applyDomAttribute(preference: ThemePreference): void {
    if (typeof document === 'undefined') return;
    const root = document.documentElement;
    if (preference === 'system') {
      root.removeAttribute('data-theme');
    } else {
      root.setAttribute('data-theme', preference);
    }
  }

  private syncStatusBar(effective: 'light' | 'dark'): void {
    if (!Capacitor.isNativePlatform()) return;
    try {
      void StatusBar.setStyle({ style: effective === 'dark' ? Style.Dark : Style.Light });
      void StatusBar.setBackgroundColor({
        color: effective === 'dark' ? CANVAS_DARK : CANVAS_LIGHT,
      });
    } catch {
      // Status bar plugin unavailable on this build/platform — ignore.
    }
  }

  private createMediaQuery(): MediaQueryList | null {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
      return null;
    }
    try {
      return window.matchMedia(DARK_QUERY);
    } catch {
      return null;
    }
  }
}
