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

import {
  CurrentSession,
  GameApiService,
  LivePlayer,
  RevealedTower,
  TowerFeature,
  ZoneFeature,
} from 'shared';

import { LocationStreamService } from '../location/location-stream.service';

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 17;
const LIVE_POLL_MIN_SECONDS = 10;
const DISCOVERY_PING_SECONDS = 20;
const DISCOVERY_TOAST_SECONDS = 8;

interface DiscoveryToast {
  id: number;
  name: string;
  method: string;
}

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
      <!-- tower-visibility: discovery cues as HIDDEN towers pop up. -->
      <div class="discovery-toasts">
        @for (toast of discoveryToasts(); track toast.id) {
          <div class="alert alert-info py-2 mb-2 shadow-sm">
            <i class="bi bi-binoculars-fill me-1"></i>
            <strong>{{ toast.name }}</strong> discovered!
            <span class="small text-body-secondary">({{ methodLabel(toast.method) }})</span>
          </div>
        }
      </div>
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
    .score-badge,
    .discovery-toasts {
      position: absolute;
      z-index: 1000;
    }
    .discovery-toasts {
      bottom: 0.75rem;
      left: 0.75rem;
      right: 0.75rem;
      pointer-events: none;
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
  private readonly stream = inject(LocationStreamService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');
  protected readonly errorMessage = signal<string | null>(null);
  protected readonly groupSlug = computed(
    () => this.route.snapshot.paramMap.get('slug') ?? null,
  );

  protected readonly discoveryToasts = signal<DiscoveryToast[]>([]);

  private map: L.Map | null = null;
  private liveLayer: L.LayerGroup | null = null;
  private geometryLayer: L.LayerGroup | null = null;
  private fogLayer: L.Polygon | null = null;
  private livePollHandle: ReturnType<typeof setInterval> | null = null;
  private discoveryHandle: ReturnType<typeof setInterval> | null = null;
  private session: CurrentSession | null = null;
  private toastSeq = 0;

  constructor() {
    afterNextRender(() => this.init());
    this.destroyRef.onDestroy(() => {
      if (this.livePollHandle) {
        clearInterval(this.livePollHandle);
      }
      if (this.discoveryHandle) {
        clearInterval(this.discoveryHandle);
      }
      this.map?.remove();
    });
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
        this.session = session;
        const game = session.game;
        if (game.base_point) {
          const [lng, lat] = game.base_point.coordinates;
          this.map?.setView([lat, lng], game.base_zoom_level || FALLBACK_ZOOM);
        }
        this.renderGeometry(zones, towers, slug !== null);
        this.setupLocation(session);
        // Consent gating (tower-visibility × live-location): with
        // tracking disabled there is no consent framework — start the
        // self-contained discovery fallback right away. With tracking
        // enabled, discovery starts only after consent is confirmed
        // (see setupLocation).
        if (!session.location.tracking_enabled) {
          this.setupDiscovery(session);
        }
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

  /**
   * live-location wiring: gate on consent, then stream + overlay.
   *
   * A location-enabled session without standing consent redirects to
   * the consent screen (playing is blocked server-side anyway). With
   * consent, the geolocation stream starts at the game-configured
   * interval and the live overlay polls `/api/location/live/` —
   * whose visibility filtering (location_visibility + the
   * presence-rules teammate refinement) happens server-side.
   */
  private setupLocation(session: CurrentSession): void {
    this.stream.configure(session.location);
    if (!session.location.tracking_enabled) {
      return;
    }
    this.api.locationConsent().subscribe({
      next: (consent) => {
        if (!consent.has_consent) {
          this.router.navigateByUrl('/location-consent');
          return;
        }
        this.stream.markConsented();
        this.startLivePolling(session.location.ping_interval_seconds);
        // Consent granted — positions may now drive discovery too.
        this.setupDiscovery(session);
      },
      error: () => {},
    });
  }

  private startLivePolling(intervalSeconds: number): void {
    const seconds = Math.max(LIVE_POLL_MIN_SECONDS, intervalSeconds || 0);
    this.refreshLive();
    this.livePollHandle = setInterval(() => this.refreshLive(), seconds * 1000);
  }

  private refreshLive(): void {
    this.api.liveLocations().subscribe({
      next: (live) => this.renderLive(live.players),
      error: () => {},
    });
  }

  private renderLive(players: LivePlayer[]): void {
    if (!this.map) return;
    if (this.liveLayer === null) {
      this.liveLayer = L.layerGroup().addTo(this.map);
    }
    this.liveLayer.clearLayers();
    for (const player of players) {
      const color = player.team_color || '#0d6efd';
      L.circleMarker([player.lat, player.lng], {
        radius: 6,
        color: '#fff',
        weight: 1.5,
        fillColor: color,
        fillOpacity: 0.95,
      })
        .bindTooltip(
          player.team_name ? `${player.username} · ${player.team_name}` : player.username,
        )
        .addTo(this.liveLayer);
    }
  }

  /**
   * tower-visibility: report positions and surface discoveries.
   *
   * The server evaluates discovery from BOTH position sources — the
   * live-location stream (when tracking is on and consented) and the
   * self-contained `POST /api/discovery/ping/` fallback. The map runs
   * the fallback loop whenever the session uses any non-VISIBLE tower;
   * the endpoint is idempotent, so overlapping with the stream is
   * harmless and the loop doubles as the toast source.
   */
  private setupDiscovery(session: CurrentSession): void {
    if (!session.visibility?.uses_discovery) return;
    if (!('geolocation' in navigator)) return;
    const sendPing = () => {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          this.api
            .discoveryPing({
              lat: position.coords.latitude,
              lng: position.coords.longitude,
            })
            .subscribe({
              next: (result) => this.onRevealed(result.newly_revealed),
              error: () => {},
            });
        },
        () => undefined,
        { enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 },
      );
    };
    sendPing();
    this.discoveryHandle = setInterval(sendPing, DISCOVERY_PING_SECONDS * 1000);
  }

  /** Discovery cue: toast each reveal and redraw the newly visible geometry. */
  private onRevealed(revealed: RevealedTower[]): void {
    if (!revealed.length) return;
    const toasts = revealed.map((r) => ({
      id: ++this.toastSeq,
      name: r.tower_name,
      method: r.method,
    }));
    this.discoveryToasts.update((current) => [...current, ...toasts]);
    setTimeout(() => {
      const ids = new Set(toasts.map((t) => t.id));
      this.discoveryToasts.update((current) => current.filter((t) => !ids.has(t.id)));
    }, DISCOVERY_TOAST_SECONDS * 1000);
    this.refreshGeometry();
  }

  private refreshGeometry(): void {
    const slug = this.groupSlug();
    forkJoin({
      zones: this.api.zones(slug ? { groupSlug: slug } : undefined),
      towers: this.api.towers(),
    }).subscribe({
      next: ({ zones, towers }) => this.renderGeometry(zones, towers, slug !== null),
      error: () => {},
    });
  }

  protected methodLabel(method: string): string {
    switch (method) {
      case 'PROXIMITY':
        return 'walked up to it';
      case 'ZONE_ENTRY':
        return 'entered the area';
      case 'ZONE_COVERAGE':
        return 'covered the area';
      case 'STAFF':
        return 'revealed by staff';
      default:
        return 'revealed';
    }
  }

  private renderGeometry(zones: ZoneFeature[], towers: TowerFeature[], scoreMode: boolean): void {
    if (!this.map) return;
    if (this.geometryLayer === null) {
      this.geometryLayer = L.layerGroup().addTo(this.map);
    }
    this.geometryLayer.clearLayers();
    this.renderZones(zones, scoreMode);
    this.renderTowers(towers);
    this.renderFog(zones);
  }

  /**
   * Fog-of-war overlay (tower-visibility): a translucent veil over the
   * whole map with the team-visible zones punched out. A `FOG_REVEAL`
   * zone only reaches the payload once revealed (zone entry / coverage),
   * so its hole appears — clearing the fog — as the team roams.
   */
  private renderFog(zones: ZoneFeature[]): void {
    if (!this.map) return;
    if (this.fogLayer) {
      this.fogLayer.remove();
      this.fogLayer = null;
    }
    if (!this.session?.visibility?.uses_fog) return;
    const world: L.LatLngExpression[] = [
      [-89, -359],
      [-89, 359],
      [89, 359],
      [89, -359],
    ];
    const holes = zones
      .filter((z) => !!z.shape)
      .map(
        (z) =>
          z.shape.coordinates[0].map(
            ([lng, lat]) => [lat, lng] as L.LatLngExpression,
          ),
      );
    this.fogLayer = L.polygon([world, ...holes], {
      stroke: false,
      fillColor: '#1f2937',
      fillOpacity: 0.45,
      interactive: false,
    }).addTo(this.map);
  }

  private renderZones(zones: ZoneFeature[], scoreMode: boolean): void {
    if (!this.map || !this.geometryLayer) return;
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
        .addTo(this.geometryLayer);
    }
  }

  private renderTowers(towers: TowerFeature[]): void {
    if (!this.map || !this.geometryLayer) return;
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
      }).addTo(this.geometryLayer);
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
