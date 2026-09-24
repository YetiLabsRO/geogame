import { DatePipe, DecimalPipe } from '@angular/common';
import {
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
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ActivatedRoute } from '@angular/router';
import * as L from 'leaflet';
import { Observable, switchMap, throwError } from 'rxjs';

import {
  AuthService,
  OverviewEvent,
  OverviewHiddenReason,
  OverviewSnapshot,
  OverviewStanding,
  OverviewTower,
  REALTIME_EVENTS,
  RealtimeService,
  ScoreboardUpdatedPayload,
  StaffApiService,
  StatusPillComponent,
  TeamColorResolver,
  TowerOwnershipChangedPayload,
  ZoneControlChangedPayload,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 15;
/** Paint for a tower no team in the selected group holds. */
const UNCLAIMED_COLOR = '#9AAAB3';
/** Zone fills the backend uses for "contested" and "nobody". */
const ZONE_CONTESTED = '#FFFFFF';
const ZONE_UNHELD = '#000000';
/** Full snapshot refresh, and the only path that moves player dots. */
const SNAPSHOT_POLL_MS = 15_000;
/** Slower resnapshot when the socket is carrying the map for us. */
const SNAPSHOT_POLL_LIVE_MS = 60_000;
const TICKER_LIMIT = 8;

/**
 * Why the overview is not plotting anyone, in words a runner can act on.
 *
 * Every one of these means "the map is fine, the dots are off" — never
 * "something is broken" — so each says which setting decided it.
 */
export const HIDDEN_REASON_TEXT: Record<OverviewHiddenReason, string> = {
  TRACKING_DISABLED: 'Location tracking is off for this game.',
  VISIBILITY_NONE: 'This game stores positions but shows them to nobody.',
  VISIBILITY_OWN_TEAM:
    'This game limits live positions to a player’s own team. A shared screen has no team, ' +
    'so nothing is plotted — set live visibility to “everyone” to show them here.',
  VISIBILITY_NEAREST_ONLY:
    'This game shows each player only their nearest few teammates. That is relative to a ' +
    'viewer, and a screen has none, so nothing is plotted.',
};

/**
 * Live overview (live-overview capability).
 *
 * One Session's present instant, big enough to read across a room:
 * towers painted by the team holding them, zones tinted by control,
 * standings alongside, and a ticker of what just changed hands.
 *
 * Two routes render this component. `/sessions/:id/overview` runs behind
 * `staffGuard` and fills from the staff endpoint; `/live/:token` runs
 * with no account at all, fills from the share-link endpoint, and shows
 * neither management nor controls. Everything below is written against
 * the snapshot, not against which of the two fetched it — that is what
 * keeps the unauthenticated path from growing its own quietly different
 * rendering.
 *
 * Ownership is per TeamGroup, because several groups play one map at
 * once. The view therefore paints one group at a time and offers a
 * selector when a Game has more than one; painting all groups together
 * would overlay two unrelated games on one tower.
 */
@Component({
  selector: 'app-live-overview',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, DecimalPipe, StatusPillComponent],
  template: `
    <div class="overview" [class.presenting]="presenting()" [class.bare]="!!shareToken">
      <header class="overview-head">
        <div class="titles">
          <div class="session-name">{{ snapshot()?.session?.name || 'Live overview' }}</div>
          <div class="game-name">{{ snapshot()?.session?.game_name }}</div>
        </div>

        @if (snapshot(); as s) {
          <app-status-pill [status]="s.session.state" />
        }

        <div class="spacer"></div>

        @if (groups().length > 1) {
          <div class="btn-group btn-group-sm" role="group" aria-label="Team group">
            @for (g of groups(); track g.slug) {
              <button
                type="button"
                class="btn"
                [class.btn-primary]="activeGroup() === g.slug"
                [class.btn-outline-secondary]="activeGroup() !== g.slug"
                (click)="selectGroup(g.slug)"
              >
                {{ g.name }}
              </button>
            }
          </div>
        }

        <span class="live-badge" [class.is-live]="realtime.connected()">
          <i class="bi" [class.bi-broadcast]="realtime.connected()"
             [class.bi-arrow-repeat]="!realtime.connected()"></i>
          {{ realtime.connected() ? 'Live' : 'Polling' }}
        </span>

        <button
          type="button"
          class="btn btn-sm btn-outline-secondary"
          (click)="togglePresenting()"
          [attr.aria-pressed]="presenting()"
        >
          <i class="bi" [class.bi-fullscreen]="!presenting()"
             [class.bi-fullscreen-exit]="presenting()"></i>
          {{ presenting() ? 'Exit' : 'Present' }}
        </button>
      </header>

      @if (loadError(); as msg) {
        <div class="alert alert-danger m-3">{{ msg }}</div>
      }

      @if (notFound()) {
        <div class="alert alert-warning m-3">
          This link is no longer valid. Ask whoever set the screen up for a new one.
        </div>
      } @else if (snapshot()) {
        <div class="overview-body">
          <div class="map-column">
            <div #mapContainer class="map"></div>
            @if (!positions().visible && positions().reason; as reason) {
              <div class="dots-note" role="status">
                <i class="bi bi-eye-slash"></i>
                <span>{{ hiddenReasonText(reason) }}</span>
              </div>
            }
          </div>

          <aside class="rail">
            <section class="rail-block">
              <h2 class="rail-title">Standings</h2>
              <ol class="standings">
                @for (row of standings(); track row.team_id) {
                  <li class="standing">
                    <span class="swatch" [style.background-color]="row.team_color"></span>
                    <span class="team">{{ row.team_name }}</span>
                    <span class="score">{{ row.current_score | number: '1.0-0' }}</span>
                  </li>
                } @empty {
                  <li class="empty">No teams in this group yet.</li>
                }
              </ol>
            </section>

            <section class="rail-block">
              <h2 class="rail-title">Towers held</h2>
              <ul class="held">
                @for (row of heldCounts(); track row.teamId) {
                  <li>
                    <span class="swatch" [style.background-color]="row.color"></span>
                    <span class="team">{{ row.name }}</span>
                    <span class="score">{{ row.count }}</span>
                  </li>
                } @empty {
                  <li class="empty">Nothing held yet.</li>
                }
              </ul>
            </section>

            <section class="rail-block grow">
              <h2 class="rail-title">Just now</h2>
              <ul class="ticker">
                @for (e of ticker(); track e.tower_id + '@' + e.at) {
                  <li>
                    <span class="swatch" [style.background-color]="e.team_color"></span>
                    <span class="what">
                      <strong>{{ e.team_name }}</strong> took {{ e.tower_name }}
                    </span>
                    <span class="when">{{ e.at | date: 'HH:mm' }}</span>
                  </li>
                } @empty {
                  <li class="empty">No captures yet.</li>
                }
              </ul>
            </section>
          </aside>
        </div>
      } @else if (loading()) {
        <div class="p-4 text-body-secondary">
          <span class="spinner-border spinner-border-sm me-2"></span> Loading…
        </div>
      }
    </div>
  `,
  styleUrl: './live-overview.component.scss',
})
export class LiveOverviewComponent {
  private readonly api = inject(StaffApiService);
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly realtime = inject(RealtimeService);

  private readonly mapContainer = viewChild<ElementRef<HTMLDivElement>>('mapContainer');

  /** Set on the share route; null on the staff route. */
  protected readonly shareToken = this.route.snapshot.paramMap.get('token');
  private readonly routeSessionId = Number(this.route.snapshot.paramMap.get('id'));

  protected readonly snapshot = signal<OverviewSnapshot | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly notFound = signal(false);
  protected readonly presenting = signal(false);
  private readonly chosenGroup = signal<string | null>(null);

  private readonly teamColors = new TeamColorResolver();
  private map: L.Map | null = null;
  private zonesLayer: L.LayerGroup | null = null;
  private towersLayer: L.LayerGroup | null = null;
  private playersLayer: L.LayerGroup | null = null;
  private pollHandle: ReturnType<typeof setInterval> | null = null;
  private pollMs = SNAPSHOT_POLL_MS;
  private fitted = false;

  protected readonly groups = computed(() => this.snapshot()?.groups ?? []);
  protected readonly positions = computed(
    () => this.snapshot()?.positions ?? { visible: false, reason: null, items: [] },
  );

  /** The group being painted: the chosen one, else the first. */
  protected readonly activeGroup = computed(() => {
    const chosen = this.chosenGroup();
    if (chosen !== null) return chosen;
    return this.groups()[0]?.slug ?? null;
  });

  protected readonly standings = computed<OverviewStanding[]>(() => {
    const rows = this.snapshot()?.standings ?? [];
    const group = this.activeGroup();
    // A game with no groups at all still has teams; don't filter them away.
    if (group === null || !this.groups().length) return rows;
    return rows.filter((r) => r.group_slug === group);
  });

  protected readonly ticker = computed<OverviewEvent[]>(() => {
    const rows = this.snapshot()?.events ?? [];
    const group = this.activeGroup();
    const scoped = group === null ? rows : rows.filter((e) => e.group_slug === group);
    return scoped.slice(0, TICKER_LIMIT);
  });

  /** Towers currently held, per team, in the selected group. */
  protected readonly heldCounts = computed(() => {
    const group = this.activeGroup();
    const counts = new Map<number, { teamId: number; name: string; color: string; count: number }>();
    for (const tower of this.snapshot()?.towers ?? []) {
      const owner = group === null ? null : tower.ownership[group];
      if (!owner) continue;
      const row = counts.get(owner.team_id) ?? {
        teamId: owner.team_id,
        name: owner.team_name,
        color: owner.team_color,
        count: 0,
      };
      row.count += 1;
      counts.set(owner.team_id, row);
    }
    return [...counts.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  });

  constructor() {
    this.load();

    // The map's host lives inside `@if (snapshot())`, so it does not
    // exist until the first response lands. Waiting for the element is
    // what makes the map appear at all.
    effect(() => {
      const host = this.mapContainer()?.nativeElement;
      if (host && !this.map) this.initMap(host);
    });

    effect(() => {
      // Repaint on a new snapshot, an applied event, or a group switch.
      this.snapshot();
      this.activeGroup();
      this.renderMap();
    });

    this.startPolling();
    this.subscribeRealtime();

    this.destroyRef.onDestroy(() => {
      if (this.pollHandle) clearInterval(this.pollHandle);
      this.realtime.disconnect();
      this.map?.remove();
      this.map = null;
    });
  }

  protected hiddenReasonText(reason: OverviewHiddenReason): string {
    return HIDDEN_REASON_TEXT[reason] ?? 'Player positions are hidden for this session.';
  }

  protected selectGroup(slug: string): void {
    this.chosenGroup.set(slug);
  }

  protected togglePresenting(): void {
    const next = !this.presenting();
    this.presenting.set(next);
    // Browser fullscreen is best-effort: it needs a user gesture and can
    // be refused. The CSS class carries the layout either way, so a
    // refusal costs the chrome-free look and nothing else.
    try {
      if (next) void document.documentElement.requestFullscreen?.();
      else if (document.fullscreenElement) void document.exitFullscreen?.();
    } catch {
      /* not available — the class alone still presents */
    }
    // Leaflet sizes to its container; the container just changed.
    setTimeout(() => this.map?.invalidateSize(), 250);
  }

  // ---- data ---------------------------------------------------------------

  /**
   * The snapshot, from whichever of the three addresses is in play.
   *
   * `/live/:token` carries its own credential; `/sessions/:id/overview`
   * names the Session; `/overview` means "whatever the session switcher
   * has selected", matching how `/scoreboard` is scoped. The profile is
   * awaited rather than read, because after a reload it has not landed
   * yet and treating that as "no session" would show an error on a
   * perfectly good page.
   */
  private fetch(): Observable<OverviewSnapshot> {
    if (this.shareToken) return this.api.publicOverview(this.shareToken);
    if (Number.isFinite(this.routeSessionId) && this.routeSessionId > 0) {
      return this.api.sessionOverview(this.routeSessionId);
    }
    const known = this.auth.profile()?.current_session;
    if (known) return this.api.sessionOverview(known);
    return this.auth.ensureProfile().pipe(
      switchMap((profile) =>
        profile.current_session
          ? this.api.sessionOverview(profile.current_session)
          : throwError(() => ({
              error: {
                detail:
                  'No current session selected. Pick one from the session switcher, ' +
                  'or open a specific session’s overview.',
              },
            })),
      ),
    );
  }

  private load(): void {
    this.loading.set(true);
    this.fetch()
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe({
        next: (snapshot) => {
          for (const team of snapshot.teams) this.teamColors.learn(team.id, team.color);
          this.snapshot.set(snapshot);
          this.loading.set(false);
          this.loadError.set(null);
          this.notFound.set(false);
          this.connectRealtime(snapshot.session.id);
          if (!this.fitted) {
            this.fitMapToContent();
            this.fitted = true;
          }
        },
        error: (err: { status?: number }) => {
          this.loading.set(false);
          // A revoked link is a 404, and it is the expected end of a
          // share link's life rather than a failure to report as one.
          if (err?.status === 404 && this.shareToken) {
            this.notFound.set(true);
            this.realtime.disconnect();
            return;
          }
          this.loadError.set(extractErrorMessage(err));
        },
      });
  }

  private startPolling(): void {
    if (this.pollHandle) clearInterval(this.pollHandle);
    this.pollHandle = setInterval(() => this.load(), this.pollMs);
  }

  private setPollInterval(ms: number): void {
    if (this.pollMs === ms) return;
    this.pollMs = ms;
    this.startPolling();
  }

  private connectRealtime(sessionId: number): void {
    if (this.shareToken) this.realtime.connectShared(sessionId, this.shareToken);
    else this.realtime.connect(sessionId);
  }

  private subscribeRealtime(): void {
    // Positions are not on the socket and never have been, so the poll
    // stays either way — just slower while events are arriving.
    effect(() => {
      this.setPollInterval(
        this.realtime.connected() ? SNAPSHOT_POLL_LIVE_MS : SNAPSHOT_POLL_MS,
      );
    });

    this.realtime
      .eventsOfType<TowerOwnershipChangedPayload>(REALTIME_EVENTS.towerOwnershipChanged)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(({ payload }) => this.applyOwnership(payload));

    this.realtime
      .eventsOfType<ZoneControlChangedPayload>(REALTIME_EVENTS.zoneControlChanged)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(({ payload }) => this.applyZoneColors(payload));

    this.realtime
      .eventsOfType<ScoreboardUpdatedPayload>(REALTIME_EVENTS.scoreboardUpdated)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(({ payload }) => this.applyScoreboard(payload));

    // Lifecycle and anything else: cheapest correct response is a
    // resnapshot, and these are rare.
    this.realtime
      .eventsOfType(REALTIME_EVENTS.sessionStateChanged)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.load());
  }

  /**
   * Apply a capture without refetching.
   *
   * The envelope's `ownership` is already keyed by group slug, the same
   * shape the snapshot carries, so this is a field swap rather than a
   * translation.
   */
  private applyOwnership(payload: TowerOwnershipChangedPayload): void {
    const current = this.snapshot();
    if (!current) return;
    const ownership = payload.ownership as OverviewTower['ownership'] | undefined;
    if (!ownership) return;
    const towers = current.towers.map((t) =>
      t.id === payload.tower_id ? { ...t, ownership } : t,
    );
    const event: OverviewEvent | null = payload.team
      ? {
          tower_id: payload.tower_id,
          tower_name: payload.tower_name,
          team_id: payload.team.team_id,
          team_name: payload.team.team_name,
          team_color: payload.team.team_color,
          group_slug:
            Object.keys(ownership).find(
              (slug) => ownership[slug]?.team_id === payload.team?.team_id,
            ) ?? null,
          at: new Date().toISOString(),
          still_held: true,
        }
      : null;
    this.snapshot.set({
      ...current,
      towers,
      events: event ? [event, ...current.events] : current.events,
    });
  }

  private applyZoneColors(payload: ZoneControlChangedPayload): void {
    const current = this.snapshot();
    if (!current || !payload.colors) return;
    const colors = payload.colors as Record<string, string>;
    this.snapshot.set({
      ...current,
      zones: current.zones.map((z) => (z.id === payload.zone_id ? { ...z, colors } : z)),
    });
  }

  private applyScoreboard(payload: ScoreboardUpdatedPayload): void {
    const current = this.snapshot();
    if (!current) return;
    const scores = new Map(payload.entries.map((e) => [e.team_id, e.current_score]));
    this.snapshot.set({
      ...current,
      standings: current.standings
        .map((row) =>
          scores.has(row.team_id)
            ? { ...row, current_score: scores.get(row.team_id)! }
            : row,
        )
        .sort((a, b) => b.current_score - a.current_score || a.team_name.localeCompare(b.team_name)),
    });
  }

  // ---- map ----------------------------------------------------------------

  private initMap(container: HTMLElement): void {
    this.map = L.map(container, { zoomControl: false }).setView(
      FALLBACK_CENTER,
      FALLBACK_ZOOM,
    );
    L.control.zoom({ position: 'bottomright' }).addTo(this.map);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);
    this.zonesLayer = L.layerGroup().addTo(this.map);
    this.towersLayer = L.layerGroup().addTo(this.map);
    this.playersLayer = L.layerGroup().addTo(this.map);
    this.renderMap();
    this.fitMapToContent();
    this.fitted = true;
  }

  private renderMap(): void {
    const snapshot = this.snapshot();
    if (!this.map || !snapshot || !this.zonesLayer || !this.towersLayer) return;
    const group = this.activeGroup();

    this.zonesLayer.clearLayers();
    for (const zone of snapshot.zones) {
      if (!zone.shape) continue;
      const raw = group === null ? undefined : zone.colors[group];
      const held = raw !== undefined && raw !== ZONE_UNHELD;
      const contested = raw === ZONE_CONTESTED;
      try {
        L.geoJSON(JSON.parse(zone.shape) as GeoJSON.GeometryObject, {
          style: {
            color: held && !contested ? raw : '#5F6B7A',
            weight: held ? 2 : 1,
            fillColor: held && !contested ? raw : '#5F6B7A',
            // Contested reads as a hatch-free neutral rather than white
            // fill, which on OSM tiles looks like a hole in the map.
            fillOpacity: contested ? 0.12 : held ? 0.3 : 0.05,
          },
        })
          .bindTooltip(zone.name)
          .addTo(this.zonesLayer);
      } catch {
        // Unparseable geometry skips its zone rather than taking the
        // whole map down.
      }
    }

    this.towersLayer.clearLayers();
    for (const tower of snapshot.towers) {
      const owner = group === null ? null : tower.ownership[group];
      L.circleMarker([tower.lat, tower.lng], {
        radius: 11,
        color: '#1E2A32',
        weight: 2,
        fillColor: owner ? owner.team_color : UNCLAIMED_COLOR,
        fillOpacity: owner ? 0.95 : 0.25,
      })
        .bindTooltip(`${tower.name} · ${owner ? owner.team_name : 'unclaimed'}`)
        .addTo(this.towersLayer);
    }

    if (!this.playersLayer) return;
    this.playersLayer.clearLayers();
    const positions = snapshot.positions;
    if (!positions.visible) return;
    for (const player of positions.items) {
      L.circleMarker([player.lat, player.lng], {
        radius: 6,
        color: '#fff',
        weight: 1.5,
        fillColor: player.team_color || this.teamColors.colorFor(player.team_id),
        fillOpacity: 0.95,
      })
        .bindTooltip(player.username ?? player.team_name ?? 'player')
        .addTo(this.playersLayer);
    }
  }

  private fitMapToContent(): void {
    const snapshot = this.snapshot();
    if (!this.map || !snapshot) return;
    const points: [number, number][] = snapshot.towers.map((t) => [t.lat, t.lng]);
    for (const p of snapshot.positions.items) points.push([p.lat, p.lng]);
    if (!points.length) return;
    const bounds = L.latLngBounds(points).pad(0.2);
    this.map.fitBounds(bounds);
    // The rail and the header claim their width after this first paint,
    // so a fit computed now is off-centre by however much they take.
    // Re-measure once the layout has settled.
    setTimeout(() => {
      this.map?.invalidateSize();
      this.map?.fitBounds(bounds);
    }, 0);
  }
}
