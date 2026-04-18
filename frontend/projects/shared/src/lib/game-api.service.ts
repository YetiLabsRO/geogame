import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

export interface CurrentGame {
  id: number;
  name: string;
  is_active: boolean;
  start_time: string;
  end_time: string;
  base_point: { type: 'Point'; coordinates: [number, number] } | null;
  base_zoom_level: number;
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

  zones(params?: { group?: number }): Observable<ZoneFeature[]> {
    const query = params?.group ? `?group=${params.group}` : '';
    return this.http.get<ZoneFeature[]>(`/api/zones/${query}`);
  }

  towers(): Observable<TowerFeature[]> {
    return this.http.get<TowerFeature[]>('/api/towers/');
  }
}
