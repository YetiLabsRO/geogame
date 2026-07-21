import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

/** One observed BLE advertiser, as reported by a phone (or the simulator). */
export interface ProximityObservation {
  token: string;
  rssi: number;
}

export interface ProximityIdentityInfo {
  token: string;
  rotates_at: string | null;
  rotated: boolean;
  report_interval_seconds: number;
  scan_duty_cycle_percent: number;
  freshness_window_seconds: number;
}

export interface ProximityReportResult {
  id: number;
  recorded: number;
  discarded: number;
  events_derived: number;
}

export interface BleCapabilityResult {
  ble_capable: boolean;
  require_ble_capable: boolean;
  admitted: boolean;
  detail: string;
}

export interface DementorMe {
  role: 'WIZARD' | 'DEMENTOR';
  energy: number;
  starting_energy: number;
  conversion_threshold: number;
  alive: boolean;
  last_delta: number;
  trend: 'DRAINING' | 'GAINING' | 'STABLE';
  last_tick_at: string | null;
  reports_stale: boolean;
  report_interval_seconds: number;
  freshness_window_seconds: number;
}

export interface DementorPlayerRow {
  player_id: number;
  username: string;
  team: string | null;
  role: 'WIZARD' | 'DEMENTOR';
  energy: number;
  alive: boolean;
  last_delta: number;
  last_tick_at: string | null;
}

export interface DementorTotals {
  session: number;
  enabled: boolean;
  totals: { wizards: number; dementors: number; out_of_play: number };
  players: DementorPlayerRow[];
}

/**
 * BLE proximity substrate + dementors mode API (mode-dementors-ble).
 *
 * The server is authoritative: this client only submits raw
 * observations and reads back server-computed energy/roles. Real BLE
 * advertise/scan needs the native shell — Web Bluetooth cannot
 * advertise — so the web player app drives these endpoints through the
 * debug simulator panel.
 */
@Injectable({ providedIn: 'root' })
export class DementorsService {
  private readonly http = inject(HttpClient);

  identity(rotate = false): Observable<ProximityIdentityInfo> {
    return this.http.post<ProximityIdentityInfo>('/api/proximity/identity/', { rotate });
  }

  report(observations: ProximityObservation[]): Observable<ProximityReportResult> {
    return this.http.post<ProximityReportResult>('/api/proximity/reports/', {
      observations,
    });
  }

  capability(bleCapable: boolean): Observable<BleCapabilityResult> {
    return this.http.post<BleCapabilityResult>('/api/proximity/capability/', {
      ble_capable: bleCapable,
    });
  }

  me(): Observable<DementorMe> {
    return this.http.get<DementorMe>('/api/dementors/me/');
  }

  totals(sessionId: number): Observable<DementorTotals> {
    return this.http.get<DementorTotals>(
      `/api/staff/dementors/session/${sessionId}/totals/`,
    );
  }
}
