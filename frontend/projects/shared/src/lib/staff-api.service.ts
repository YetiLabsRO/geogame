import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { ChallengeType, ReviewMode, ScoreMultiplierScope, ScoreMultiplierType } from './game-api.service';

export type SubmissionOutcome = 0 | 1 | 2; // PENDING, CONFIRMED, REJECTED
export type SubmissionFilter = 'pending' | 'confirmed' | 'rejected' | 'all';

export interface StaffSubmission {
  id: number;
  team: number;
  team_name: string;
  team_color: string;
  tower: number;
  tower_name: string;
  challenge: number | null;
  challenge_text: string | null;
  challenge_difficulty: number | null;
  /** challenge-type-system: type of the submitted challenge (RFID for challenge-less scans). */
  challenge_type: ChallengeType | string | null;
  submitted_by: number | null;
  submitted_by_username: string | null;
  photo_url: string | null;
  /** Scanned code carried by scan-type submissions (audit trail). */
  submitted_code: string | null;
  /** True when the outcome was resolved by the system (AUTO types), not staff. */
  auto_resolved: boolean;
  timestamp_submitted: string;
  timestamp_verified: string | null;
  outcome: SubmissionOutcome;
  response_text: string;
  /** Presence evidence (presence-rules); null for ungated submissions. */
  presence_check: PresenceCheckInfo | null;
}

/** Persisted presence evidence for a submission (presence-rules capability). */
export interface PresenceCheckInfo {
  required_count: number;
  present_count: number;
  method: PresenceMethod;
  verified_member_ids: number[];
  window_seconds: number;
  /** null = the window could not be evaluated (live-location unavailable). */
  window_satisfied: boolean | null;
  satisfied: boolean;
  reason_code: string;
}

/** An active tower lock as listed on /api/staff/tower_locks/ (tower-locking). */
export interface StaffTowerLock {
  id: number;
  tower: number;
  tower_name: string;
  team: number;
  team_name: string;
  team_color: string;
  group: number | null;
  group_name: string | null;
  started_at: string;
  expires_at: string;
  released_at: string | null;
  release_reason: 'FINISHED' | 'EXPIRED' | 'CANCELLED' | null;
  remaining_seconds: number;
}

/** A Collection or Game referencing a repository asset (usage reporting). */
export interface UsageRef {
  id: number;
  name: string;
}

/** Zone conquest rules (zone-conquest-and-scoring-config). */
export type ConquestRule = 'ALL' | 'MAJORITY' | 'ANY';

// ---- tower-visibility -------------------------------------------------------

/** Tower discoverability axis: whether/when a tower appears on the map. */
export type Discoverability = 'HIDDEN' | 'VISIBLE' | 'FOG_REVEAL';

/** Challenge visibility axis: whether the challenge is legible from afar. */
export type ChallengeVisibility = 'HIDDEN_UNTIL_ARRIVAL' | 'VISIBLE_ANYWHERE';

/** Visibility knobs shared by Game (defaults) and Session (overrides). */
export interface TowerVisibilityConfig {
  tower_discoverability_default: Discoverability;
  challenge_visibility_default: ChallengeVisibility;
  fog_reveal_coverage_pct_default: number;
  reveal_other_teams_ownership: boolean;
}

/** Per-session visibility overrides: null inherits the Game default. */
export type TowerVisibilityOverrides = {
  [K in keyof TowerVisibilityConfig]: TowerVisibilityConfig[K] | null;
};

/** Scoring time units — the unit zone scores accrue per. */
export type ScoreTimeUnit = 'SECOND' | 'MINUTE' | 'HOUR';

/** A curator-captured reference photo of a tower (field-authoring-mode). */
export interface TowerPhotoInfo {
  id: number;
  tower: number;
  image: string;
  caption: string;
  captured_by: number | null;
  captured_by_username: string | null;
  captured_at: string;
}

export interface AdminTower {
  id: number;
  name: string;
  /** Many-to-many zone membership (tower-zone-topology). */
  zones: number[];
  category: number;
  is_active: boolean;
  /** Per-tower capture radius; null inherits the Game default. */
  proximity_meters: number | null;
  /** tower-visibility axes; null inherits the Session/Game default. */
  discoverability: Discoverability | null;
  challenge_visibility: ChallengeVisibility | null;
  initial_bonus: number;
  rfid_code: string | null;
  location: { type: 'Point'; coordinates: [number, number] } | null;
  authored_accuracy_m: number | null;
  photos: TowerPhotoInfo[];
  collections: UsageRef[];
  games: UsageRef[];
}

/** Create-at-GPS payload (field-authoring-mode task 2.1). */
export interface CreateTowerPayload {
  name: string;
  lat: number;
  lng: number;
  /** Member zones via the many-to-many (tower-zone-topology). */
  zones?: number[];
  category?: number;
  is_active?: boolean;
  initial_bonus?: number;
  /** GPS accuracy (m) of the capture fix — provenance, desk creates omit it. */
  authored_accuracy_m?: number | null;
  /** Target Collection the new tower is filed into in the same call. */
  collection?: number | null;
}

export interface AdminZone {
  id: number;
  name: string;
  color: string;
  scoring_type: number;
  /** Per-zone conquest override; null inherits Session/Game. */
  conquest_rule: ConquestRule | null;
  /** Fog-of-war reveal threshold (%); null inherits Session/Game. */
  fog_reveal_coverage_pct: number | null;
  /** Member towers via the many-to-many (read-only). */
  towers: UsageRef[];
  shape: { type: 'Polygon'; coordinates: number[][][] } | null;
  collections: UsageRef[];
  games: UsageRef[];
}

/** Walked/tapped boundary payload (field-authoring-mode task 2.3). */
export interface CreateZonePayload {
  name: string;
  scoring_type?: number;
  color?: string;
  /** Boundary as [lng, lat] pairs in capture order; ring closed server-side. */
  vertices: [number, number][];
  /** Target Collection the new zone is filed into in the same call. */
  collection?: number | null;
}

/** Attach a Challenge to a tower on site (field-authoring-mode task 2.4). */
export type AttachChallengePayload =
  | { challenge: number }
  | { game: number; text: string; difficulty?: number };

export interface AdminCollection {
  id: number;
  name: string;
  slug: string;
  description: string;
  created_by: number | null;
  created_by_username: string | null;
  created_at: string;
  towers: number[];
  zones: number[];
  games: UsageRef[];
}

export interface AdminCollectionPayload {
  name?: string;
  slug?: string;
  description?: string;
}

export interface AdminTeam {
  id: number;
  name: string;
  game: number;
  group: number | null;
  color: string;
  description: string | null;
  active_member_count: number;
  is_ready: boolean;
  members_needed: number;
  captain: number | null;
  captain_username: string | null;
  team_join_confirmation: TeamJoinConfirmation | null;
  join_code: string | null;
}

export interface AdminTeamGroup {
  id: number;
  name: string;
  game: number;
  slug: string;
}

export type RoleRequirementMode = 'NONE' | 'ALL' | 'ANY';

export interface AdminChallenge {
  id: number;
  game: number | null;
  text: string;
  tower: number | null;
  difficulty: number;
  /** challenge-type-system: type + per-type configuration. */
  type: ChallengeType | string;
  /** Handout code for NFC_QR (staff-only; never sent to players). */
  validation_code: string | null;
  /** Per-type extras, e.g. { venue_label: 'Bar X', single_use: true }. */
  type_config: Record<string, unknown>;
  /** Optional override of the type's default review flow. */
  review_mode: ReviewMode | null;
  role_requirement_mode: RoleRequirementMode;
  required_roles: number[];
  require_holders_present: boolean;
  /** presence-rules: null = no presence requirement. */
  presence_requirement: number | null;
}

// ---- presence-rules ---------------------------------------------------------

export type PresenceMethod = 'GEOFENCE' | 'PHOTO' | 'GEOFENCE_OR_PHOTO';
export type TogethernessMode = 'SPLIT_ALLOWED' | 'WHOLE_TEAM_TOGETHER';
export type TeammateVisibilityMode = 'OWN_TEAM' | 'EVERYONE' | 'SELECT_COUNT';

/** A named, reusable presence requirement referenced by challenges. */
export interface AdminPresenceRequirement {
  id: number;
  name: string;
  min_members_present: number;
  method: PresenceMethod;
  /** null falls back to the tower's effective proximity_meters. */
  geofence_radius_meters: number | null;
  /** null falls back to the Session's effective presence_window_seconds. */
  window_seconds: number | null;
  challenge_count: number;
}

export type AdminPresenceRequirementPayload = Partial<
  Omit<AdminPresenceRequirement, 'id' | 'challenge_count'>
>;

/** Presence knobs shared by Game (defaults) and Session (overrides). */
export interface PresenceRulesConfig {
  togetherness_mode: TogethernessMode;
  teammate_visibility_mode: TeammateVisibilityMode;
  teammate_visibility_count: number;
  presence_window_seconds: number;
}

/** Per-session presence overrides: null inherits the Game default. */
export type PresenceRulesOverrides = {
  [K in keyof PresenceRulesConfig]: PresenceRulesConfig[K] | null;
};

export type BuiltinPower = 'NONE' | 'INVITER';

export interface AdminGameRole {
  id: number;
  game: number;
  name: string;
  slug: string;
  description: string;
  builtin_power: BuiltinPower;
  created_at: string | null;
}

export type AdminGameRolePayload = Partial<Omit<AdminGameRole, 'id' | 'created_at'>>;

export interface RoleSummary {
  id: number;
  slug: string;
  name: string;
  builtin_power: BuiltinPower;
}

export interface AdminMembership {
  id: number;
  team: number;
  user: number;
  username: string;
  first_name: string;
  last_name: string;
  is_active: boolean;
  joined_at: string;
  roles: RoleSummary[];
}

export type FailCounterReset =
  | 'TOWER_SUCCESS_ONLY'
  | 'ANY_SUCCESS_ELSEWHERE'
  | 'ANY_ATTEMPT_ELSEWHERE';

/** Phase 10 config knobs shared by Game (defaults) and Session (overrides). */
export interface Phase10Config {
  pause_freezes_floating_score: boolean;
  pause_restores_ownerships_on_resume: boolean;
  pause_rejects_submissions: boolean;
  fail_point_penalty: number;
  fail_cooloff_scaling: number;
  fail_tower_lockout_minutes: number;
  fail_difficulty_rollback: boolean;
  fail_counter_reset: FailCounterReset;
}

/** Team-composition rules: minima ≥ 1, maxima use 0 to mean "no cap". */
export interface TeamRulesConfig {
  min_teams: number;
  max_teams: number;
  min_members_per_team: number;
  max_members_per_team: number;
}

/** Per-session team-rule overrides: null means "inherit the Game default". */
export type TeamRulesOverrides = {
  [K in keyof TeamRulesConfig]: TeamRulesConfig[K] | null;
};

export type TeamJoinConfirmation = 'AUTO_APPROVE' | 'CAPTAIN' | 'STAFF';

export type LocationVisibility = 'NONE' | 'OWN_TEAM' | 'EVERYONE';

/** Live-location knobs shared by Game (defaults) and Session (overrides). */
export interface LocationTrackingConfig {
  location_tracking_enabled: boolean;
  location_ping_interval_seconds: number;
  location_visibility: LocationVisibility;
  location_retention_days: number;
  location_consent_text: string;
}

/** Per-session live-location overrides: null inherits the Game default. */
export type LocationTrackingOverrides = {
  [K in keyof LocationTrackingConfig]: LocationTrackingConfig[K] | null;
};

export interface AdminGame
  extends Phase10Config,
    TeamRulesConfig,
    LocationTrackingConfig,
    PresenceRulesConfig,
    TowerVisibilityConfig {
  id: number;
  slug: string;
  name: string;
  base_point: { type: 'Point'; coordinates: [number, number] } | null;
  base_zoom_level: number;
  is_active: boolean;
  proximity_meters: number;
  cooloff_minutes: number;
  initial_bonus_default: number;
  /** Game-wide conquest-rule default (zone-conquest-and-scoring-config). */
  zone_conquest_rule: ConquestRule;
  /** Game-wide scoring time-unit default. */
  score_time_unit: ScoreTimeUnit;
  allow_player_team_creation: boolean;
  team_join_confirmation: TeamJoinConfirmation;
  collections: number[];
  created_by: number | null;
  created_by_username: string | null;
  cloned_from: number | null;
  created_at: string | null;
}

export type AdminGamePayload = Partial<
  Omit<
    AdminGame,
    'id' | 'base_point' | 'created_by' | 'created_by_username' | 'cloned_from' | 'created_at'
  >
> & {
  base_lat?: number | null;
  base_lng?: number | null;
};

/** Per-session overrides: null means "inherit the Game default". */
export type Phase10Overrides = {
  [K in keyof Phase10Config]: Phase10Config[K] | null;
};

/** Session lifecycle states (session-lifecycle capability). */
export type SessionState =
  | 'DRAFT'
  | 'OPEN_FOR_PARTICIPANTS'
  | 'RUNNING'
  | 'PAUSED'
  | 'FINISHED';

/** Lifecycle actions, each driving one edge of the transition table. */
export type SessionTransitionAction =
  | 'open_participation'
  | 'close_participation'
  | 'start'
  | 'pause'
  | 'resume'
  | 'finish';

export interface AdminSession
  extends Phase10Overrides,
    TeamRulesOverrides,
    LocationTrackingOverrides,
    PresenceRulesOverrides,
    TowerVisibilityOverrides {
  id: number;
  /** Per-session override; null inherits the Game default. */
  allow_player_team_creation: boolean | null;
  /** Conquest-rule override; null inherits the Game default. */
  zone_conquest_rule: ConquestRule | null;
  /** Scoring time-unit override; null inherits the Game default. */
  score_time_unit: ScoreTimeUnit | null;
  game: number;
  game_slug: string;
  game_name: string;
  slug: string;
  name: string;
  start_time: string;
  end_time: string;
  scheduled_start: string | null;
  state: SessionState;
  allowed_transitions: SessionTransitionAction[];
  is_active: boolean;
  is_paused: boolean;
  created_at: string | null;
}

export type AdminSessionPayload = Partial<
  Omit<
    AdminSession,
    | 'id'
    | 'game_slug'
    | 'game_name'
    | 'state'
    | 'allowed_transitions'
    | 'is_active'
    | 'is_paused'
    | 'created_at'
  >
>;

export interface TeamBuildResult {
  teams: { id: number; name: string; members: string[] }[];
  assigned: number;
}

export interface PauseWindowInfo {
  id: number;
  started_at: string;
  ended_at: string | null;
  restore_on_resume: boolean;
}

export interface PauseHistory {
  is_paused: boolean;
  windows: PauseWindowInfo[];
}

export interface FailCounterInfo {
  team_id: number;
  team_name: string;
  team_color: string;
  tower_id: number;
  tower_name: string;
  consecutive_fails: number;
  locked_until: string | null;
  is_locked: boolean;
}

/** One reason a Session may not start (machine `code` + human `message`). */
export interface StartBlocker {
  code:
    | 'too_few_teams'
    | 'too_many_teams'
    | 'team_below_minimum'
    | 'team_above_maximum';
  message: string;
  required?: number;
  allowed?: number;
  current?: number;
  shortfall?: number;
  team_id?: number;
  team_name?: string;
}

export interface StartReadinessTeam {
  id: number;
  name: string;
  color: string;
  active_member_count: number;
  is_ready: boolean;
  members_needed: number;
}

export interface StartReadiness {
  can_start: boolean;
  blockers: StartBlocker[];
  min_members_per_team: number;
  teams: StartReadinessTeam[];
}

@Injectable({ providedIn: 'root' })
export class StaffApiService {
  private readonly http = inject(HttpClient);

  listSubmissions(filter: SubmissionFilter = 'pending'): Observable<StaffSubmission[]> {
    return this.http.get<StaffSubmission[]>(`/api/staff/submissions/?outcome=${filter}`);
  }

  confirmSubmission(id: number): Observable<StaffSubmission> {
    return this.http.post<StaffSubmission>(
      `/api/staff/submissions/${id}/review/`,
      { outcome: 'confirm' },
    );
  }

  rejectSubmission(id: number, responseText = ''): Observable<StaffSubmission> {
    return this.http.post<StaffSubmission>(
      `/api/staff/submissions/${id}/review/`,
      { outcome: 'reject', response_text: responseText },
    );
  }

  // ---- Tower locks (tower-locking) ----------------------------------------

  /** Active locks in the current session, soonest deadline first. */
  listTowerLocks(): Observable<StaffTowerLock[]> {
    return this.http.get<StaffTowerLock[]>('/api/staff/tower_locks/');
  }

  /** Force-release an active lock (release_reason=CANCELLED). */
  cancelTowerLock(id: number): Observable<StaffTowerLock> {
    return this.http.post<StaffTowerLock>(
      `/api/staff/tower_locks/${id}/cancel/`,
      {},
    );
  }

  // ---- Admin CRUD ---------------------------------------------------------

  listTowers(collectionId?: number): Observable<AdminTower[]> {
    const query = collectionId ? `?collection=${collectionId}` : '';
    return this.http.get<AdminTower[]>(`/api/staff/towers/${query}`);
  }

  /** Field authoring: drop a tower at a GPS fix, filing it into a Collection. */
  createTower(payload: CreateTowerPayload): Observable<AdminTower> {
    return this.http.post<AdminTower>('/api/staff/towers/', payload);
  }

  updateTower(
    id: number,
    patch: Partial<AdminTower> & { lat?: number; lng?: number },
  ): Observable<AdminTower> {
    return this.http.patch<AdminTower>(`/api/staff/towers/${id}/`, patch);
  }

  // ---- Field authoring: reference photos + attach-challenge ----------------

  listTowerPhotos(towerId: number): Observable<TowerPhotoInfo[]> {
    return this.http.get<TowerPhotoInfo[]>(`/api/staff/towers/${towerId}/photos/`);
  }

  /** `image` is a base64 data URL (client-side compressed capture). */
  uploadTowerPhoto(
    towerId: number,
    payload: { image: string; caption?: string },
  ): Observable<TowerPhotoInfo> {
    return this.http.post<TowerPhotoInfo>(
      `/api/staff/towers/${towerId}/photos/`,
      payload,
    );
  }

  deleteTowerPhoto(towerId: number, photoId: number): Observable<void> {
    return this.http.delete<void>(`/api/staff/towers/${towerId}/photos/${photoId}/`);
  }

  attachChallenge(
    towerId: number,
    payload: AttachChallengePayload,
  ): Observable<AdminChallenge> {
    return this.http.post<AdminChallenge>(
      `/api/staff/towers/${towerId}/attach-challenge/`,
      payload,
    );
  }

  unassignTower(id: number): Observable<AdminTower> {
    return this.http.post<AdminTower>(`/api/staff/towers/${id}/unassign/`, {});
  }

  unassignAllTowers(): Observable<{ unassigned: number[] }> {
    return this.http.post<{ unassigned: number[] }>(
      '/api/staff/towers/unassign_all/',
      {},
    );
  }

  listZones(collectionId?: number): Observable<AdminZone[]> {
    const query = collectionId ? `?collection=${collectionId}` : '';
    return this.http.get<AdminZone[]>(`/api/staff/zones/${query}`);
  }

  /** Field authoring: create a zone from walked/tapped vertices. */
  createZone(payload: CreateZonePayload): Observable<AdminZone> {
    return this.http.post<AdminZone>('/api/staff/zones/', payload);
  }

  updateZone(
    id: number,
    patch: Partial<AdminZone> & { vertices?: [number, number][] },
  ): Observable<AdminZone> {
    return this.http.patch<AdminZone>(`/api/staff/zones/${id}/`, patch);
  }

  listTeams(): Observable<AdminTeam[]> {
    return this.http.get<AdminTeam[]>('/api/staff/teams/');
  }

  updateTeam(id: number, patch: Partial<AdminTeam>): Observable<AdminTeam> {
    return this.http.patch<AdminTeam>(`/api/staff/teams/${id}/`, patch);
  }

  listTeamGroups(): Observable<AdminTeamGroup[]> {
    return this.http.get<AdminTeamGroup[]>('/api/staff/team-groups/');
  }

  listChallenges(): Observable<AdminChallenge[]> {
    return this.http.get<AdminChallenge[]>('/api/staff/challenges/');
  }

  createChallenge(payload: Omit<AdminChallenge, 'id'>): Observable<AdminChallenge> {
    return this.http.post<AdminChallenge>('/api/staff/challenges/', payload);
  }

  updateChallenge(id: number, patch: Partial<AdminChallenge>): Observable<AdminChallenge> {
    return this.http.patch<AdminChallenge>(`/api/staff/challenges/${id}/`, patch);
  }

  deleteChallenge(id: number): Observable<void> {
    return this.http.delete<void>(`/api/staff/challenges/${id}/`);
  }

  // ---- team-roles: role definitions + roster assignment --------------------

  listGameRoles(gameId?: number): Observable<AdminGameRole[]> {
    const query = gameId ? `?game=${gameId}` : '';
    return this.http.get<AdminGameRole[]>(`/api/staff/game_roles/${query}`);
  }

  createGameRole(payload: AdminGameRolePayload): Observable<AdminGameRole> {
    return this.http.post<AdminGameRole>('/api/staff/game_roles/', payload);
  }

  updateGameRole(id: number, patch: AdminGameRolePayload): Observable<AdminGameRole> {
    return this.http.patch<AdminGameRole>(`/api/staff/game_roles/${id}/`, patch);
  }

  deleteGameRole(id: number): Observable<void> {
    return this.http.delete<void>(`/api/staff/game_roles/${id}/`);
  }

  listMemberships(teamId?: number): Observable<AdminMembership[]> {
    const query = teamId ? `?team=${teamId}` : '';
    return this.http.get<AdminMembership[]>(`/api/staff/memberships/${query}`);
  }

  assignRole(membershipId: number, roleId: number): Observable<AdminMembership> {
    return this.http.post<AdminMembership>(
      `/api/staff/memberships/${membershipId}/assign_role/`,
      { role: roleId },
    );
  }

  unassignRole(membershipId: number, roleId: number): Observable<AdminMembership> {
    return this.http.post<AdminMembership>(
      `/api/staff/memberships/${membershipId}/unassign_role/`,
      { role: roleId },
    );
  }

  resetScores(): Observable<{ teams_reset: number }> {
    return this.http.post<{ teams_reset: number }>(
      '/api/staff/game-state/reset-scores/',
      {},
    );
  }

  // ---- Collections (points repository) -------------------------------------

  listCollections(): Observable<AdminCollection[]> {
    return this.http.get<AdminCollection[]>('/api/staff/collections/');
  }

  createCollection(payload: AdminCollectionPayload): Observable<AdminCollection> {
    return this.http.post<AdminCollection>('/api/staff/collections/', payload);
  }

  updateCollection(
    id: number,
    payload: AdminCollectionPayload,
  ): Observable<AdminCollection> {
    return this.http.patch<AdminCollection>(`/api/staff/collections/${id}/`, payload);
  }

  deleteCollection(id: number): Observable<void> {
    return this.http.delete<void>(`/api/staff/collections/${id}/`);
  }

  addCollectionTowers(id: number, towerIds: number[]): Observable<AdminCollection> {
    return this.http.post<AdminCollection>(
      `/api/staff/collections/${id}/add-towers/`,
      { tower_ids: towerIds },
    );
  }

  removeCollectionTowers(id: number, towerIds: number[]): Observable<AdminCollection> {
    return this.http.post<AdminCollection>(
      `/api/staff/collections/${id}/remove-towers/`,
      { tower_ids: towerIds },
    );
  }

  addCollectionZones(id: number, zoneIds: number[]): Observable<AdminCollection> {
    return this.http.post<AdminCollection>(
      `/api/staff/collections/${id}/add-zones/`,
      { zone_ids: zoneIds },
    );
  }

  removeCollectionZones(id: number, zoneIds: number[]): Observable<AdminCollection> {
    return this.http.post<AdminCollection>(
      `/api/staff/collections/${id}/remove-zones/`,
      { zone_ids: zoneIds },
    );
  }

  // ---- Games ---------------------------------------------------------------

  listGames(): Observable<AdminGame[]> {
    return this.http.get<AdminGame[]>('/api/staff/games/');
  }

  getGame(id: number): Observable<AdminGame> {
    return this.http.get<AdminGame>(`/api/staff/games/${id}/`);
  }

  cloneGame(
    id: number,
    payload: { name?: string; slug?: string } = {},
  ): Observable<AdminGame> {
    return this.http.post<AdminGame>(`/api/staff/games/${id}/clone/`, payload);
  }

  createGame(payload: AdminGamePayload): Observable<AdminGame> {
    return this.http.post<AdminGame>('/api/staff/games/', payload);
  }

  updateGame(id: number, payload: AdminGamePayload): Observable<AdminGame> {
    return this.http.patch<AdminGame>(`/api/staff/games/${id}/`, payload);
  }

  // ---- Sessions ------------------------------------------------------------

  listSessions(gameId?: number): Observable<AdminSession[]> {
    const query = gameId ? `?game=${gameId}` : '';
    return this.http.get<AdminSession[]>(`/api/staff/sessions/${query}`);
  }

  getSession(id: number): Observable<AdminSession> {
    return this.http.get<AdminSession>(`/api/staff/sessions/${id}/`);
  }

  createSession(payload: AdminSessionPayload): Observable<AdminSession> {
    return this.http.post<AdminSession>('/api/staff/sessions/', payload);
  }

  updateSession(
    id: number,
    payload: AdminSessionPayload,
  ): Observable<AdminSession> {
    return this.http.patch<AdminSession>(`/api/staff/sessions/${id}/`, payload);
  }

  // ---- Session lifecycle transitions (session-lifecycle) -------------------

  transitionSession(
    id: number,
    action: SessionTransitionAction,
    override = false,
  ): Observable<AdminSession> {
    return this.http.post<AdminSession>(
      `/api/staff/sessions/${id}/${action}/`,
      override ? { override: true } : {},
    );
  }

  // ---- Phase 10: day pausing + failure observability -----------------------

  pauseSession(id: number): Observable<AdminSession> {
    return this.transitionSession(id, 'pause');
  }

  shuffleTeams(id: number, teamCount: number): Observable<TeamBuildResult> {
    return this.http.post<TeamBuildResult>(`/api/staff/sessions/${id}/shuffle-teams/`, {
      team_count: teamCount,
    });
  }

  balanceTeams(
    id: number,
    teamCount: number,
    attributeKeys: string[],
  ): Observable<TeamBuildResult> {
    return this.http.post<TeamBuildResult>(`/api/staff/sessions/${id}/balance-teams/`, {
      team_count: teamCount,
      attribute_keys: attributeKeys,
    });
  }

  resumeSession(id: number): Observable<AdminSession> {
    return this.transitionSession(id, 'resume');
  }

  pauseAllSessions(gameId: number): Observable<{ paused_sessions: number[] }> {
    return this.http.post<{ paused_sessions: number[] }>(
      `/api/staff/games/${gameId}/pause_all/`,
      {},
    );
  }

  sessionPauseHistory(id: number): Observable<PauseHistory> {
    return this.http.get<PauseHistory>(`/api/staff/sessions/${id}/pause_history/`);
  }

  sessionFailCounters(id: number): Observable<FailCounterInfo[]> {
    return this.http.get<FailCounterInfo[]>(
      `/api/staff/sessions/${id}/fail_counters/`,
    );
  }

  // ---- Team rules: start-gate readiness -------------------------------------

  sessionStartBlockers(id: number): Observable<StartReadiness> {
    return this.http.get<StartReadiness>(
      `/api/staff/sessions/${id}/start_blockers/`,
    );
  }

  // ---- presence-rules: reusable presence requirements -----------------------

  listPresenceRequirements(): Observable<AdminPresenceRequirement[]> {
    return this.http.get<AdminPresenceRequirement[]>('/api/staff/presence-requirements/');
  }

  createPresenceRequirement(
    payload: AdminPresenceRequirementPayload,
  ): Observable<AdminPresenceRequirement> {
    return this.http.post<AdminPresenceRequirement>(
      '/api/staff/presence-requirements/',
      payload,
    );
  }

  updatePresenceRequirement(
    id: number,
    payload: AdminPresenceRequirementPayload,
  ): Observable<AdminPresenceRequirement> {
    return this.http.patch<AdminPresenceRequirement>(
      `/api/staff/presence-requirements/${id}/`,
      payload,
    );
  }

  deletePresenceRequirement(id: number): Observable<void> {
    return this.http.delete<void>(`/api/staff/presence-requirements/${id}/`);
  }

  // ---- tower-visibility: discovery matrix + staff reveal --------------------

  sessionDiscoveryMatrix(id: number): Observable<DiscoveryMatrix> {
    return this.http.get<DiscoveryMatrix>(
      `/api/staff/sessions/${id}/discovery-matrix/`,
    );
  }

  revealTowerToTeam(teamId: number, towerId: number): Observable<DiscoveryMatrixCell> {
    return this.http.post<DiscoveryMatrixCell>('/api/staff/discovery/reveal/', {
      team: teamId,
      tower: towerId,
    });
  }

  // ---- live-location: after-game replay feed --------------------------------

  sessionLocationHistory(
    id: number,
    filters: { user?: number; team?: number; from?: string; to?: string } = {},
  ): Observable<LocationHistory> {
    const parts: string[] = [];
    if (filters.user) parts.push(`user=${filters.user}`);
    if (filters.team) parts.push(`team=${filters.team}`);
    if (filters.from) parts.push(`from=${encodeURIComponent(filters.from)}`);
    if (filters.to) parts.push(`to=${encodeURIComponent(filters.to)}`);
    const query = parts.length ? `?${parts.join('&')}` : '';
    return this.http.get<LocationHistory>(
      `/api/staff/sessions/${id}/location-history/${query}`,
    );
  }


  // ---- nfc-native-and-secure-links: tag provisioning + scan audit ----------

  nfcTags(params?: { tower?: number; mode?: string }): Observable<NfcTagInfo[]> {
    const parts: string[] = [];
    if (params?.tower) parts.push(`tower=${params.tower}`);
    if (params?.mode) parts.push(`mode=${params.mode}`);
    const query = parts.length ? `?${parts.join('&')}` : '';
    return this.http.get<NfcTagInfo[]>(`/api/staff/nfc-tags/${query}`);
  }

  createNfcTag(payload: Partial<NfcTagInfo>): Observable<NfcTagInfo> {
    return this.http.post<NfcTagInfo>('/api/staff/nfc-tags/', payload);
  }

  updateNfcTag(id: number, payload: Partial<NfcTagInfo>): Observable<NfcTagInfo> {
    return this.http.patch<NfcTagInfo>(`/api/staff/nfc-tags/${id}/`, payload);
  }

  deleteNfcTag(id: number): Observable<void> {
    return this.http.delete<void>(`/api/staff/nfc-tags/${id}/`);
  }

  nfcTagNdef(id: number): Observable<NfcNdefPayload> {
    return this.http.get<NfcNdefPayload>(`/api/staff/nfc-tags/${id}/ndef/`);
  }

  nfcScanAudit(params?: { tag?: number }): Observable<TagScanInfo[]> {
    const query = params?.tag ? `?tag=${params.tag}` : '';
    return this.http.get<TagScanInfo[]>(`/api/staff/nfc-tags/scan-audit/${query}`);
  }

  // ---- Score multipliers (score-multipliers) --------------------------------

  listGameMultipliers(gameId: number): Observable<AdminScoreMultiplier[]> {
    return this.http.get<AdminScoreMultiplier[]>(
      `/api/staff/games/${gameId}/score-multipliers/`,
    );
  }

  createGameMultiplier(
    gameId: number,
    payload: AdminScoreMultiplierPayload,
  ): Observable<AdminScoreMultiplier> {
    return this.http.post<AdminScoreMultiplier>(
      `/api/staff/games/${gameId}/score-multipliers/`,
      payload,
    );
  }

  updateGameMultiplier(
    gameId: number,
    id: number,
    patch: Partial<AdminScoreMultiplierPayload>,
  ): Observable<AdminScoreMultiplier> {
    return this.http.patch<AdminScoreMultiplier>(
      `/api/staff/games/${gameId}/score-multipliers/${id}/`,
      patch,
    );
  }

  deleteGameMultiplier(gameId: number, id: number): Observable<void> {
    return this.http.delete<void>(
      `/api/staff/games/${gameId}/score-multipliers/${id}/`,
    );
  }

  /** Union of Session-owned and Game-owned rows — the whole picture. */
  listSessionMultipliers(sessionId: number): Observable<AdminScoreMultiplier[]> {
    return this.http.get<AdminScoreMultiplier[]>(
      `/api/staff/sessions/${sessionId}/score-multipliers/`,
    );
  }

  /** Live drop: always creates a Session-owned row (MANUAL / RANDOM_BONUS). */
  createSessionMultiplier(
    sessionId: number,
    payload: AdminScoreMultiplierPayload,
  ): Observable<AdminScoreMultiplier> {
    return this.http.post<AdminScoreMultiplier>(
      `/api/staff/sessions/${sessionId}/score-multipliers/`,
      payload,
    );
  }

  /** Live MANUAL switch: flips is_active from this instant forward. */
  setMultiplierActive(
    sessionId: number,
    id: number,
    active: boolean,
  ): Observable<AdminScoreMultiplier> {
    const action = active ? 'activate' : 'deactivate';
    return this.http.post<AdminScoreMultiplier>(
      `/api/staff/sessions/${sessionId}/score-multipliers/${id}/${action}/`,
      {},
    );
  }

  // ---- mcp-authoring: AI authoring review inbox + credentials ----------

  authoringProposals(status?: string): Observable<AuthoringProposal[]> {
    const query = status ? `?status=${status}` : '';
    return this.http.get<AuthoringProposal[]>(`/api/staff/authoring/proposals/${query}`);
  }

  authoringProposal(id: number): Observable<AuthoringProposalDetail> {
    return this.http.get<AuthoringProposalDetail>(`/api/staff/authoring/proposals/${id}/`);
  }

  authoringDecision(
    id: number,
    action: 'approve' | 'reject' | 'apply' | 'withdraw',
  ): Observable<AuthoringProposalDetail> {
    return this.http.post<AuthoringProposalDetail>(
      `/api/staff/authoring/proposals/${id}/${action}/`,
      {},
    );
  }

  authoringOperationDecision(
    proposalId: number,
    opId: number,
    action: 'approve' | 'reject',
  ): Observable<AuthoringProposalDetail> {
    return this.http.post<AuthoringProposalDetail>(
      `/api/staff/authoring/proposals/${proposalId}/operations/${opId}/${action}/`,
      {},
    );
  }

  authoringAudit(): Observable<AuthoringAuditEvent[]> {
    return this.http.get<AuthoringAuditEvent[]>('/api/staff/authoring/audit/');
  }

  mcpCredentials(): Observable<McpCredential[]> {
    return this.http.get<McpCredential[]>('/api/staff/authoring/credentials/');
  }

  issueMcpCredential(label: string): Observable<McpCredential & { token: string }> {
    return this.http.post<McpCredential & { token: string }>(
      '/api/staff/authoring/credentials/',
      { label },
    );
  }

  revokeMcpCredential(id: number): Observable<McpCredential> {
    return this.http.post<McpCredential>(
      `/api/staff/authoring/credentials/${id}/revoke/`,
      {},
    );
  }

  // --- simulator ---------------------------------------------------------
  // game-simulator-backend: staff-only run driver under /api/staff/simulator/.

  createSimulationRun(payload: CreateSimulationRunPayload): Observable<SimulationRun> {
    return this.http.post<SimulationRun>('/api/staff/simulator/runs/', payload);
  }

  listSimulationRuns(): Observable<SimulationRun[]> {
    return this.http.get<SimulationRun[]>('/api/staff/simulator/runs/');
  }

  /** Run row + a live `state` snapshot (null before setup finishes). */
  getSimulationRun(id: number): Observable<SimulationRunDetail> {
    return this.http.get<SimulationRunDetail>(`/api/staff/simulator/runs/${id}/`);
  }

  stepSimulation(id: number, ticks = 1): Observable<SimulationState> {
    return this.http.post<SimulationState>(`/api/staff/simulator/runs/${id}/step/`, { ticks });
  }

  playSimulation(id: number, ticks: number): Observable<SimulationState> {
    return this.http.post<SimulationState>(`/api/staff/simulator/runs/${id}/play/`, { ticks });
  }

  pauseSimulation(id: number): Observable<SimulationRun> {
    return this.http.post<SimulationRun>(`/api/staff/simulator/runs/${id}/pause/`, {});
  }

  stopSimulation(id: number): Observable<SimulationRun> {
    return this.http.post<SimulationRun>(`/api/staff/simulator/runs/${id}/stop/`, {});
  }

  /** The run's full append-only SimulationEvent tape, tick-ordered. */
  simulationTimeline(id: number): Observable<SimulationEvent[]> {
    return this.http.get<SimulationEvent[]>(`/api/staff/simulator/runs/${id}/timeline/`);
  }

  /** Full teardown: deletes the sim-created Game/Session + fake users. */
  deleteSimulationRun(id: number): Observable<void> {
    return this.http.delete<void>(`/api/staff/simulator/runs/${id}/`);
  }
}

// ---- tower-visibility: discovery matrix ------------------------------------

export interface DiscoveryMatrixCell {
  team_id?: number;
  tower_id: number;
  method: string;
  discovered_at: string;
  discovered_by?: string | null;
}

export interface DiscoveryMatrix {
  session: number;
  default_discoverability: Discoverability;
  teams: { id: number; name: string; color: string }[];
  /** Only towers whose effective discoverability is not VISIBLE. */
  towers: { id: number; name: string; discoverability: Discoverability }[];
  discoveries: DiscoveryMatrixCell[];
}

// ---- live-location ----------------------------------------------------------

export interface LocationHistoryPing {
  user_id: number;
  username: string;
  team_id: number | null;
  team_name: string | null;
  team_color: string | null;
  lat: number;
  lng: number;
  accuracy: number | null;
  recorded_at: string;
  received_at: string;
}

export interface LocationHistory {
  session: number;
  retention_days: number;
  pings: LocationHistoryPing[];
}

// ---- nfc-native-and-secure-links --------------------------------------------

export interface NfcTagInfo {
  id: number;
  token: string;
  mode: 'LEGACY_URL' | 'SECURE_TOKEN';
  tower: number | null;
  challenge: number | null;
  label: string;
  hidden_hint: string;
  is_active: boolean;
  expected_counter: number | null;
  last_counter: number | null;
  app_link: string;
  target_summary: { kind: string; id: number; name: string } | null;
  scan_count: number;
  created_at: string;
}

export interface NfcNdefPayload {
  mode: string;
  token: string;
  records: { type: string; uri?: string; package?: string }[];
}

export interface TagScanInfo {
  id: number;
  tag: number;
  tag_label: string;
  player_username: string | null;
  session: number | null;
  timestamp: string;
  outcome: string;
  lat: number | null;
  lng: number | null;
  accuracy: number | null;
  counter: number | null;
}


/** A ScoreMultiplier row (score-multipliers capability). Durations are
 *  Django strings ("HH:MM:SS" or "D HH:MM:SS"); datetimes are ISO. */
export interface AdminScoreMultiplier {
  id: number;
  game: number | null;
  session: number | null;
  scope: ScoreMultiplierScope;
  tower: number | null;
  tower_name: string | null;
  zone: number | null;
  zone_name: string | null;
  multiplier_type: ScoreMultiplierType;
  factor: number;
  is_active: boolean;
  window_start_offset: string | null;
  window_end_offset: string | null;
  starts_at: string | null;
  ends_at: string | null;
  label: string;
  created_by: number | null;
  created_by_username: string | null;
  created_at: string;
}

/** Ownership (game/session) comes from the URL, never the body. */
export interface AdminScoreMultiplierPayload {
  scope: ScoreMultiplierScope;
  multiplier_type: ScoreMultiplierType;
  factor: number;
  tower?: number | null;
  zone?: number | null;
  is_active?: boolean;
  window_start_offset?: string | null;
  window_end_offset?: string | null;
  starts_at?: string | null;
  ends_at?: string | null;
  label?: string;
}

// ---- mcp-authoring: staged proposals, operations, audit, credentials -------

export type AuthoringProposalStatus =
  | 'DRAFT' | 'PENDING' | 'APPROVED' | 'APPLIED'
  | 'PARTIALLY_APPLIED' | 'REJECTED' | 'WITHDRAWN' | 'FAILED';

export type ProposedOperationStatus =
  | 'PENDING' | 'APPROVED' | 'REJECTED' | 'APPLIED' | 'FAILED';

export interface ProposedOperation {
  id: number;
  entity_type: string;
  action: string;
  temp_ref: string;
  target_ref: string;
  payload: Record<string, unknown>;
  rationale: string;
  status: ProposedOperationStatus;
  order: number;
  applied_object_type: string;
  applied_object_id: number | null;
  error: string;
  current: Record<string, string> | null;
}

export interface AuthoringProposal {
  id: number;
  status: AuthoringProposalStatus;
  atomic: boolean;
  summary: string;
  created_by: number;
  created_by_username: string | null;
  client_name: string;
  llm_model: string;
  created_at: string;
  updated_at: string;
  decided_by: number | null;
  decided_at: string | null;
  operation_count: number;
}

export interface AuthoringProposalDetail extends AuthoringProposal {
  operations: ProposedOperation[];
}

export interface AuthoringAuditEvent {
  id: number;
  event_type: string;
  tool_name: string;
  client_name: string;
  llm_model: string;
  created_by: number;
  created_by_username: string | null;
  session: number | null;
  proposal: number | null;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
  created_at: string;
}

export interface McpCredential {
  id: number;
  label: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

// --- simulator ---------------------------------------------------------
// game-simulator-backend: a SimulationRun spins up a REAL Game/Session/
// roster and drives it through the same domain code the live API uses.
// Every action is recorded to an append-only SimulationEvent tape for
// replay/scrub (see simulator/driver.py + simulator/models.py).

export type SimulationRunStatus = 'DRAFT' | 'RUNNING' | 'PAUSED' | 'FINISHED';

/** A SimulationRun row: its config + pointers to the real Game/Session it drives. */
export interface SimulationRun {
  id: number;
  name: string;
  created_by: number | null;
  game: number | null;
  session: number | null;
  status: SimulationRunStatus;
  seed: number;
  config: Record<string, unknown>;
  tick_count: number;
  created_at: string;
}

/**
 * POST body for `createSimulationRun` — creates AND immediately sets up
 * the run (real Game/Session/roster/teams). `template_game_id` clones an
 * existing Game as the sim's template; omit it (optionally passing
 * `game_name`) to spin up a fresh throwaway Game instead.
 */
export interface CreateSimulationRunPayload {
  name?: string;
  seed?: number;
  template_game_id?: number | null;
  /** Only used when no `template_game_id` is given. */
  game_name?: string;
  n_players?: number;
  n_teams?: number;
  /** Free-text label only; `dementors_enabled` is what actually switches behavior. */
  mode?: string;
  dementors_enabled?: boolean;
  tick_seconds?: number;
  capture_probability?: number;
  center_lat?: number;
  center_lng?: number;
  radius_m?: number;
}

/** One fake roster member's live position + (dementors-mode) role/energy. */
export interface SimPlayer {
  id: number;
  profile_id: number;
  username: string;
  team_id: number | null;
  team_name: string | null;
  lat: number;
  lng: number;
  /** '' outside dementors mode; 'WIZARD' | 'DEMENTOR' when it's on. */
  role: string;
  /** null outside dementors mode. */
  energy: number | null;
  alive: boolean;
}

export interface SimScoreEntry {
  team_id: number;
  name: string;
  score: number;
}

export interface SimTowerState {
  id: number;
  name: string;
  owner_team_id: number | null;
  owner_team_name: string | null;
}

/** Live snapshot returned by step/play, and nested under `state` on the detail GET. */
export interface SimulationState {
  run_id: number;
  status: SimulationRunStatus;
  tick_count: number;
  session_state: string | null;
  players: SimPlayer[];
  scoreboard: SimScoreEntry[];
  towers: SimTowerState[];
}

/** GET .../runs/{id}/ response: the run row plus a live `state` snapshot. */
export interface SimulationRunDetail extends SimulationRun {
  /** null when the run somehow has no session yet (setup always sets one). */
  state: SimulationState | null;
}

export type SimulationEventAction =
  | 'SPAWN' | 'MOVE' | 'PROXIMITY' | 'CAPTURE' | 'TRANSITION' | 'TICK';

/**
 * One entry in a run's append-only replay tape. MOVE payload carries
 * `{from:[lat,lng], to:[lat,lng]}`; CAPTURE payload carries
 * `{tower_id, team_id}`; PROXIMITY outcome carries `roles`/`energy` maps
 * keyed by (stringified) `profile_id`.
 */
export interface SimulationEvent {
  id: number;
  tick: number;
  ts: string;
  actor: number | null;
  actor_username: string | null;
  action: SimulationEventAction;
  payload: Record<string, unknown>;
  outcome: Record<string, unknown>;
}
