import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

const STORAGE_KEY = 'cercetador.auth.token';

export interface AuthResponse {
  token: string;
  user_id: number;
  username: string;
}

export interface ActiveRole {
  id: number;
  slug: string;
  name: string;
  builtin_power: string;
}

export interface UserProfile {
  id: number;
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  current_session: number | null;
  current_game: number | null;
  active_team_id: number | null;
  active_roles: ActiveRole[];
  is_staff: boolean;
  allow_player_team_creation: boolean;
  captain_of_team_id: number | null;
}

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);

  private readonly _token = signal<string | null>(this.readToken());
  private readonly _profile = signal<UserProfile | null>(null);

  readonly token = this._token.asReadonly();
  readonly profile = this._profile.asReadonly();
  readonly isAuthenticated = computed(() => this._token() !== null);
  readonly isStaff = computed(() => this._profile()?.is_staff ?? false);

  login(login: string, password: string): Observable<AuthResponse> {
    return this.http.post<AuthResponse>('/api/auth/login/', { login, password }).pipe(
      tap((res) => this.storeToken(res.token)),
    );
  }

  register(payload: {
    username: string;
    email: string;
    password: string;
    first_name?: string;
    last_name?: string;
  }): Observable<AuthResponse> {
    return this.http.post<AuthResponse>('/api/auth/register/', payload).pipe(
      tap((res) => this.storeToken(res.token)),
    );
  }

  logout(): Observable<void> {
    return this.http.post<void>('/api/auth/logout/', {}).pipe(
      tap(() => this.clearToken()),
    );
  }

  fetchProfile(): Observable<UserProfile> {
    return this.http.get<UserProfile>('/api/me/').pipe(
      tap((profile) => this._profile.set(profile)),
    );
  }

  requestPasswordReset(email: string): Observable<void> {
    return this.http.post<void>('/api/auth/password-reset/', { email });
  }

  confirmPasswordReset(uid: string, token: string, new_password: string): Observable<void> {
    return this.http.post<void>('/api/auth/password-reset/confirm/', {
      uid,
      token,
      new_password,
    });
  }

  setToken(token: string): void {
    this.storeToken(token);
  }

  private storeToken(token: string): void {
    localStorage.setItem(STORAGE_KEY, token);
    this._token.set(token);
  }

  private clearToken(): void {
    localStorage.removeItem(STORAGE_KEY);
    this._token.set(null);
    this._profile.set(null);
  }

  private readToken(): string | null {
    if (typeof localStorage === 'undefined') {
      return null;
    }
    return localStorage.getItem(STORAGE_KEY);
  }
}
