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
}

export interface AdminTower {
  id: number;
  name: string;
  game: number;
  zone: number | null;
  category: number;
  is_active: boolean;
  initial_bonus: number;
  rfid_code: string | null;
}

export interface AdminZone {
  id: number;
  name: string;
  game: number;
  color: string;
  scoring_type: number;
}

export interface AdminTeam {
  id: number;
  name: string;
  game: number;
  group: number | null;
  color: string;
  description: string | null;
}

export interface AdminTeamGroup {
  id: number;
  name: string;
  game: number;
  slug: string;
}

export interface AdminChallenge {
  id: number;
  game: number | null;
  text: string;
  tower: number | null;
  difficulty: number;
}

export interface AdminGame {
  id: number;
  slug: string;
  name: string;
  base_point: { type: 'Point'; coordinates: [number, number] } | null;
  base_zoom_level: number;
  is_active: boolean;
  proximity_meters: number;
  cooloff_minutes: number;
  initial_bonus_default: number;
  created_at: string | null;
}

export type AdminGamePayload = Partial<
  Omit<AdminGame, 'id' | 'base_point' | 'created_at'>
> & {
  base_lat?: number | null;
  base_lng?: number | null;
};

export interface AdminSession {
  id: number;
  game: number;
  game_slug: string;
  game_name: string;
  slug: string;
  name: string;
  start_time: string;
  end_time: string;
  is_active: boolean;
  created_at: string | null;
}

export type AdminSessionPayload = Partial<
  Omit<AdminSession, 'id' | 'game_slug' | 'game_name' | 'created_at'>
>;

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

  listTowers(): Observable<AdminTower[]> {
    return this.http.get<AdminTower[]>('/api/staff/towers/');
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

  listZones(): Observable<AdminZone[]> {
    return this.http.get<AdminZone[]>('/api/staff/zones/');
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

  resetScores(): Observable<{ teams_reset: number }> {
    return this.http.post<{ teams_reset: number }>(
      '/api/staff/game-state/reset-scores/',
      {},
    );
  }

  // ---- Games ---------------------------------------------------------------

  listGames(): Observable<AdminGame[]> {
    return this.http.get<AdminGame[]>('/api/staff/games/');
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

  createSession(payload: AdminSessionPayload): Observable<AdminSession> {
    return this.http.post<AdminSession>('/api/staff/sessions/', payload);
  }

  updateSession(
    id: number,
    payload: AdminSessionPayload,
  ): Observable<AdminSession> {
    return this.http.patch<AdminSession>(`/api/staff/sessions/${id}/`, payload);
  }
}
