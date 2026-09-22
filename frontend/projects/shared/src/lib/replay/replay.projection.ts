import {
  ReplayAttribute,
  ReplayFrame,
  ReplayInput,
  ReplayPlayerKey,
  ReplayPlayerState,
  ReplayStanding,
  ReplayTowerState,
} from './replay.types';

/**
 * Build one full snapshot per frame from a source-agnostic `ReplayInput`.
 *
 * Three rules do all the work, and they are the reason this lives in one
 * place rather than once per source:
 *
 *  1. **Carry-forward with a staleness horizon.** A player keeps their
 *     last known position through frames where they produced no sample,
 *     because GPS gaps under tree cover are routine and blinking markers
 *     are unreadable. Past `stalenessFrames` they are dropped instead —
 *     someone who stopped pinging an hour ago must not be drawn as if
 *     they were standing still on the hillside. A `null` horizon means
 *     never stale (the simulator, where everyone moves every tick).
 *  2. **Ownership from spans**, resolved per frame, so a tower already
 *     held at frame 0 shows as held rather than appearing only once it
 *     is captured on camera.
 *  3. **Standings are derived**, counting towers held. Not the score.
 */
export function buildReplayFrames(input: ReplayInput): ReplayFrame[] {
  const frameCount = Math.max(1, input.frameCount);
  const samplesByFrame = groupSamples(input);
  const attributesByFrame = groupAttributes(input.attributes ?? []);
  const teamNames = new Map(input.teams.map((t) => [t.id, t.name]));

  // Live carry-forward state, advanced one frame at a time.
  const position = new Map<ReplayPlayerKey, { lat: number; lng: number; frame: number }>();
  const role = new Map<ReplayPlayerKey, string>();
  const energy = new Map<ReplayPlayerKey, number | null>();

  const frames: ReplayFrame[] = [];
  for (let index = 0; index < frameCount; index++) {
    for (const sample of samplesByFrame.get(index) ?? []) {
      position.set(sample.key, { lat: sample.lat, lng: sample.lng, frame: index });
    }
    for (const attribute of attributesByFrame.get(index) ?? []) {
      if (attribute.role !== undefined) role.set(attribute.key, attribute.role);
      if (attribute.energy !== undefined) energy.set(attribute.key, attribute.energy);
    }

    const players: ReplayPlayerState[] = [];
    for (const meta of input.players) {
      const fix = position.get(meta.key);
      // No sample yet, or the last one has gone stale.
      if (!fix || isStale(index, fix.frame, input.stalenessFrames)) continue;
      players.push({
        key: meta.key,
        username: meta.username,
        teamId: meta.teamId,
        teamName: meta.teamName,
        lat: fix.lat,
        lng: fix.lng,
        role: role.get(meta.key) ?? '',
        energy: energy.get(meta.key) ?? null,
      });
    }

    const towers: ReplayTowerState[] = input.towers.map((tower) => {
      const ownerTeamId = ownerAt(input, tower.id, index);
      return {
        id: tower.id,
        name: tower.name,
        lat: tower.lat,
        lng: tower.lng,
        ownerTeamId,
        ownerTeamName: ownerTeamId === null ? null : (teamNames.get(ownerTeamId) ?? null),
      };
    });

    frames.push({
      index,
      label: input.labelFor?.(index) ?? `${index}`,
      at: input.instantFor?.(index) ?? null,
      players,
      towers,
      standings: standingsFor(input, towers),
    });
  }
  return frames;
}

function isStale(frame: number, lastFrame: number, horizon: number | null): boolean {
  if (horizon === null) return false;
  return frame - lastFrame > horizon;
}

/**
 * Owner of `towerId` at `frame`, or null if unclaimed.
 *
 * Spans are half-open — `[fromFrame, toFrame)` — so the frame in which
 * a tower changes hands shows the new owner, not the old one. The last
 * matching span wins, which resolves the overlap that a same-frame
 * handover produces.
 */
function ownerAt(input: ReplayInput, towerId: number, frame: number): number | null {
  let owner: number | null = null;
  for (const span of input.ownership) {
    if (span.towerId !== towerId) continue;
    if (span.fromFrame > frame) continue;
    if (span.toFrame !== null && span.toFrame <= frame) continue;
    owner = span.teamId;
  }
  return owner;
}

function standingsFor(input: ReplayInput, towers: ReplayTowerState[]): ReplayStanding[] {
  const held = new Map<number, number>();
  for (const tower of towers) {
    if (tower.ownerTeamId === null) continue;
    held.set(tower.ownerTeamId, (held.get(tower.ownerTeamId) ?? 0) + 1);
  }
  return input.teams
    .map((team) => ({
      teamId: team.id,
      teamName: team.name,
      color: team.color,
      towersHeld: held.get(team.id) ?? 0,
    }))
    .sort((a, b) => b.towersHeld - a.towersHeld || a.teamName.localeCompare(b.teamName));
}

function groupSamples(input: ReplayInput) {
  const byFrame = new Map<number, ReplayInput['samples']>();
  for (const sample of input.samples) {
    const bucket = byFrame.get(sample.frame);
    if (bucket) bucket.push(sample);
    else byFrame.set(sample.frame, [sample]);
  }
  return byFrame;
}

function groupAttributes(attributes: ReplayAttribute[]) {
  const byFrame = new Map<number, ReplayAttribute[]>();
  for (const attribute of attributes) {
    const bucket = byFrame.get(attribute.frame);
    if (bucket) bucket.push(attribute);
    else byFrame.set(attribute.frame, [attribute]);
  }
  return byFrame;
}
