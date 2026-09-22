import {
  ReplayFrame,
  ReplayInput,
  ReplayOwnershipSpan,
  SimPlayer,
  SimTowerState,
  SimulationEvent,
  buildReplayFrames as buildFrames,
} from 'shared';

/**
 * Simulator adapter onto the shared replay projection (session-replay).
 *
 * The tape (`SimulationEvent[]`) remains the only source of truth for
 * scrubbing — no backend calls happen while dragging the slider. What
 * changed is that the *semantics* of a frame (carry-forward, ownership
 * resolution, standings) now live in `shared/replay` and are shared with
 * recorded-Session replay, so a fix to one fixes both. This file does
 * two jobs and nothing else: map a tick tape onto `ReplayInput`, and map
 * the projection's output back to the snake_case shape this page's map
 * and tables already render.
 *
 * `actor_username` is the join key from an event back to a player — it
 * is unique per sim run and present on both `SimulationEvent` and the
 * baseline `SimPlayer` snapshot fetched when a run is opened.
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

export interface ReplayDisplayFrame {
  tick: number;
  players: ReplayDisplayPlayer[];
  towers: ReplayDisplayTower[];
}

/** Build one frame per tick (0..max), each a full reconstructed snapshot. */
export function buildReplayFrames(
  events: SimulationEvent[],
  baselinePlayers: SimPlayer[],
  baselineTowers: SimTowerState[],
): ReplayDisplayFrame[] {
  return buildFrames(toReplayInput(events, baselinePlayers, baselineTowers)).map(toDisplay);
}

function toReplayInput(
  events: SimulationEvent[],
  baselinePlayers: SimPlayer[],
  baselineTowers: SimTowerState[],
): ReplayInput {
  const byUsername = new Map(baselinePlayers.map((p) => [p.username, p]));
  const sorted = [...events].sort((a, b) => a.tick - b.tick || a.id - b.id);
  const maxTick = sorted.reduce((max, e) => Math.max(max, e.tick), 0);

  const samples: ReplayInput['samples'] = [];
  const attributes: ReplayInput['attributes'] = [];
  // A capture closes the tower's previous span and opens a new one, which
  // reproduces the tape's "latest capture wins" semantics as spans.
  const ownership: ReplayOwnershipSpan[] = [];
  const openSpan = new Map<number, ReplayOwnershipSpan>();

  for (const event of sorted) {
    switch (event.action) {
      case 'MOVE': {
        const player = event.actor_username ? byUsername.get(event.actor_username) : undefined;
        if (!player) break;
        const to = event.payload['to'] as [number, number] | undefined;
        const from = event.payload['from'] as [number, number] | undefined;
        const at = to ?? from;
        if (at) {
          samples.push({ frame: event.tick, key: player.profile_id, lat: at[0], lng: at[1] });
        }
        break;
      }
      case 'CAPTURE': {
        const towerId = event.payload['tower_id'] as number | undefined;
        if (towerId === undefined) break;
        const teamId = (event.payload['team_id'] as number | undefined) ?? null;
        const previous = openSpan.get(towerId);
        if (previous) previous.toFrame = event.tick;
        const span: ReplayOwnershipSpan = {
          towerId,
          teamId,
          fromFrame: event.tick,
          toFrame: null,
        };
        ownership.push(span);
        openSpan.set(towerId, span);
        break;
      }
      case 'PROXIMITY': {
        const roles = (event.outcome['roles'] as Record<string, string> | undefined) ?? {};
        const energy = (event.outcome['energy'] as Record<string, number> | undefined) ?? {};
        for (const [pid, role] of Object.entries(roles)) {
          attributes.push({ frame: event.tick, key: Number(pid), role });
        }
        for (const [pid, value] of Object.entries(energy)) {
          attributes.push({ frame: event.tick, key: Number(pid), energy: value });
        }
        break;
      }
      default:
        break; // SPAWN / TRANSITION / TICK carry no positional data
    }
  }

  return {
    frameCount: maxTick + 1,
    players: baselinePlayers.map((p) => ({
      key: p.profile_id,
      username: p.username,
      teamId: p.team_id,
      teamName: p.team_name,
    })),
    teams: teamsFrom(baselinePlayers),
    // A sim tape carries no tower geometry; the page looks coordinates
    // up separately from the run's tower list.
    towers: baselineTowers.map((t) => ({ id: t.id, name: t.name, lat: null, lng: null })),
    samples,
    ownership,
    attributes,
    // Every simulated player moves every tick, so a carried-forward
    // position is never stale.
    stalenessFrames: null,
  };
}

function teamsFrom(players: SimPlayer[]): ReplayInput['teams'] {
  const teams = new Map<number, string>();
  for (const player of players) {
    if (player.team_id !== null && player.team_name !== null) {
      teams.set(player.team_id, player.team_name);
    }
  }
  return Array.from(teams.entries()).map(([id, name]) => ({ id, name, color: null }));
}

function toDisplay(frame: ReplayFrame): ReplayDisplayFrame {
  return {
    tick: frame.index,
    players: frame.players.map((p) => ({
      profile_id: p.key,
      username: p.username,
      team_id: p.teamId,
      team_name: p.teamName,
      lat: p.lat,
      lng: p.lng,
      role: p.role,
      energy: p.energy,
    })),
    towers: frame.towers.map((t) => ({
      id: t.id,
      name: t.name,
      owner_team_id: t.ownerTeamId,
      owner_team_name: t.ownerTeamName,
    })),
  };
}
