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
    role_requirement: RoleRequirementInfo | null;
  } | null;
  /** null = no presence requirement (presence-rules capability). */
  presence: PresenceStatus | null;
  pending_submission: boolean;
  cooloff_until: string | null;
  proximity_meters: number;
}

export interface ChallengeSubmitPayload {
  tower: number;
  challenge: number;
  photo?: string;
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
  zone: string | null;
  category: number;
  is_active: boolean;
  has_initial_bonus: boolean;
  ownership: TowerOwnership | Record<string, never>;
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

  towerState(id: number): Observable<TowerState> {
    return this.http.get<TowerState>(`/api/towers/${id}/state/`);
  }

  submitChallenge(payload: ChallengeSubmitPayload): Observable<ChallengeSubmitResponse> {
    return this.http.post<ChallengeSubmitResponse>(
      '/api/team_tower_challenges/',
      payload,
    );
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
