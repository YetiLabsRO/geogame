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
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { HttpErrorResponse } from '@angular/common/http';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';
import * as L from 'leaflet';

import {
  ActiveMultiplier,
  CurrentSession,
  GameApiService,
  GeolocationService,
  HapticsService,
  LivePlayer,
  REALTIME_EVENTS,
  RealtimeEnvelope,
  RealtimeService,
  RealtimeTeamSummary,
  RevealedTower,
  TowerFeature,
  TowerOwnershipChangedPayload,
  UiAlertComponent,
  UiIconComponent,
  ZoneControlChangedPayload,
  ZoneFeature,
} from 'shared';

import { LocationStreamService } from '../location/location-stream.service';

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 17;
const LIVE_POLL_MIN_SECONDS = 10;
/** Poll interval used only while the realtime socket is down. */
const FALLBACK_POLL_MS = 30_000;
/** Poll interval for the active-multiplier boost banner. */
const BOOST_POLL_MS = 60_000;
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
  imports: [RouterLink, UiIconComponent, UiAlertComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="map-wrapper">
      <div class="map-pills">
        @if (groupSlug()) {
          <div class="map-pill">
            <ui-icon name="map" [size]="14" />
            <span class="tr-meta-tiny">Score map · {{ groupSlug() }}</span>
          </div>
        }
        @if (realtime.connected()) {
          <div class="map-pill map-pill--live">
            <ui-icon name="sparkle" [size]="14" />
            <span class="tr-meta-tiny">Live</span>
          </div>
        } @else if (realtime.status() === 'reconnecting') {
          <div class="map-pill map-pill--warn">
            <ui-icon name="clock" [size]="14" />
            <span class="tr-meta-tiny">Reconnecting…</span>
          </div>
        }
      </div>
      @if (boosts().length > 0) {
        <div class="map-boost-banner">
          @for (b of boosts(); track b.id) {
            <div class="map-pill map-pill--warn">
              <ui-icon name="star" [size]="14" />
              <span class="tr-meta-tiny">&times;{{ b.factor }} points {{ boostTarget(b) }}</span>
            </div>
          }
        </div>
      }
      <div class="map" #mapContainer></div>
      @if (errorMessage(); as msg) {
        <ui-alert tone="danger" [withIcon]="true" class="map-error">{{ msg }}</ui-alert>
      }
      <!-- tower-visibility: discovery cues as HIDDEN towers pop up. -->
      <div class="map-discovery-toasts">
        @for (toast of discoveryToasts(); track toast.id) {
          <ui-alert tone="success" [withIcon]="true" class="map-discovery-toast">
            <strong>{{ toast.name }}</strong> discovered!
            <span class="tr-meta-tiny">({{ methodLabel(toast.method) }})</span>
          </ui-alert>
        }
      </div>
      <a class="map-fab" routerLink="/scan" aria-label="Scan tag">
        <ui-icon name="target" [size]="26" />
      </a>
    </div>
  `,
  styles: `
    :host {
      display: block;
      height: calc(100dvh - 56px - var(--safe-top) - 78px - var(--safe-bottom));
      width: 100%;
    }
    .map-wrapper {
      position: relative;
      height: 100%;
      width: 100%;
    }
    .map {
      height: 100%;
      width: 100%;
    }
  `,
})
export class MapComponent {
  private readonly api = inject(GameApiService);
  private readonly stream = inject(LocationStreamService);
  private readonly geolocation = inject(GeolocationService);
  private readonly haptics = inject(HapticsService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  protected readonly realtime = inject(RealtimeService);

  protected readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');
  protected readonly errorMessage = signal<string | null>(null);
  /** Multipliers in effect right now — "Double points" banner (5.3). */
  protected readonly boosts = signal<ActiveMultiplier[]>([]);
  protected readonly groupSlug = computed(() => this.route.snapshot.paramMap.get('slug') ?? null);

  protected readonly discoveryToasts = signal<DiscoveryToast[]>([]);

  private map: L.Map | null = null;
  private liveLayer: L.LayerGroup | null = null;
  private geometryLayer: L.LayerGroup | null = null;
  private fogLayer: L.Polygon | null = null;
  private livePollHandle: ReturnType<typeof setInterval> | null = null;
  private discoveryHandle: ReturnType<typeof setInterval> | null = null;
  private session: CurrentSession | null = null;
  /** Live-recolor registries: rendered leaflet layers by identity. */
  private readonly towerMarkers = new Map<number, L.CircleMarker>();
  private readonly towerData = new Map<number, TowerFeature>();
  private readonly zoneLayers = new Map<string, L.GeoJSON>();
  private seenConnections = 0;
  private toastSeq = 0;
  /** Cached for the haptics "stolen from us" check (D4/2.7). */
  private myTeamName: string | null = null;

  constructor() {
    afterNextRender(() => this.init());

    this.api.myTeam().subscribe({
      next: (team) => (this.myTeamName = team.name),
      error: () => {}, // no team yet (e.g. between sessions) — steal haptics simply won't fire
    });

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
        // Open the live socket (skipped when realtime is disabled for
        // the session — polling then remains the update path).
        this.realtime.connect(session.id, session.realtime_enabled);
        this.watchBoosts(session.id);
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
        if (err instanceof HttpErrorResponse && (err.status === 404 || err.status === 409)) {
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
    const sendPing = () => {
      this.geolocation
        .current({ enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 })
        .then((position) => {
          this.api
            .discoveryPing({
              lat: position.coords.latitude,
              lng: position.coords.longitude,
            })
            .subscribe({
              next: (result) => this.onRevealed(result.newly_revealed),
              error: () => {},
            });
        })
        .catch(() => undefined);
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
    this.refreshData();
  }

  /** Refetch the zone/tower snapshot and redraw layers in place. */
  private refreshData(): void {
    if (!this.map) return;
    const slug = this.groupSlug();
    forkJoin({
      zones: this.api.zones(slug ? { groupSlug: slug } : undefined),
      towers: this.api.towers(),
    }).subscribe({
      next: ({ zones, towers }) => this.renderGeometry(zones, towers, slug !== null),
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
      case REALTIME_EVENTS.bonusAppeared:
        // Haptics only here — the boost banner is driven by watchBoosts().
        this.haptics.notify('warning');
        break;
      default:
        break; // scoreboard events are handled by other screens
    }
  }

  private applyTowerOwnership(payload: TowerOwnershipChangedPayload): void {
    const feature = this.towerData.get(payload.tower_id);
    const previousOwnerName =
      feature?.ownership && 'name' in feature.ownership ? feature.ownership.name : null;
    // A steal targeting OUR team: haptics fire regardless of which map
    // mode is rendered (default or per-group score map).
    if (
      payload.kind === 'stolen' &&
      previousOwnerName !== null &&
      this.myTeamName !== null &&
      previousOwnerName === this.myTeamName
    ) {
      this.haptics.impact('heavy');
    }

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

  /** Poll the in-effect multipliers so the banner tracks live boosts. */
  private watchBoosts(sessionId: number): void {
    const load = () =>
      this.api.sessionActiveMultipliers(sessionId).subscribe({
        next: (list) => this.boosts.set(list),
        error: () => {},
      });
    load();
    const handle = setInterval(load, BOOST_POLL_MS);
    this.destroyRef.onDestroy(() => clearInterval(handle));
  }

  protected boostTarget(b: ActiveMultiplier): string {
    if (b.label) return `— ${b.label}`;
    if (b.scope === 'TOWER') return `at ${b.tower_name}`;
    if (b.scope === 'ZONE') return `in ${b.zone_name}`;
    return 'everywhere';
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

  // ---- rendering -----------------------------------------------------------

  private renderGeometry(zones: ZoneFeature[], towers: TowerFeature[], scoreMode: boolean): void {
    if (!this.map) return;
    if (this.geometryLayer === null) {
      this.geometryLayer = L.layerGroup().addTo(this.map);
    }
    this.geometryLayer.clearLayers();
    // Reset the realtime-recolor registries in lockstep with the cleared
    // layer group so live events resolve against the freshly drawn layers.
    this.zoneLayers.clear();
    this.towerMarkers.clear();
    this.towerData.clear();
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
      .map((z) => z.shape.coordinates[0].map(([lng, lat]) => [lat, lng] as L.LatLngExpression));
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
      const layer = L.geoJSON(zone.shape, {
        style: {
          color: fill,
          weight: 2,
          fillColor: fill,
          fillOpacity: unheld ? 0.05 : scoreMode ? 0.35 : 0.15,
        },
      })
        .bindTooltip(zone.name)
        .addTo(this.geometryLayer);
      this.zoneLayers.set(zone.name, layer);
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
      this.towerMarkers.set(tower.id, marker);
      this.towerData.set(tower.id, tower);
    }
  }

  private towerPopup(tower: TowerFeature): string {
    const name = escapeHtml(tower.name);
    const owner = tower.ownership as Partial<{ name: string; color: string }>;
    const ownerLine = owner?.name
      ? `<div style="margin-top:4px;color:var(--color-text-secondary)">Held by <strong>${escapeHtml(owner.name)}</strong></div>`
      : '<div style="margin-top:4px;color:var(--color-text-muted)">Unclaimed</div>';
    const bonus = tower.has_initial_bonus
      ? '<div style="margin-top:2px;font-size:12px;color:var(--color-success)">Initial bonus available</div>'
      : '';
    const detailLink =
      `<a href="/tower/${tower.id}" style="display:inline-block;margin-top:8px;padding:6px 14px;` +
      'border-radius:var(--radius-full);background:var(--color-brand-primary);' +
      'color:var(--color-text-onBrand);text-decoration:none;font-size:12px;font-weight:600">' +
      'View details</a>';
    return (
      `<div style="font-family:var(--font-ui);min-width:160px">` +
      `<div style="font-family:var(--font-display);font-weight:700;color:var(--color-text-primary)">${name}</div>` +
      `${ownerLine}${bonus}${detailLink}</div>`
    );
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
