import { describe, expect, it } from 'vitest';

import { buildReplayFrames } from './replay.projection';
import { ReplayInput } from './replay.types';

function input(overrides: Partial<ReplayInput> = {}): ReplayInput {
  return {
    frameCount: 4,
    players: [
      { key: 1, username: 'ana', teamId: 10, teamName: 'alpha' },
      { key: 2, username: 'bo', teamId: 20, teamName: 'bravo' },
    ],
    teams: [
      { id: 10, name: 'alpha', color: '#003366' },
      { id: 20, name: 'bravo', color: '#aa0000' },
    ],
    towers: [
      { id: 100, name: 'TA', lat: 46.5, lng: 23.5 },
      { id: 200, name: 'TB', lat: 46.6, lng: 23.6 },
    ],
    samples: [],
    ownership: [],
    stalenessFrames: null,
    ...overrides,
  };
}

describe('buildReplayFrames', () => {
  it('produces one frame per index', () => {
    const frames = buildReplayFrames(input({ frameCount: 3 }));
    expect(frames.map((f) => f.index)).toEqual([0, 1, 2]);
  });

  it('always produces at least one frame', () => {
    expect(buildReplayFrames(input({ frameCount: 0 }))).toHaveLength(1);
  });

  it('omits a player before their first sample', () => {
    const frames = buildReplayFrames(
      input({ samples: [{ frame: 2, key: 1, lat: 46.1, lng: 23.1 }] }),
    );
    expect(frames[0].players).toHaveLength(0);
    expect(frames[1].players).toHaveLength(0);
    expect(frames[2].players.map((p) => p.username)).toEqual(['ana']);
  });

  it('carries a position forward across frames with no sample', () => {
    const frames = buildReplayFrames(
      input({ samples: [{ frame: 0, key: 1, lat: 46.1, lng: 23.1 }] }),
    );
    expect(frames[3].players[0].lat).toBeCloseTo(46.1);
  });

  it('drops a player once their position goes stale', () => {
    const frames = buildReplayFrames(
      input({
        frameCount: 5,
        stalenessFrames: 2,
        samples: [{ frame: 0, key: 1, lat: 46.1, lng: 23.1 }],
      }),
    );
    // Held through the horizon, gone beyond it.
    expect(frames[2].players).toHaveLength(1);
    expect(frames[3].players).toHaveLength(0);
  });

  it('brings a stale player back at their next sample', () => {
    const frames = buildReplayFrames(
      input({
        frameCount: 6,
        stalenessFrames: 1,
        samples: [
          { frame: 0, key: 1, lat: 46.1, lng: 23.1 },
          { frame: 4, key: 1, lat: 46.9, lng: 23.9 },
        ],
      }),
    );
    expect(frames[3].players).toHaveLength(0);
    expect(frames[4].players[0].lat).toBeCloseTo(46.9);
  });

  it('never goes stale when the horizon is null', () => {
    const frames = buildReplayFrames(
      input({ frameCount: 50, samples: [{ frame: 0, key: 1, lat: 46.1, lng: 23.1 }] }),
    );
    expect(frames[49].players).toHaveLength(1);
  });

  it('shows a tower held from before the replay as held at frame 0', () => {
    const frames = buildReplayFrames(
      input({ ownership: [{ towerId: 100, teamId: 10, fromFrame: 0, toFrame: null }] }),
    );
    const tower = frames[0].towers.find((t) => t.id === 100);
    expect(tower?.ownerTeamId).toBe(10);
    expect(tower?.ownerTeamName).toBe('alpha');
  });

  it('treats ownership spans as half-open at the closing frame', () => {
    const frames = buildReplayFrames(
      input({ ownership: [{ towerId: 100, teamId: 10, fromFrame: 1, toFrame: 3 }] }),
    );
    expect(frames[0].towers.find((t) => t.id === 100)?.ownerTeamId).toBeNull();
    expect(frames[1].towers.find((t) => t.id === 100)?.ownerTeamId).toBe(10);
    expect(frames[2].towers.find((t) => t.id === 100)?.ownerTeamId).toBe(10);
    expect(frames[3].towers.find((t) => t.id === 100)?.ownerTeamId).toBeNull();
  });

  it('shows the new owner from the frame a tower changes hands', () => {
    const frames = buildReplayFrames(
      input({
        ownership: [
          { towerId: 100, teamId: 10, fromFrame: 0, toFrame: 2 },
          { towerId: 100, teamId: 20, fromFrame: 2, toFrame: null },
        ],
      }),
    );
    expect(frames[1].towers.find((t) => t.id === 100)?.ownerTeamId).toBe(10);
    expect(frames[2].towers.find((t) => t.id === 100)?.ownerTeamId).toBe(20);
  });

  it('reports an unclaimed tower as unowned', () => {
    const frames = buildReplayFrames(input());
    expect(frames[0].towers.every((t) => t.ownerTeamId === null)).toBe(true);
  });

  it('derives standings from towers held, leaders first', () => {
    const frames = buildReplayFrames(
      input({
        ownership: [
          { towerId: 100, teamId: 20, fromFrame: 0, toFrame: null },
          { towerId: 200, teamId: 20, fromFrame: 0, toFrame: null },
        ],
      }),
    );
    expect(frames[0].standings.map((s) => [s.teamName, s.towersHeld])).toEqual([
      ['bravo', 2],
      ['alpha', 0],
    ]);
  });

  it('includes every team in standings even at zero', () => {
    const frames = buildReplayFrames(input());
    expect(frames[0].standings).toHaveLength(2);
    expect(frames[0].standings.every((s) => s.towersHeld === 0)).toBe(true);
  });

  it('applies role and energy attributes and carries them forward', () => {
    const frames = buildReplayFrames(
      input({
        samples: [{ frame: 0, key: 1, lat: 46.1, lng: 23.1 }],
        attributes: [{ frame: 1, key: 1, role: 'DEMENTOR', energy: 7 }],
      }),
    );
    expect(frames[0].players[0].role).toBe('');
    expect(frames[0].players[0].energy).toBeNull();
    expect(frames[1].players[0].role).toBe('DEMENTOR');
    expect(frames[2].players[0].energy).toBe(7);
  });

  it('labels and timestamps frames through the supplied callbacks', () => {
    const frames = buildReplayFrames(
      input({
        frameCount: 2,
        labelFor: (f) => `Tick ${f}`,
        instantFor: (f) => (f === 0 ? '2026-09-22T10:00:00Z' : null),
      }),
    );
    expect(frames[0].label).toBe('Tick 0');
    expect(frames[0].at).toBe('2026-09-22T10:00:00Z');
    expect(frames[1].at).toBeNull();
  });
});
