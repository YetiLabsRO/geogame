import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable, tap } from 'rxjs';

import { AuthService } from './auth.service';

export interface InvitePreview {
  team_name: string;
  team_group: string;
  expires_at: string;
}

export interface InviteAcceptResponse {
  token: string;
  user_id: number;
  username: string;
  team_id: number;
  team_name: string;
}

export interface InviteAcceptPayload {
  username?: string;
  email?: string;
  password?: string;
  first_name?: string;
  last_name?: string;
}

export type InviteStatus = 'pending' | 'accepted' | 'revoked' | 'expired';

export interface Invite {
  id: number;
  token: string;
  team: number;
  team_name: string;
  email: string | null;
  created_by: number | null;
  created_by_username: string | null;
  created_at: string;
  expires_at: string;
  accepted_by: number | null;
  accepted_at: string | null;
  revoked: boolean;
  status: InviteStatus;
}

export interface InviteCreatePayload {
  team: number;
  email?: string;
}

@Injectable({ providedIn: 'root' })
export class InvitesService {
  private readonly http = inject(HttpClient);
  private readonly auth = inject(AuthService);

  preview(token: string): Observable<InvitePreview> {
    return this.http.get<InvitePreview>(`/api/invites/${encodeURIComponent(token)}/`);
  }

  accept(token: string, payload: InviteAcceptPayload = {}): Observable<InviteAcceptResponse> {
    return this.http
      .post<InviteAcceptResponse>(`/api/invites/accept/${encodeURIComponent(token)}/`, payload)
      .pipe(tap((res) => this.auth.setToken(res.token)));
  }

  list(status?: InviteStatus): Observable<Invite[]> {
    const query = status ? `?status=${status}` : '';
    return this.http.get<Invite[]>(`/api/invites/${query}`);
  }

  create(payload: InviteCreatePayload): Observable<Invite> {
    return this.http.post<Invite>('/api/invites/', payload);
  }

  revoke(id: number): Observable<void> {
    return this.http.delete<void>(`/api/invites/${id}/`);
  }

  resend(id: number): Observable<void> {
    return this.http.post<void>(`/api/invites/${id}/resend/`, {});
  }
}
