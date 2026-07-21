import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import * as L from 'leaflet';

import {
  CurrentSession,
  GameApiService,
  LivePlayer,
  REALTIME_EVENTS,
  RealtimeEnvelope,
  RealtimeService,
  RealtimeTeamSummary,
  TowerFeature,
  TowerOwnershipChangedPayload,
  ZoneControlChangedPayload,
  ZoneFeature,
} from 'shared';

import { LocationStreamService } from '../location/location-stream.service';

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 17;
const LIVE_POLL_MIN_SECONDS = 10;
/** Poll interval used only while the realtime socket is down. */
const FALLBACK_POLL_MS = 30_000;

@Component({
  selector: 'app-map',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="map-wrapper">
      <div class="badges">
        @if (groupSlug()) {
          <div class="map-badge">
            <i class="bi bi-flag-fill"></i>
            Score map · {{ groupSlug() }}
          </div>
        }
        @if (realtime.connected()) {
          <div class="map-badge text-success">
            <i class="bi bi-broadcast"></i> Live
          </div>
        } @else if (realtime.status() === 'reconnecting') {
          <div class="map-badge text-warning">
            <i class="bi bi-arrow-repeat"></i> Reconnecting…
          </div>
        }
      </div>
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
    .badges {
      position: absolute;
      z-index: 1000;
    }
    .badges {
      top: 0.75rem;
      right: 0.75rem;
      display: flex;
      gap: 0.5rem;
    }
    .map-badge {
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
  protected readonly realtime = inject(RealtimeService);

  protected readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');
  protected readonly errorMessage = signal<string | null>(null);
  protected readonly groupSlug = computed(
    () => this.route.snapshot.paramMap.get('slug') ?? null,
  );

  private map: L.Map | null = null;
  private liveLayer: L.LayerGroup | null = null;
  private livePollHandle: ReturnType<typeof setInterval> | null = null;
  private session: CurrentSession | null = null;
  /** Live-recolor registries: rendered leaflet layers by identity. */
  private readonly towerMarkers = new Map<number, L.CircleMarker>();
  private readonly towerData = new Map<number, TowerFeature>();
  private readonly zoneLayers = new Map<string, L.GeoJSON>();
  private seenConnections = 0;

  constructor() {
    afterNextRender(() => this.init());

    // 4.2 — after every RE-connect, reconcile from a fresh REST snapshot
    // (events may have been missed while the socket was down).
    effect(() => {
      const count = this.realtime.connections();
      if (count > this.seenConnections && this.seenConnections > 0) {
        this.refreshData();
      }
      this.seenConnections = Math.max(this.seenConnections, count);
    });

    // 4.3 — apply live events to the already-rendered layers.
    this.realtime.events$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((envelope) => this.applyEvent(envelope));

    // 4.5 — polling fallback: refresh over REST only while the socket
    // is down (or realtime is disabled for the session).
    const pollHandle = setInterval(() => {
      if (!this.realtime.connected()) {
        this.refreshData();
      }
    }, FALLBACK_POLL_MS);

    this.destroyRef.onDestroy(() => {
      clearInterval(pollHandle);
      this.realtime.disconnect();
      if (this.livePollHandle) {
        clearInterval(this.livePollHandle);
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
        this.renderZones(zones, slug !== null);
        this.renderTowers(towers);
        this.setupLocation(session);
        // Open the live socket (skipped when realtime is disabled for
        // the session — polling then remains the update path).
        this.realtime.connect(session.id, session.realtime_enabled);
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

  /** Refetch the zone/tower snapshot and redraw layers in place. */
  private refreshData(): void {
    if (!this.map) return;
    const slug = this.groupSlug();
    forkJoin({
      zones: this.api.zones(slug ? { groupSlug: slug } : undefined),
      towers: this.api.towers(),
    }).subscribe({
      next: ({ zones, towers }) => {
        this.renderZones(zones, slug !== null);
        this.renderTowers(towers);
      },
      error: () => {
        // Keep the last rendered state; the next poll retries.
      },
    });
  }

  // ---- live events ---------------------------------------------------------

  private applyEvent(envelope: RealtimeEnvelope): void {
    if (this.session && envelope.session !== this.session.id) return;
    switch (envelope.type) {
      case REALTIME_EVENTS.towerOwnershipChanged:
        this.applyTowerOwnership(envelope.payload as TowerOwnershipChangedPayload);
        break;
      case REALTIME_EVENTS.zoneControlChanged:
        this.applyZoneControl(envelope.payload as ZoneControlChangedPayload);
        break;
      case REALTIME_EVENTS.sessionStateChanged:
        // Lifecycle flips can change what the REST snapshot exposes.
        this.refreshData();
        break;
      default:
        break; // scoreboard/bonus events are handled by other screens
    }
  }

  private applyTowerOwnership(payload: TowerOwnershipChangedPayload): void {
    const marker = this.towerMarkers.get(payload.tower_id);
    if (!marker) return;
    const slug = this.groupSlug();
    // In score-map mode the payload carries the per-group owner; on the
    // default map color by the capturing team (release → unowned).
    const owner: RealtimeTeamSummary | null = slug
      ? (payload.ownership[slug] ?? null)
      : payload.kind === 'released'
        ? null
        : payload.team;
    marker.setStyle({
      color: owner?.team_color || '#333',
      fillColor: owner?.team_color || '#fff',
      fillOpacity: owner ? 0.9 : 0.3,
    });
    const feature = this.towerData.get(payload.tower_id);
    if (feature) {
      feature.ownership = owner
        ? { name: owner.team_name, color: owner.team_color, current_score: 0 }
        : {};
      marker.bindPopup(this.towerPopup(feature));
    }
  }

  private applyZoneControl(payload: ZoneControlChangedPayload): void {
    const slug = this.groupSlug();
    if (!slug) return; // default map colors zones statically
    const layer = this.zoneLayers.get(payload.zone_name);
    const fill = payload.colors[slug];
    if (!layer || !fill) return;
    const unheld = fill === '#000000' || fill === '#FFFFFF';
    layer.setStyle({
      color: fill,
      weight: 2,
      fillColor: fill,
      fillOpacity: unheld ? 0.05 : 0.35,
    });
  }

  // ---- rendering -----------------------------------------------------------

  private renderZones(zones: ZoneFeature[], scoreMode: boolean): void {
    if (!this.map) return;
    for (const layer of this.zoneLayers.values()) {
      layer.remove();
    }
    this.zoneLayers.clear();
    for (const zone of zones) {
      if (!zone.shape) continue;
      const fill = scoreMode ? zone.team_color : zone.color;
      const unheld = scoreMode && (fill === '#000000' || fill === '#FFFFFF');
      const layer = L.geoJSON(zone.shape, {
        style: {
          color: fill,
          weight: 2,
          fillColor: fill,
          fillOpacity: unheld ? 0.05 : scoreMode ? 0.35 : 0.15,
        },
      })
        .bindTooltip(zone.name)
        .addTo(this.map);
      this.zoneLayers.set(zone.name, layer);
    }
  }

  private renderTowers(towers: TowerFeature[]): void {
    if (!this.map) return;
    for (const marker of this.towerMarkers.values()) {
      marker.remove();
    }
    this.towerMarkers.clear();
    this.towerData.clear();
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
      this.towerMarkers.set(tower.id, marker);
      this.towerData.set(tower.id, tower);
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
