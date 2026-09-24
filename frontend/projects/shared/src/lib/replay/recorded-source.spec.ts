import { describe, expect, it } from 'vitest';

import { SessionReplayBundle } from '../staff-api.service';
import { buildReplayFrames } from './replay.projection';
import { STALENESS_FRAMES_MIN, bundleToReplayInput } from './recorded-source';

const WINDOW_FROM = '2026-09-22T10:00:00.000Z';

/** Instant `seconds` after the window start, as the API would send it. */
function at(seconds: number): string {
  return new Date(Date.parse(WINDOW_FROM) + seconds * 1000).toISOString();
}

function bundle(overrides: Partial<SessionReplayBundle> = {}): SessionReplayBundle {
  return {
    session: {
      id: 1,
      name: 'Autumn run',
      state: 'FINISHED',
      start_time: WINDOW_FROM,
      end_time: at(600),
    },
    window: { from: WINDOW_FROM, to: at(600) },
    interval_seconds: 60,
    interval_coarsened: false,
    frame_count: 11,
    teams: [
      { id: 10, name: 'alpha', color: '#003366', group_id: null },
      { id: 20, name: 'bravo', color: '#aa0000', group_id: null },
    ],
    players: [{ user_id: 5, username: 'ana', team_id: 10, team_name: 'alpha' }],
    towers: [{ id: 100, name: 'TA', lat: 46.5, lng: 23.5 }],
    zones: [],
    ownership: [],
    positions: [],
    availability: {
      location_tracking_enabled: true,
      consented_players: 1,
      roster_players: 1,
      retention_days: 7,
      retention_cutoff: null,
      earliest_ping_at: null,
      history_truncated: false,
    },
    ...overrides,
  };
}

describe('bundleToReplayInput', () => {
  it('carries frame count, roster, teams and tower geometry across', () => {
    const input = bundleToReplayInput(bundle());
    expect(input.frameCount).toBe(11);
    expect(input.players).toEqual([
      { key: 5, username: 'ana', teamId: 10, teamName: 'alpha' },
    ]);
    expect(input.teams.map((t) => t.color)).toEqual(['#003366', '#aa0000']);
    expect(input.towers[0]).toMatchObject({ id: 100, lat: 46.5, lng: 23.5 });
  });

  it('keys samples by auth user id, the join key positions use', () => {
    const input = bundleToReplayInput(
      bundle({
        positions: [
          {
            user_id: 5,
            frame: 2,
            lat: 46.1,
            lng: 23.1,
            accuracy: 8,
            recorded_at: at(120),
            received_at: at(121),
          },
        ],
      }),
    );
    expect(input.samples).toEqual([{ frame: 2, key: 5, lat: 46.1, lng: 23.1 }]);
  });

  it('converts a wall-clock ownership interval to half-open frames', () => {
    const input = bundleToReplayInput(
      bundle({
        ownership: [{ tower_id: 100, team_id: 10, start: at(120), end: at(300) }],
      }),
    );
    // 60s frames: captured at frame 2, released at frame 5 (exclusive).
    expect(input.ownership).toEqual([
      { towerId: 100, teamId: 10, fromFrame: 2, toFrame: 5 },
    ]);
  });

  it('rounds a mid-frame capture up to the next frame', () => {
    // A tower captured at 01:30 is not yet held at the 01:00 frame.
    const input = bundleToReplayInput(
      bundle({ ownership: [{ tower_id: 100, team_id: 10, start: at(90), end: null }] }),
    );
    expect(input.ownership[0].fromFrame).toBe(2);
    expect(input.ownership[0].toFrame).toBeNull();
  });

  it('clamps an interval that began before the window to frame 0', () => {
    const input = bundleToReplayInput(
      bundle({ ownership: [{ tower_id: 100, team_id: 10, start: at(-3600), end: null }] }),
    );
    expect(input.ownership[0].fromFrame).toBe(0);
  });

  it('derives a staleness horizon in frames, never below the floor', () => {
    expect(bundleToReplayInput(bundle({ interval_seconds: 60 })).stalenessFrames).toBe(
      STALENESS_FRAMES_MIN,
    );
    // At 10s frames, 120s of staleness is 12 frames.
    expect(bundleToReplayInput(bundle({ interval_seconds: 10 })).stalenessFrames).toBe(12);
  });

  it('stamps each frame with its wall-clock instant', () => {
    const input = bundleToReplayInput(bundle());
    expect(input.instantFor?.(0)).toBe(WINDOW_FROM);
    expect(input.instantFor?.(3)).toBe(at(180));
  });

  it('survives a degenerate zero-length window', () => {
    const input = bundleToReplayInput(
      bundle({ frame_count: 0, interval_seconds: 0, window: { from: WINDOW_FROM, to: WINDOW_FROM } }),
    );
    expect(input.frameCount).toBe(1);
    expect(buildReplayFrames(input)).toHaveLength(1);
  });
});

describe('recorded replay end to end', () => {
  it('shows a tower held from before the window as held at frame 0', () => {
    const frames = buildReplayFrames(
      bundleToReplayInput(
        bundle({
          ownership: [{ tower_id: 100, team_id: 10, start: at(-3600), end: null }],
        }),
      ),
    );
    expect(frames[0].towers[0].ownerTeamId).toBe(10);
    expect(frames[0].towers[0].ownerTeamName).toBe('alpha');
    expect(frames[0].standings[0]).toMatchObject({ teamName: 'alpha', towersHeld: 1 });
  });

  it('drops a player whose last sample has gone stale, then brings them back', () => {
    const position = (frame: number, lat: number) => ({
      user_id: 5,
      frame,
      lat,
      lng: 23.1,
      accuracy: null,
      recorded_at: at(frame * 60),
      received_at: at(frame * 60),
    });
    const frames = buildReplayFrames(
      bundleToReplayInput(bundle({ positions: [position(0, 46.1), position(8, 46.9)] })),
    );
    // 60s frames -> a 3-frame horizon.
    expect(frames[3].players).toHaveLength(1);
    expect(frames[4].players).toHaveLength(0);
    expect(frames[8].players[0].lat).toBeCloseTo(46.9);
  });

  it('replays ownership and standings with no location data at all', () => {
    const frames = buildReplayFrames(
      bundleToReplayInput(
        bundle({
          positions: [],
          ownership: [{ tower_id: 100, team_id: 20, start: at(0), end: null }],
          availability: { ...bundle().availability, location_tracking_enabled: false },
        }),
      ),
    );
    expect(frames.every((f) => f.players.length === 0)).toBe(true);
    expect(frames[5].towers[0].ownerTeamName).toBe('bravo');
    expect(frames[5].standings[0]).toMatchObject({ teamName: 'bravo', towersHeld: 1 });
  });
});
