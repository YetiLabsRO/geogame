import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface TowerState {
  id: number;
  name: string;
  category: number;
  location: { type: 'Point'; coordinates: [number, number] };
  has_initial_bonus: boolean;
  ownership: { team_id: number; team_name: string; team_color: string } | null;
  next_challenge: { id: number; text: string; difficulty: number; tower: number | null } | null;
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

export interface CurrentGame {
  id: number;
  name: string;
  slug: string;
  is_active: boolean;
  start_time: string;
  end_time: string;
  base_point: { type: 'Point'; coordinates: [number, number] } | null;
  base_zoom_level: number;
  proximity_meters: number;
  cooloff_minutes: number;
  initial_bonus_default: number;
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
  code: string;
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

  currentGame(): Observable<CurrentGame> {
    return this.http.get<CurrentGame>('/api/current-game/');
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
}

export interface TeamSummary {
  id: number;
  name: string;
  code: string;
  group: number | null;
  group_name: string | null;
  group_slug: string | null;
  current_score: number;
  color: string;
}
