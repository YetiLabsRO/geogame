import { SimPlayer, SimTowerState, SimulationEvent } from 'shared';

/**
 * Client-side replay reconstruction (game-simulator-backend UI).
 *
 * The timeline (`SimulationEvent[]`) is the only source of truth for
 * scrubbing — no backend calls happen while dragging the slider. Events
 * don't carry a player's spawn position (SPAWN payload is just
 * `{profile_id, team_id}`), so a player's position for tick 0 is taken
 * from the `from` side of their *first* MOVE event; a player who never
 * moved (0 ticks stepped yet) has no reconstructable position and is
 * simply omitted from early frames.
 *
 * `actor_username` is the join key from an event back to a player — it's
 * unique per sim run and present on both `SimulationEvent` and the
 * baseline `SimPlayer` snapshot fetched once when a run is opened.
 */

export interface ReplayDisplayPlayer {
  profile_id: number;
  username: string;
  team_id: number | null;
  team_name: string | null;
  lat: number;
  lng: number;
  /** '' when no PROXIMITY tick has assigned a role yet (or dementors mode is off). */
  role: string;
  energy: number | null;
}

export interface ReplayDisplayTower {
  id: number;
  name: string;
  owner_team_id: number | null;
  owner_team_name: string | null;
}

export interface ReplayFrame {
  tick: number;
  players: ReplayDisplayPlayer[];
  towers: ReplayDisplayTower[];
}

interface PlayerMeta {
  profile_id: number;
  username: string;
  team_id: number | null;
  team_name: string | null;
}

/** Build one frame per tick (0..max), each a full reconstructed snapshot. */
export function buildReplayFrames(
  events: SimulationEvent[],
  baselinePlayers: SimPlayer[],
  baselineTowers: SimTowerState[],
): ReplayFrame[] {
  const byUsername = new Map<string, PlayerMeta>();
  for (const p of baselinePlayers) {
    byUsername.set(p.username, {
      profile_id: p.profile_id,
      username: p.username,
      team_id: p.team_id,
      team_name: p.team_name,
    });
  }
  const teamNames = new Map<number, string>();
  for (const p of baselinePlayers) {
    if (p.team_id !== null && p.team_name !== null) teamNames.set(p.team_id, p.team_name);
  }
  const towerNames = new Map<number, string>();
  for (const t of baselineTowers) towerNames.set(t.id, t.name);

  const sorted = [...events].sort((a, b) => a.tick - b.tick || a.id - b.id);
  const maxTick = sorted.reduce((max, e) => Math.max(max, e.tick), 0);

  const positions = new Map<number, [number, number]>();
  const ownership = new Map<number, number | null>();
  const roles = new Map<number, string>();
  const energy = new Map<number, number | null>();

  const frames: ReplayFrame[] = [];
  let cursor = 0;
  for (let tick = 0; tick <= maxTick; tick++) {
    while (cursor < sorted.length && sorted[cursor].tick === tick) {
      applyEvent(sorted[cursor], byUsername, positions, ownership, roles, energy);
      cursor++;
    }
    frames.push(
      snapshot(tick, byUsername, teamNames, towerNames, positions, ownership, roles, energy),
    );
  }
  // Always return at least the empty tick-0 frame, even with zero events
  // (a freshly-set-up run that has never been stepped).
  if (frames.length === 0) {
    frames.push(snapshot(0, byUsername, teamNames, towerNames, positions, ownership, roles, energy));
  }
  return frames;
}

function applyEvent(
  event: SimulationEvent,
  byUsername: Map<string, PlayerMeta>,
  positions: Map<number, [number, number]>,
  ownership: Map<number, number | null>,
  roles: Map<number, string>,
  energy: Map<number, number | null>,
): void {
  switch (event.action) {
    case 'MOVE': {
      const meta = event.actor_username ? byUsername.get(event.actor_username) : undefined;
      if (!meta) return;
      const from = event.payload['from'] as [number, number] | undefined;
      const to = event.payload['to'] as [number, number] | undefined;
      if (!positions.has(meta.profile_id) && from) positions.set(meta.profile_id, from);
      if (to) positions.set(meta.profile_id, to);
      return;
    }
    case 'CAPTURE': {
      const towerId = event.payload['tower_id'] as number | undefined;
      const teamId = event.payload['team_id'] as number | undefined;
      if (towerId === undefined) return;
      ownership.set(towerId, teamId ?? null);
      return;
    }
    case 'PROXIMITY': {
      const roleMap = (event.outcome['roles'] as Record<string, string> | undefined) ?? {};
      const energyMap = (event.outcome['energy'] as Record<string, number> | undefined) ?? {};
      for (const [pid, role] of Object.entries(roleMap)) {
        roles.set(Number(pid), role);
      }
      for (const [pid, value] of Object.entries(energyMap)) {
        energy.set(Number(pid), value);
      }
      return;
    }
    default:
      return; // SPAWN / TRANSITION / TICK carry no positional data
  }
}

function snapshot(
  tick: number,
  byUsername: Map<string, PlayerMeta>,
  teamNames: Map<number, string>,
  towerNames: Map<number, string>,
  positions: Map<number, [number, number]>,
  ownership: Map<number, number | null>,
  roles: Map<number, string>,
  energy: Map<number, number | null>,
): ReplayFrame {
  const players: ReplayDisplayPlayer[] = [];
  for (const meta of byUsername.values()) {
    const pos = positions.get(meta.profile_id);
    if (!pos) continue; // no move recorded yet for this player at this tick
    players.push({
      profile_id: meta.profile_id,
      username: meta.username,
      team_id: meta.team_id,
      team_name: meta.team_name,
      lat: pos[0],
      lng: pos[1],
      role: roles.get(meta.profile_id) ?? '',
      energy: energy.get(meta.profile_id) ?? null,
    });
  }
  const towers: ReplayDisplayTower[] = [];
  for (const [id, name] of towerNames.entries()) {
    const ownerTeamId = ownership.get(id) ?? null;
    towers.push({
      id,
      name,
      owner_team_id: ownerTeamId,
      owner_team_name: ownerTeamId !== null ? (teamNames.get(ownerTeamId) ?? null) : null,
    });
  }
  return { tick, players, towers };
}
