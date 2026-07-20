import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import { TeamSummary } from './game-api.service';

export type JoinConfirmation = 'AUTO_APPROVE' | 'CAPTAIN' | 'STAFF';
export type JoinRequestStatus = 'PENDING' | 'APPROVED' | 'REJECTED';
export type JoinRequestSource = 'BROWSE' | 'QR' | 'LINK';

export interface JoinableTeam {
  id: number;
  name: string;
  color: string;
  group_name: string | null;
  member_count: number;
  join_confirmation: JoinConfirmation;
  my_request_status: JoinRequestStatus | null;
}

export interface TeamJoinRequest {
  id: number;
  team: number;
  team_name: string;
  username: string;
  first_name: string;
  last_name: string;
  status: JoinRequestStatus;
  source: JoinRequestSource;
  note: string;
  requested_at: string;
  decided_by_username: string | null;
  decided_at: string | null;
}

export interface JoinCodePayload {
  team: number;
  team_name: string;
  join_code: string | null;
  join_url: string | null;
}

export interface JoinCodePreview {
  team_name: string;
  team_group: string;
  color: string;
  session_name: string;
  game_name: string;
  join_confirmation: JoinConfirmation;
}

export interface CreateTeamPayload {
  name: string;
  group?: number | null;
  color?: string;
}

@Injectable({ providedIn: 'root' })
export class TeamFormationService {
  private readonly http = inject(HttpClient);

  createTeam(payload: CreateTeamPayload): Observable<TeamSummary> {
    return this.http.post<TeamSummary>('/api/teams/', payload);
  }

  joinableTeams(): Observable<JoinableTeam[]> {
    return this.http.get<JoinableTeam[]>('/api/joinable-teams/');
  }

  joinCode(teamId: number): Observable<JoinCodePayload> {
    return this.http.get<JoinCodePayload>(`/api/teams/${teamId}/join-code/`);
  }

  rotateJoinCode(teamId: number): Observable<JoinCodePayload> {
    return this.http.post<JoinCodePayload>(`/api/teams/${teamId}/join-code/`, {
      action: 'rotate',
    });
  }

  revokeJoinCode(teamId: number): Observable<JoinCodePayload> {
    return this.http.post<JoinCodePayload>(`/api/teams/${teamId}/join-code/`, {
      action: 'revoke',
    });
  }

  joinCodePreview(code: string): Observable<JoinCodePreview> {
    return this.http.get<JoinCodePreview>(`/api/join-codes/${encodeURIComponent(code)}/`);
  }

  requestJoin(payload: { team?: number; code?: string; note?: string }): Observable<TeamJoinRequest> {
    return this.http.post<TeamJoinRequest>('/api/join-requests/', payload);
  }

  joinRequests(status?: JoinRequestStatus): Observable<TeamJoinRequest[]> {
    const query = status ? `?status=${status}` : '';
    return this.http.get<TeamJoinRequest[]>(`/api/join-requests/${query}`);
  }

  approveJoinRequest(id: number): Observable<TeamJoinRequest> {
    return this.http.post<TeamJoinRequest>(`/api/join-requests/${id}/approve/`, {});
  }

  rejectJoinRequest(id: number): Observable<TeamJoinRequest> {
    return this.http.post<TeamJoinRequest>(`/api/join-requests/${id}/reject/`, {});
  }
}
