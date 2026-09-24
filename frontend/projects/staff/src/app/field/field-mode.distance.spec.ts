import { describe, expect, it } from 'vitest';

import { distanceMeters } from './field-mode.component';

/**
 * The offset readout (library-map crosshair placement).
 *
 * Panning the map is otherwise invisible: a curator who moved the map
 * while walking has no way to know the crosshair is no longer where
 * they are standing. The number is the whole warning, so it has to be
 * right at the scale it is read at — tens of metres, not kilometres.
 */
describe('distanceMeters', () => {
  const here = { lat: 46.068, lng: 23.59 };

  it('reads zero at the fix', () => {
    expect(distanceMeters(here, here)).toBe(0);
  });

  it('measures a short northward step', () => {
    // 0.0001 degrees of latitude is ~11.1 m anywhere on Earth.
    const north = { lat: here.lat + 0.0001, lng: here.lng };
    expect(distanceMeters(here, north)).toBeGreaterThan(10.5);
    expect(distanceMeters(here, north)).toBeLessThan(11.5);
  });

  it('accounts for latitude when measuring eastward', () => {
    // A degree of longitude is shorter away from the equator; at 46°N
    // it is about cos(46°) ≈ 0.695 of a degree of latitude. Ignoring
    // that would overstate an east-west offset by ~44%.
    const east = { lat: here.lat, lng: here.lng + 0.0001 };
    const north = { lat: here.lat + 0.0001, lng: here.lng };
    const ratio = distanceMeters(here, east) / distanceMeters(here, north);
    expect(ratio).toBeGreaterThan(0.66);
    expect(ratio).toBeLessThan(0.73);
  });

  it('is symmetric', () => {
    const other = { lat: 46.0695, lng: 23.5915 };
    expect(distanceMeters(here, other)).toBeCloseTo(distanceMeters(other, here), 6);
  });

  it('is roughly right over a few hundred metres', () => {
    // 0.001 degrees latitude ≈ 111 m.
    const away = { lat: here.lat + 0.001, lng: here.lng };
    expect(distanceMeters(here, away)).toBeGreaterThan(108);
    expect(distanceMeters(here, away)).toBeLessThan(114);
  });
});
