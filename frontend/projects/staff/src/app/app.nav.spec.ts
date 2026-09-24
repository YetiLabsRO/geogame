import { describe, expect, it } from 'vitest';

import { NAV_SECTIONS } from './app';
import { routes } from './app.routes';

/**
 * The sidebar's coverage guarantee (staff-nav-sidebar).
 *
 * `/nfc-tags` shipped with a route and a working page that nothing ever
 * linked to, because the old shell declared each link as its own block of
 * markup and nobody noticed one was missing. These tests make that class
 * of omission fail the build instead.
 */

/** Top-level staff routes a person should be able to click to. */
const EXCLUDED = new Set([
  'login', // reached by signing out, not from the sidebar
  '**', // wildcard redirect
]);

function navigableRoutes(): string[] {
  return routes
    // A pure redirect is not a destination: it exists so an old link
    // keeps working, and linking it in the sidebar would advertise a
    // path we deliberately moved away from.
    .filter((route) => !route.redirectTo)
    .map((route) => route.path ?? '')
    .filter((path) => !EXCLUDED.has(path))
    // Parameterised and nested routes (sessions/:id/replay, games/:id/edit)
    // are reached from their parent page, not the sidebar.
    .filter((path) => !path.includes(':'))
    .filter((path) => !path.includes('/'));
}

describe('staff sidebar navigation', () => {
  const linked = new Set(
    NAV_SECTIONS.flatMap((section) => section.items).map((item) => item.link.replace(/^\//, '')),
  );

  it('links every navigable top-level route', () => {
    const missing = navigableRoutes().filter((path) => !linked.has(path));
    expect(missing, `routes with no sidebar entry: ${missing.join(', ')}`).toEqual([]);
  });

  it('points every sidebar entry at a real route', () => {
    // Redirects count as real here — a sidebar entry pointing at one
    // still lands the user somewhere valid.
    const known = new Set(routes.map((route) => route.path ?? ''));
    const dangling = [...linked].filter((link) => !known.has(link));
    expect(dangling, `sidebar entries with no route: ${dangling.join(', ')}`).toEqual([]);
  });

  it('places each destination in exactly one section', () => {
    const links = NAV_SECTIONS.flatMap((s) => s.items).map((i) => i.link);
    expect(links).toHaveLength(new Set(links).size);
  });

  it('gives every entry a label and an icon', () => {
    for (const item of NAV_SECTIONS.flatMap((s) => s.items)) {
      expect(item.label.trim(), `label for ${item.link}`).not.toBe('');
      expect(item.icon, `icon for ${item.link}`).toMatch(/^bi-/);
    }
  });

  it('matches exactly only on the root route', () => {
    for (const item of NAV_SECTIONS.flatMap((s) => s.items)) {
      expect(!!item.exact, `exact flag on ${item.link}`).toBe(item.link === '/');
    }
  });

  it('names its sections', () => {
    expect(NAV_SECTIONS.map((s) => s.label)).toEqual(['Run', 'Build', 'Organize', 'Analyze']);
    for (const section of NAV_SECTIONS) expect(section.items.length).toBeGreaterThan(0);
  });
});
