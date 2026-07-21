import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface RoleRequirementInfo {
  mode: 'ALL' | 'ANY';
  required_roles: { slug: string; name: string }[];
  require_holders_present: boolean;
  team_satisfies: boolean;
  missing_roles: string[];
}

/** Player-facing presence status for a tower (presence-rules capability). */
export interface PresenceStatus {
  required_members: number;
  present_members: number;
  present_member_ids: number[];
  method: 'GEOFENCE' | 'PHOTO' | 'GEOFENCE_OR_PHOTO';
  photo_fallback_offered: boolean;
  geofence_radius_meters: number;
  window_seconds: number;
}

/** challenge-type-system: the pluggable challenge type discriminator. */
export type ChallengeType = 'TEXT' | 'PHOTO' | 'NFC_QR' | 'RFID';
export type ReviewMode = 'AUTO' | 'MANUAL';

/** Tower contention modes (tower-locking capability). */
export type TowerLockMode = 'FREE_FOR_ALL' | 'LOCK_ON_INITIATE';

/** Player-facing view of a tower's active lock (null when free). */
export interface TowerLockInfo {
  held_by_us: boolean;
  team_id: number;
  team_name: string;
  team_color: string;
  started_at: string;
  expires_at: string;
  remaining_seconds: number;
}
export interface TowerState {
  id: number;
  name: string;
  category: number;
  location: { type: 'Point'; coordinates: [number, number] };
  has_initial_bonus: boolean;
  ownership: { team_id: number; team_name: string; team_color: string } | null;
  next_challenge: {
    id: number;
    text: string;
    difficulty: number;
    tower: number | null;
    /** challenge-type-system: drives the per-type submission UI. */
    type: ChallengeType | string;
    effective_review_mode: ReviewMode | null;
    /** Payload keys a submission must supply ('photo', 'submitted_code'). */
    required_payload: string[];
    role_requirement: RoleRequirementInfo | null;
  } | null;
  /** null = no presence requirement (presence-rules capability). */
  presence: PresenceStatus | null;
  pending_submission: boolean;
  cooloff_until: string | null;
  proximity_meters: number;
  tower_lock_mode: TowerLockMode;
  lock: TowerLockInfo | null;
  /** tower-visibility (challenge axis): HIDDEN_UNTIL_ARRIVAL withholds
   *  the challenge until the reported position is inside the
   *  activation area — `challenge_hidden` says whether it currently is. */
  challenge_visibility: 'HIDDEN_UNTIL_ARRIVAL' | 'VISIBLE_ANYWHERE';
  challenge_hidden: boolean;
}

export interface TowerInitiateResponse {
  tower_lock_mode: TowerLockMode;
  locked: boolean;
  lock: TowerLockInfo | null;
}

export interface ChallengeSubmitPayload {
  tower: number;
  challenge: number;
  photo?: string;
  /** Scanned/pasted venue or tag code for scan-type challenges. */
  submitted_code?: string;
  lat: number;
  lng: number;
}

export interface ChallengeSubmitResponse {
  id: number;
  tower: number;
  challenge: number;
  outcome: number;
  timestamp_submitted: string;
}

export interface GameConfig {
  id: number;
  name: string;
  slug: string;
  is_active: boolean;
  base_point: { type: 'Point'; coordinates: [number, number] } | null;
  base_zoom_level: number;
  proximity_meters: number;
  cooloff_minutes: number;
  initial_bonus_default: number;
  allow_player_team_creation: boolean;
  team_join_confirmation: string;
  team_groups: { id: number; name: string; slug: string }[];
}

/** Effective live-location config for a Session (live-location capability). */
export interface LocationConfig {
  tracking_enabled: boolean;
  /** Game-level pacing; the player app streams at this cadence and never
   *  exposes a control to change it. */
  ping_interval_seconds: number;
  visibility: 'NONE' | 'OWN_TEAM' | 'EVERYONE';
  consent_text: string;
}

/** Effective tower-visibility config (tower-visibility capability). */
export interface VisibilityConfig {
  default_discoverability: 'HIDDEN' | 'VISIBLE' | 'FOG_REVEAL';
  /** Any FOG_REVEAL tower reachable in this session → render the fog overlay. */
  uses_fog: boolean;
  /** Any non-VISIBLE tower → report positions for discovery. */
  uses_discovery: boolean;
  reveal_other_teams_ownership: boolean;
}

export interface CurrentSession {
  id: number;
  slug: string;
  name: string;
  /** Lifecycle state (session-lifecycle capability). */
  state: string;
  is_active: boolean;
  start_time: string;
  end_time: string;
  game: GameConfig;
  allow_player_team_creation: boolean;
  location: LocationConfig;
  /** Effective realtime/push toggles (realtime-and-notifications). */
  realtime_enabled: boolean;
  push_notifications_enabled: boolean;
  /** Effective dementors-mode opt-in (mode-dementors-ble). */
  dementors_enabled: boolean;
  visibility: VisibilityConfig;
}

export interface ZoneFeature {
  name: string;
  color: string;
  scoring_type: number;
  shape: { type: 'Polygon'; coordinates: number[][][] };
  team_color: string;
}

export interface TowerOwnership {
  name: string;
  color: string;
  current_score: number;
}

export interface TowerFeature {
  id: number;
  name: string;
  location: { type: 'Point'; coordinates: [number, number] };
  /** Many-to-many zone membership (ids) — tower-zone-topology. */
  zones: number[];
  category: number;
  is_active: boolean;
  has_initial_bonus: boolean;
  /** Per-tower capture radius; null inherits the Game default. */
  proximity_meters: number | null;
  ownership: TowerOwnership | Record<string, never>;
}

export interface NfcCaptureResponse {
  outcome: string;
  detail?: string;
  submission_id?: number;
  tower?: { id: number; name: string };
  challenge?: number | null;
}

/** mode-trail-discovery: one trail step in the player state payload. */
export interface TrailStepInfo {
  id: number;
  order: number;
  is_start: boolean;
  is_finish: boolean;
  has_gate: boolean;
  gate_challenge: number | null;
  tower: { id: number; name: string; location: { type: 'Point'; coordinates: [number, number] } };
  clue: string;
  state: 'REVEALED' | 'ARRIVED' | 'UNLOCKED' | null;
  revealed_at?: string | null;
  arrived_at?: string | null;
  unlocked_at?: string | null;
}

export interface TrailState {
  trail: { structure: string; starting_knowledge: string; participation: string };
  route: { start_step: number; party: string; sequence: number[] | null } | null;
  steps: TrailStepInfo[];
  next_steps: TrailStepInfo[];
  progress?: { unlocked: number; total: number };
  finished: boolean;
  finished_at: string | null;
  start_hint?: string;
}

export interface TrailLeaderboardRow {
  party: string;
  team_id: number | null;
  team_color: string | null;
  steps_unlocked: number;
  finished: boolean;
  finished_at: string | null;
  rank: number;
}

@Injectable({ providedIn: 'root' })
export class GameApiService {
  private readonly http = inject(HttpClient);

  currentSession(): Observable<CurrentSession> {
    return this.http.get<CurrentSession>('/api/current-session/');
  }

  setCurrentSession(sessionId: number): Observable<CurrentSession> {
    return this.http.post<CurrentSession>('/api/current-session/', {
      session_id: sessionId,
    });
  }

  mySessions(): Observable<CurrentSession[]> {
    return this.http.get<CurrentSession[]>('/api/my-sessions/');
  }

  sessionScoreboard(id: number): Observable<SessionScoreboard> {
    return this.http.get<SessionScoreboard>(
      `/api/sessions/${id}/scoreboard/`,
    );
  }

  sessionTimeline(id: number): Observable<SessionTimeline> {
    return this.http.get<SessionTimeline>(`/api/sessions/${id}/timeline/`);
  }

  /** Multipliers in effect right now — map/scoreboard banner source. */
  sessionActiveMultipliers(id: number): Observable<ActiveMultiplier[]> {
    return this.http.get<ActiveMultiplier[]>(
      `/api/sessions/${id}/score-multipliers/active/`,
    );
  }

  zones(params?: { group?: number; groupSlug?: string }): Observable<ZoneFeature[]> {
    const parts: string[] = [];
    if (params?.group) parts.push(`group=${params.group}`);
    if (params?.groupSlug) parts.push(`group_slug=${encodeURIComponent(params.groupSlug)}`);
    const query = parts.length ? `?${parts.join('&')}` : '';
    return this.http.get<ZoneFeature[]>(`/api/zones/${query}`);
  }

  towers(): Observable<TowerFeature[]> {
    return this.http.get<TowerFeature[]>('/api/towers/');
  }

  towerState(id: number, position?: { lat: number; lng: number }): Observable<TowerState> {
    const query = position ? `?lat=${position.lat}&lng=${position.lng}` : '';
    return this.http.get<TowerState>(`/api/towers/${id}/state/${query}`);
  }

  /**
   * INITIATE lifecycle phase (tower-locking): under LOCK_ON_INITIATE this
   * acquires the tower lock for the caller's team group (409 when another
   * team in the group holds it); under FREE_FOR_ALL it is a no-op ack.
   */
  initiateTower(id: number): Observable<TowerInitiateResponse> {
    return this.http.post<TowerInitiateResponse>(`/api/towers/${id}/initiate/`, {});
  }

  /** Voluntarily give up our team's active lock on this tower (CANCELLED). */
  releaseTowerLock(id: number): Observable<{ released: boolean }> {
    return this.http.post<{ released: boolean }>(
      `/api/towers/${id}/release_lock/`,
      {},
    );
  }

  submitChallenge(payload: ChallengeSubmitPayload): Observable<ChallengeSubmitResponse> {
    return this.http.post<ChallengeSubmitResponse>(
      '/api/team_tower_challenges/',
      payload,
    );
  }

  /** mode-trail-discovery: the party's trail state. 404 on DOMINATION sessions. */
  trailState(): Observable<TrailState> {
    return this.http.get<TrailState>('/api/trail/state/');
  }

  trailNext(): Observable<{ next_steps: TrailStepInfo[]; is_branch: boolean }> {
    return this.http.get<{ next_steps: TrailStepInfo[]; is_branch: boolean }>('/api/trail/next/');
  }

  trailLeaderboard(): Observable<{ ranking: TrailLeaderboardRow[] }> {
    return this.http.get<{ ranking: TrailLeaderboardRow[] }>('/api/trail/leaderboard/');
  }

  teams(): Observable<TeamSummary[]> {
    return this.http.get<TeamSummary[]>('/api/teams/');
  }

  myTeam(): Observable<MyTeam> {
    return this.http.get<MyTeam>('/api/my-team/');
  }

  // ---- live-location --------------------------------------------------------

  locationConsent(): Observable<LocationConsentStatus> {
    return this.http.get<LocationConsentStatus>('/api/location/consent/');
  }

  grantLocationConsent(): Observable<LocationConsentStatus> {
    return this.http.post<LocationConsentStatus>('/api/location/consent/', {});
  }

  withdrawLocationConsent(): Observable<void> {
    return this.http.delete<void>('/api/location/consent/');
  }

  sendLocationPing(payload: LocationPingPayload): Observable<LocationPingResponse> {
    return this.http.post<LocationPingResponse>('/api/location/ping/', payload);
  }

  liveLocations(): Observable<LiveLocations> {
    return this.http.get<LiveLocations>('/api/location/live/');
  }

  /** nfc-native-and-secure-links: the single capture call every scan
   *  transport (Web NFC, native bridge, QR camera, manual entry)
   *  resolves to. The X-Cercetador-App header marks the app origin for
   *  sessions with nfc_require_app enabled. */
  nfcCapture(payload: {
    token: string;
    lat: number;
    lng: number;
    accuracy?: number;
    counter?: number;
  }): Observable<NfcCaptureResponse> {
    return this.http.post<NfcCaptureResponse>('/api/nfc/capture/', payload, {
      headers: { 'X-Cercetador-App': '1' },
    });
  }

  // ---- discovery (tower-visibility capability) ------------------------------

  /** Self-contained position fallback: report a position, get new reveals. */
  discoveryPing(payload: { lat: number; lng: number }): Observable<DiscoveryPingResponse> {
    return this.http.post<DiscoveryPingResponse>('/api/discovery/ping/', payload);
  }

  /** The caller team's discovered towers for the current Session. */
  discoveredTowers(): Observable<DiscoveredTowers> {
    return this.http.get<DiscoveredTowers>('/api/discovery/towers/');
  }
}

// ---- discovery (tower-visibility capability) -------------------------------

export interface RevealedTower {
  tower_id: number;
  tower_name: string;
  location: { type: 'Point'; coordinates: [number, number] };
  method: 'PROXIMITY' | 'ZONE_ENTRY' | 'ZONE_COVERAGE' | 'ALWAYS_VISIBLE' | 'STAFF';
  discovered_at: string;
}

export interface DiscoveryPingResponse {
  session: number;
  team: number;
  newly_revealed: RevealedTower[];
}

export interface DiscoveredTowers {
  session: number;
  team: number;
  towers: RevealedTower[];
}

// ---- live-location ---------------------------------------------------------

export interface LocationConsentStatus {
  session: number;
  tracking_enabled?: boolean;
  consent_required?: boolean;
  has_consent: boolean;
  agreed_at: string | null;
  consent_text: string;
  ping_interval_seconds?: number;
}

export interface LocationPingPayload {
  lat: number;
  lng: number;
  accuracy?: number;
  recorded_at?: string;
}

export interface LocationPingResponse {
  id: number;
  recorded_at: string;
  received_at: string;
  ping_interval_seconds: number;
  /** Towers this position newly revealed (discovery-tracking). */
  newly_revealed: { tower_id: number; tower_name: string; method: string }[];
}

export interface LivePlayer {
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

export interface LiveLocations {
  session: number;
  tracking_enabled: boolean;
  visibility: 'NONE' | 'OWN_TEAM' | 'EVERYONE';
  /** presence-rules refinement the plotting consumes (SELECT_COUNT = nearest N). */
  teammate_visibility: {
    mode: 'OWN_TEAM' | 'EVERYONE' | 'SELECT_COUNT';
    count: number;
  };
  players: LivePlayer[];
}

// ---- team-roles ------------------------------------------------------------

export interface MemberRole {
  id: number;
  slug: string;
  name: string;
  builtin_power?: string;
}

export interface MyTeamMember {
  user_id: number;
  username: string;
  first_name: string;
  last_name: string;
  joined_at: string;
  roles: MemberRole[];
}

export interface MyTeam {
  id: number;
  name: string;
  color: string;
  score: number;
  current_score: number;
  members: MyTeamMember[];
  can_invite: boolean;
  active_member_count: number;
  is_ready: boolean;
  members_needed: number;
}

export interface SessionScoreboardEntry {
  team_id: number;
  team_name: string;
  team_color: string;
  group_name: string | null;
  group_slug: string | null;
  locked_score: number;
  floating_score: number;
  current_score: number;
}

export interface SessionScoreboard {
  session: CurrentSession;
  entries: SessionScoreboardEntry[];
  /** Multipliers in effect right now (score-multipliers capability). */
  active_multipliers: ActiveMultiplier[];
}

// ---- score-multipliers -----------------------------------------------------

export type ScoreMultiplierScope = 'TOWER' | 'ZONE' | 'GLOBAL';
export type ScoreMultiplierType = 'MANUAL' | 'SCHEDULED' | 'RANDOM_BONUS';

/** One multiplier in effect right now (read-only banner payload). */
export interface ActiveMultiplier {
  id: number;
  factor: number;
  scope: ScoreMultiplierScope;
  multiplier_type: ScoreMultiplierType;
  tower_id: number | null;
  tower_name: string | null;
  zone_id: number | null;
  zone_name: string | null;
  label: string;
  active_until: string | null;
  owned_by: 'session' | 'game';
}

export interface SessionTimelineEvent {
  id: number;
  team_id: number;
  team_name: string;
  team_color: string;
  tower_id: number;
  tower_name: string;
  timestamp_start: string;
  timestamp_end: string | null;
}

export interface SessionTimeline {
  session: CurrentSession;
  events: SessionTimelineEvent[];
}

export interface TeamSummaryMember {
  user_id: number;
  username: string;
  roles: { id: number; slug: string; name: string }[];
}

export interface TeamSummary {
  id: number;
  name: string;
  group: number | null;
  group_name: string | null;
  group_slug: string | null;
  current_score: number;
  color: string;
  members: TeamSummaryMember[];
  active_member_count: number;
  is_ready: boolean;
  members_needed: number;
}
