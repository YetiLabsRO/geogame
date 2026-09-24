import { describe, expect, it } from 'vitest';

import {
  COLLECTION_KEY,
  distanceMeters,
  readRememberedCollection,
  rememberCollection,
} from './field-mode.component';

/**
 * The offset readout.
 *
 * It is the only thing that says the tower is not going where the
 * curator is standing — which is what they asked for when they tapped
 * the map, and what they might have done by accident. The number is the
 * whole warning, so it has to be right at the scale it is read at:
 * tens of metres, not kilometres.
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

/**
 * The remembered target collection.
 *
 * A scouting trip is one collection across several sessions, and
 * re-picking it each time taxes the person least able to pay it. It is
 * a per-device convenience, so every path where the browser refuses to
 * cooperate has to end in "pick the first one" rather than in an error.
 */
describe('remembered target collection', () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it('has nothing to say on a device that has never been used', () => {
    expect(readRememberedCollection()).toBeNull();
  });

  it('round-trips an id', () => {
    rememberCollection(7);
    expect(readRememberedCollection()).toBe(7);
  });

  it('forgets when the target is cleared', () => {
    rememberCollection(7);
    rememberCollection(null);
    expect(readRememberedCollection()).toBeNull();
  });

  it('treats a value it cannot read as nothing remembered', () => {
    // Another tab, an older build, a hand-edited devtools entry.
    localStorage.setItem(COLLECTION_KEY, 'Alba Iulia');
    expect(readRememberedCollection()).toBeNull();
  });

  it('survives storage being unavailable', () => {
    const original = Storage.prototype.getItem;
    Storage.prototype.getItem = () => {
      throw new DOMException('denied', 'SecurityError');
    };
    try {
      expect(readRememberedCollection()).toBeNull();
    } finally {
      Storage.prototype.getItem = original;
    }
  });
});
