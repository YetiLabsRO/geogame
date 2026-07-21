import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

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
  submitted_by: number | null;
  submitted_by_username: string | null;
  photo_url: string | null;
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

/** A Collection or Game referencing a repository asset (usage reporting). */
export interface UsageRef {
  id: number;
  name: string;
}

export interface AdminTower {
  id: number;
  name: string;
  zone: number | null;
  category: number;
  is_active: boolean;
  initial_bonus: number;
  rfid_code: string | null;
  collections: UsageRef[];
  games: UsageRef[];
}

export interface AdminZone {
  id: number;
  name: string;
  color: string;
  scoring_type: number;
  collections: UsageRef[];
  games: UsageRef[];
}

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
    PresenceRulesConfig {
  id: number;
  slug: string;
  name: string;
  base_point: { type: 'Point'; coordinates: [number, number] } | null;
  base_zoom_level: number;
  is_active: boolean;
  proximity_meters: number;
  cooloff_minutes: number;
  initial_bonus_default: number;
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
    PresenceRulesOverrides {
  id: number;
  /** Per-session override; null inherits the Game default. */
  allow_player_team_creation: boolean | null;
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

  // ---- Admin CRUD ---------------------------------------------------------

  listTowers(collectionId?: number): Observable<AdminTower[]> {
    const query = collectionId ? `?collection=${collectionId}` : '';
    return this.http.get<AdminTower[]>(`/api/staff/towers/${query}`);
  }

  updateTower(id: number, patch: Partial<AdminTower>): Observable<AdminTower> {
    return this.http.patch<AdminTower>(`/api/staff/towers/${id}/`, patch);
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

  updateZone(id: number, patch: Partial<AdminZone>): Observable<AdminZone> {
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
