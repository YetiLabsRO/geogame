import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/** Active hand-out binding of a badge, as returned by the staff API. */
export interface BadgeAssignmentInfo {
  id: number;
  session_id: number;
  session: string;
  player_id: number | null;
  player: string | null;
  team_id: number | null;
  team: string | null;
  assigned_at: string;
}

/** One fleet inventory row (wearable-badge-hardware). */
export interface BadgeRow {
  id: number;
  badge_id: string;
  hardware_mac: string | null;
  firmware_version: string;
  firmware_stale: boolean;
  battery_pct: number | null;
  battery_low: boolean;
  status: 'AVAILABLE' | 'ASSIGNED' | 'MAINTENANCE' | 'LOST' | 'RETIRED';
  last_seen_at: string | null;
  stale: boolean;
  note: string;
  assignment: BadgeAssignmentInfo | null;
  unreturned: boolean;
}

/** One gateway health row. */
export interface GatewayRow {
  id: number;
  name: string;
  transport: 'WIFI' | 'CELLULAR' | 'TABLET';
  token: string;
  active: boolean;
  last_seen_at: string | null;
  stale: boolean;
  coverage_note: string;
}

export interface RegisterBadgeRequest {
  badge_id?: string;
  hardware_mac?: string;
  firmware_version?: string;
  note?: string;
}

export interface AssignBadgeRequest {
  player_id?: number;
  team_id?: number;
  session_id?: number;
}

/**
 * Staff fleet API for wearable badges + gateways
 * (wearable-badge-hardware). Provisioning only: hand-out/collect manage
 * the asset registry; all gameplay flows through the gateway ingest
 * endpoint server-side.
 */
@Injectable({ providedIn: 'root' })
export class BadgesService {
  private readonly http = inject(HttpClient);

  badges(): Observable<BadgeRow[]> {
    return this.http.get<BadgeRow[]>('/api/staff/badges/');
  }

  registerBadge(body: RegisterBadgeRequest): Observable<BadgeRow> {
    return this.http.post<BadgeRow>('/api/staff/badges/', body);
  }

  assign(badgePk: number, body: AssignBadgeRequest): Observable<BadgeRow> {
    return this.http.post<BadgeRow>(`/api/staff/badges/${badgePk}/assign/`, body);
  }

  collect(badgePk: number, markLost = false): Observable<BadgeRow> {
    return this.http.post<BadgeRow>(`/api/staff/badges/${badgePk}/collect/`, {
      mark_lost: markLost,
    });
  }

  gateways(): Observable<GatewayRow[]> {
    return this.http.get<GatewayRow[]>('/api/staff/gateways/');
  }

  registerGateway(body: {
    name: string;
    transport?: string;
    coverage_note?: string;
  }): Observable<GatewayRow> {
    return this.http.post<GatewayRow>('/api/staff/gateways/', body);
  }
}
