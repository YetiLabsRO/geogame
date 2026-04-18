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
}
