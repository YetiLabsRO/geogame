import { describe, expect, it } from 'vitest';

import { HIDDEN_REASON_TEXT } from './live-overview.component';

/**
 * The absence the overview has to explain (live-overview).
 *
 * A screen with no dots on it looks broken, and the reason it has none
 * is always a setting somebody chose rather than a fault. Every reason
 * the backend can return therefore needs words on the page — a missing
 * entry would render as a blank note under a map full of towers.
 */

/** Must match `game/overview.py`'s REASON_* constants. */
const BACKEND_REASONS = [
  'TRACKING_DISABLED',
  'VISIBILITY_NONE',
  'VISIBILITY_OWN_TEAM',
  'VISIBILITY_NEAREST_ONLY',
] as const;

describe('hidden-position reasons', () => {
  it('has wording for every reason the backend can send', () => {
    const missing = BACKEND_REASONS.filter((reason) => !HIDDEN_REASON_TEXT[reason]);
    expect(missing, `reasons with no wording: ${missing.join(', ')}`).toEqual([]);
  });

  it('names no reason the backend does not send', () => {
    expect(Object.keys(HIDDEN_REASON_TEXT).sort()).toEqual([...BACKEND_REASONS].sort());
  });

  it('explains the default case as a setting rather than a fault', () => {
    // OWN_TEAM is the default, so this is the message most runners will
    // meet. It has to say what to change, not just that nothing shows.
    const text = HIDDEN_REASON_TEXT.VISIBILITY_OWN_TEAM;
    expect(text).toMatch(/own team/i);
    expect(text).toMatch(/everyone/i);
  });

  it('never phrases an absence as an error', () => {
    for (const text of Object.values(HIDDEN_REASON_TEXT)) {
      expect(text).not.toMatch(/error|failed|unavailable/i);
      expect(text.trim().length).toBeGreaterThan(20);
    }
  });
});
