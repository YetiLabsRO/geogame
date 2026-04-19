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
  code: string;
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
}
