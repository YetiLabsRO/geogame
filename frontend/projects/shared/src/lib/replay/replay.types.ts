/**
 * The shared replay model (session-replay capability).
 *
 * A replay is an ordered series of frames, each a *full* snapshot of the
 * game world at one point in a run — never a delta, so seeking to any
 * index costs the same as stepping to the next one.
 *
 * Two sources feed it and they differ only in their input shape:
 *
 *  - a simulator run's tick tape (`SimulationEvent[]`), where the frame
 *    index is the tick and there is no wall clock;
 *  - a recorded Session's replay bundle, where the frame index is a
 *    fixed-width time bucket and every frame has a real instant.
 *
 * Each source has its own small adapter that produces a `ReplayInput`;
 * everything downstream of that is this one projection, so replay
 * semantics have a single implementation.
 */

/** Join key for a player: the profile id for a sim run, the auth user id for a recorded one. */
export type ReplayPlayerKey = number;

export interface ReplayPlayerMeta {
  key: ReplayPlayerKey;
  username: string;
  teamId: number | null;
  teamName: string | null;
}

export interface ReplayTeamMeta {
  id: number;
  name: string;
  color: string | null;
}

export interface ReplayTowerMeta {
  id: number;
  name: string;
  /** Absent for a sim tape, whose events carry no tower geometry. */
  lat: number | null;
  lng: number | null;
}

/** A position already assigned to a frame by whichever source produced it. */
export interface ReplaySample {
  frame: number;
  key: ReplayPlayerKey;
  lat: number;
  lng: number;
}

/**
 * Tower ownership over a half-open frame range `[fromFrame, toFrame)`.
 * `toFrame === null` means still held at the end of the replay.
 */
export interface ReplayOwnershipSpan {
  towerId: number;
  teamId: number | null;
  fromFrame: number;
  toFrame: number | null;
}

/** Per-frame extras only some sources have (dementors role and energy). */
export interface ReplayAttribute {
  frame: number;
  key: ReplayPlayerKey;
  role?: string;
  energy?: number | null;
}

export interface ReplayInput {
  frameCount: number;
  players: ReplayPlayerMeta[];
  teams: ReplayTeamMeta[];
  towers: ReplayTowerMeta[];
  samples: ReplaySample[];
  ownership: ReplayOwnershipSpan[];
  attributes?: ReplayAttribute[];
  /**
   * How many frames a position may be carried forward before the player
   * is dropped from frames entirely. `null` means never go stale — the
   * simulator's semantics, where every player moves every tick.
   */
  stalenessFrames: number | null;
  /** Wall-clock instant for a frame; returns null for a simulated run. */
  instantFor?: (frame: number) => string | null;
  /** Human-readable frame label, e.g. a clock time or `Tick 12`. */
  labelFor?: (frame: number) => string;
}

export interface ReplayPlayerState {
  key: ReplayPlayerKey;
  username: string;
  teamId: number | null;
  teamName: string | null;
  lat: number;
  lng: number;
  /** '' when no source has assigned a role (dementors mode off). */
  role: string;
  energy: number | null;
}

export interface ReplayTowerState {
  id: number;
  name: string;
  lat: number | null;
  lng: number | null;
  ownerTeamId: number | null;
  ownerTeamName: string | null;
}

export interface ReplayStanding {
  teamId: number;
  teamName: string;
  color: string | null;
  /**
   * Towers held at this frame. Deliberately NOT the team's score —
   * true score accrues over time from zone control and is not
   * reconstructed here.
   */
  towersHeld: number;
}

export interface ReplayFrame {
  index: number;
  label: string;
  /** null for a simulated run, which has no real clock. */
  at: string | null;
  players: ReplayPlayerState[];
  towers: ReplayTowerState[];
  standings: ReplayStanding[];
}
