import { SessionReplayBundle } from '../staff-api.service';
import { ReplayInput, ReplayOwnershipSpan } from './replay.types';

/** A position older than this is no longer credible as "where they are". */
export const STALENESS_SECONDS = 120;
/** ...but never a horizon shorter than this many frames. */
export const STALENESS_FRAMES_MIN = 3;

/**
 * Map a recorded Session's replay bundle onto the shared projection input.
 *
 * Two conversions carry the weight. Wall-clock ownership intervals become
 * half-open *frame* ranges, so the frame in which a tower changes hands
 * already shows the new owner rather than lagging by one. And the
 * staleness horizon, which the design states in seconds, becomes a frame
 * count, since frames are what the projection counts in.
 */
export function bundleToReplayInput(bundle: SessionReplayBundle): ReplayInput {
  const windowFrom = Date.parse(bundle.window.from);
  const interval = Math.max(1, bundle.interval_seconds);
  const frameCount = Math.max(1, bundle.frame_count);

  // Frame `f` represents the instant `windowFrom + f * interval`, so the
  // first frame at or after an instant is its ceiling.
  const frameAtOrAfter = (iso: string): number =>
    Math.max(0, Math.ceil((Date.parse(iso) - windowFrom) / 1000 / interval));

  const ownership: ReplayOwnershipSpan[] = bundle.ownership.map((row) => ({
    towerId: row.tower_id,
    teamId: row.team_id,
    fromFrame: frameAtOrAfter(row.start),
    toFrame: row.end === null ? null : frameAtOrAfter(row.end),
  }));

  const instantOf = (frame: number) => new Date(windowFrom + frame * interval * 1000);

  return {
    frameCount,
    players: bundle.players.map((p) => ({
      key: p.user_id,
      username: p.username,
      teamId: p.team_id,
      teamName: p.team_name,
    })),
    teams: bundle.teams.map((t) => ({ id: t.id, name: t.name, color: t.color })),
    towers: bundle.towers.map((t) => ({ id: t.id, name: t.name, lat: t.lat, lng: t.lng })),
    samples: bundle.positions.map((p) => ({
      frame: p.frame,
      key: p.user_id,
      lat: p.lat,
      lng: p.lng,
    })),
    ownership,
    stalenessFrames: Math.max(STALENESS_FRAMES_MIN, Math.ceil(STALENESS_SECONDS / interval)),
    instantFor: (frame) => instantOf(frame).toISOString(),
    labelFor: (frame) =>
      instantOf(frame).toLocaleTimeString(undefined, {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
      }),
  };
}
