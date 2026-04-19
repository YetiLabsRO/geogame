import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { forkJoin } from 'rxjs';
import * as L from 'leaflet';

import { GameApiService, TowerFeature, ZoneFeature } from 'shared';

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 17;

@Component({
  selector: 'app-map',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="map-wrapper">
      @if (groupSlug()) {
        <div class="score-badge">
          <i class="bi bi-flag-fill"></i>
          Score map · {{ groupSlug() }}
        </div>
      }
      <div class="map" #mapContainer></div>
      @if (errorMessage(); as msg) {
        <div class="alert alert-warning map-error">{{ msg }}</div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
      height: calc(100vh - 4rem);
    }
    .map-wrapper {
      position: relative;
      height: 100%;
    }
    .map {
      height: 100%;
      width: 100%;
      border-radius: 0.375rem;
    }
    .map-error,
    .score-badge {
      position: absolute;
      z-index: 1000;
    }
    .score-badge {
      top: 0.75rem;
      right: 0.75rem;
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid rgba(0, 0, 0, 0.1);
      border-radius: 999px;
      padding: 0.25rem 0.75rem;
      font-size: 0.875rem;
      font-weight: 500;
    }
    .map-error {
      top: 1rem;
      left: 1rem;
      right: 1rem;
      margin: 0;
    }
  `,
})
export class MapComponent {
  private readonly api = inject(GameApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');
  protected readonly errorMessage = signal<string | null>(null);
  protected readonly groupSlug = computed(
    () => this.route.snapshot.paramMap.get('slug') ?? null,
  );

  private map: L.Map | null = null;

  constructor() {
    afterNextRender(() => this.init());
    this.destroyRef.onDestroy(() => this.map?.remove());
  }

  private init(): void {
    this.map = L.map(this.mapContainer().nativeElement).setView(FALLBACK_CENTER, FALLBACK_ZOOM);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);

    const slug = this.groupSlug();
    forkJoin({
      session: this.api.currentSession(),
      zones: this.api.zones(slug ? { groupSlug: slug } : undefined),
      towers: this.api.towers(),
    }).subscribe({
      next: ({ session, zones, towers }) => {
        const game = session.game;
        if (game.base_point) {
          const [lng, lat] = game.base_point.coordinates;
          this.map?.setView([lat, lng], game.base_zoom_level || FALLBACK_ZOOM);
        }
        this.renderZones(zones, slug !== null);
        this.renderTowers(towers);
      },
      error: (err) => {
        // 404 (no session) and 409 (multiple candidates) mean the
        // player needs to land on /pick-session before we can render.
        if (
          err instanceof HttpErrorResponse &&
          (err.status === 404 || err.status === 409)
        ) {
          this.router.navigateByUrl('/pick-session');
          return;
        }
        this.errorMessage.set('Could not load map data. Check your connection and refresh.');
      },
    });
  }

  private renderZones(zones: ZoneFeature[], scoreMode: boolean): void {
    if (!this.map) return;
    for (const zone of zones) {
      if (!zone.shape) continue;
      const fill = scoreMode ? zone.team_color : zone.color;
      const unheld = scoreMode && (fill === '#000000' || fill === '#FFFFFF');
      L.geoJSON(zone.shape, {
        style: {
          color: fill,
          weight: 2,
          fillColor: fill,
          fillOpacity: unheld ? 0.05 : scoreMode ? 0.35 : 0.15,
        },
      })
        .bindTooltip(zone.name)
        .addTo(this.map);
    }
  }

  private renderTowers(towers: TowerFeature[]): void {
    if (!this.map) return;
    for (const tower of towers) {
      if (!tower.location) continue;
      const [lng, lat] = tower.location.coordinates;
      const owner = (tower.ownership as Partial<{ name: string; color: string }>) ?? {};
      const marker = L.circleMarker([lat, lng], {
        radius: 9,
        color: owner.color || '#333',
        weight: 2,
        fillColor: owner.color || '#fff',
        fillOpacity: owner.name ? 0.9 : 0.3,
      }).addTo(this.map);
      marker.bindPopup(this.towerPopup(tower));
    }
  }

  private towerPopup(tower: TowerFeature): string {
    const name = escapeHtml(tower.name);
    const owner = tower.ownership as Partial<{ name: string; color: string }>;
    const ownerLine = owner?.name
      ? `<div class="mt-1">Held by <strong>${escapeHtml(owner.name)}</strong></div>`
      : '<div class="mt-1 text-body-secondary">Unclaimed</div>';
    const bonus = tower.has_initial_bonus
      ? '<div class="small text-success">Initial bonus available</div>'
      : '';
    const detailLink =
      `<a class="btn btn-sm btn-primary mt-2" href="/tower/${tower.id}">View details</a>`;
    return `<div class="fw-semibold">${name}</div>${ownerLine}${bonus}${detailLink}`;
  }
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
