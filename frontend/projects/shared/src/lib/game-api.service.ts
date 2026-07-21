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

/** challenge-type-system: the pluggable challenge type discriminator. */
export type ChallengeType = 'TEXT' | 'PHOTO' | 'NFC_QR' | 'RFID';
export type ReviewMode = 'AUTO' | 'MANUAL';

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
  pending_submission: boolean;
  cooloff_until: string | null;
  proximity_meters: number;
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

export interface NfcCaptureResponse {
  outcome: string;
  detail?: string;
  submission_id?: number;
  tower?: { id: number; name: string };
  challenge?: number | null;
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
