import { DatePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import * as L from 'leaflet';

import {
  LocationHistory,
  PageHeaderComponent,
  ReplayFrame,
  SessionReplayBundle,
  StaffApiService,
  TeamColorResolver,
  buildReplayFrames,
  bundleToReplayInput,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 14;
const UNCLAIMED_COLOR = '#9AAAB3';

/**
 * Session replay (session-replay capability).
 *
 * Plays a recorded Session back on a map with a timeline scrubber. The
 * bundle is fetched once; every frame after that is reconstructed
 * client-side by the shared projection in `shared/replay` — the same one
 * the simulator's tick tape goes through, so the two replays agree by
 * construction rather than by convention. Dragging the timeline issues
 * no requests.
 *
 * What a replay can show is bounded by what was recorded: tracking may
 * have been off, players may never have consented, and retention purges
 * the ping series on a timer. Those cases are stated on the page instead
 * of rendering an empty map and leaving the reader to guess.
 */
@Component({
  selector: 'app-session-replay',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FormsModule, RouterLink, PageHeaderComponent],
  template: `
    <a [routerLink]="['/sessions', sessionId]" class="small text-body-secondary">
      &larr; Back to session
    </a>

    <app-page-header
      [title]="bundle()?.session?.name || 'Session replay'"
      subtitle="Scrub a recorded session on the map — player tracks, tower ownership, and standings over time."
    />

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading()) {
      <div class="d-flex align-items-center text-body-secondary mb-3">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading replay…
      </div>
    }

    @if (bundle(); as b) {
      @if (notices().length) {
        <div class="alert alert-warning py-2">
          <ul class="mb-0 ps-3 small">
            @for (notice of notices(); track notice) {
              <li>{{ notice }}</li>
            }
          </ul>
        </div>
      }

      <div class="row g-3">
        <div class="col-lg-8">
          <div class="card">
            <div #mapContainer class="rounded-top" style="height: 460px"></div>
            <div class="card-body">
              <!-- Timeline -->
              <div class="d-flex align-items-center gap-2 mb-2">
                <div class="btn-group btn-group-sm" role="group" aria-label="Playback">
                  <button
                    type="button"
                    class="btn btn-outline-secondary"
                    title="Step back"
                    [disabled]="frameIndex() === 0"
                    (click)="step(-1)"
                  >
                    <i class="bi bi-skip-backward-fill"></i>
                  </button>
                  <button type="button" class="btn btn-primary" (click)="togglePlay()">
                    @if (playing()) {
                      <i class="bi bi-pause-fill"></i> Pause
                    } @else {
                      <i class="bi bi-play-fill"></i> Play
                    }
                  </button>
                  <button
                    type="button"
                    class="btn btn-outline-secondary"
                    title="Step forward"
                    [disabled]="frameIndex() >= maxFrame()"
                    (click)="step(1)"
                  >
                    <i class="bi bi-skip-forward-fill"></i>
                  </button>
                </div>
                <input
                  type="range"
                  class="form-range flex-grow-1"
                  aria-label="Replay timeline"
                  min="0"
                  [max]="maxFrame()"
                  [value]="frameIndex()"
                  (input)="seek($any($event.target).valueAsNumber)"
                />
                <select
                  class="form-select form-select-sm w-auto"
                  aria-label="Playback speed"
                  [ngModel]="speedMs()"
                  (ngModelChange)="speedMs.set(+$event)"
                >
                  <option [value]="1000">1x</option>
                  <option [value]="500">2x</option>
                  <option [value]="200">5x</option>
                  <option [value]="50">20x</option>
                </select>
              </div>
              <div class="d-flex justify-content-between small text-body-secondary">
                <span>
                  Frame {{ frameIndex() }} / {{ maxFrame() }} ·
                  <strong class="text-body">{{ currentFrame()?.label }}</strong>
                  @if (currentFrame()?.at; as at) {
                    <span class="ms-1">({{ at | date: 'mediumDate' }})</span>
                  }
                </span>
                <span>
                  {{ b.interval_seconds }}s per frame
                  @if (b.interval_coarsened) {
                    <span class="text-warning-emphasis">(coarsened to fit)</span>
                  }
                </span>
              </div>
              @if (purgedFraction() > 0) {
                <!-- The span retention has already eaten, marked rather
                     than silently trimmed off the front of the timeline. -->
                <div class="progress mt-2" style="height: 4px" role="img"
                     aria-label="Purged span of the timeline">
                  <div
                    class="progress-bar bg-secondary opacity-50"
                    [style.width.%]="purgedFraction() * 100"
                  ></div>
                </div>
                <div class="small text-body-secondary mt-1">
                  Shaded span has no surviving location history (purged by retention).
                </div>
              }
            </div>
          </div>
        </div>

        <div class="col-lg-4">
          <!-- Standings -->
          <div class="card mb-3">
            <div class="card-header py-2 small fw-semibold">Towers held</div>
            <ul class="list-group list-group-flush">
              @for (standing of currentFrame()?.standings ?? []; track standing.teamId) {
                <li class="list-group-item d-flex align-items-center justify-content-between py-2">
                  <span class="d-flex align-items-center gap-2">
                    <span
                      class="d-inline-block rounded-circle"
                      style="width: 12px; height: 12px"
                      [style.background-color]="colorFor(standing.teamId)"
                    ></span>
                    {{ standing.teamName }}
                  </span>
                  <span class="badge text-bg-secondary">{{ standing.towersHeld }}</span>
                </li>
              } @empty {
                <li class="list-group-item small text-body-secondary">No teams in this session.</li>
              }
            </ul>
            <div class="card-footer small text-body-secondary py-2">
              Towers held at this frame — not the score, which accrues over time from zone
              control and is not reconstructed here.
            </div>
          </div>

          <!-- Team filter -->
          <div class="card mb-3">
            <div class="card-header py-2 small fw-semibold">Plot</div>
            <div class="card-body py-2">
              <select
                class="form-select form-select-sm"
                aria-label="Filter plotted players by team"
                [ngModel]="teamFilter()"
                (ngModelChange)="teamFilter.set($event === '' ? null : +$event)"
              >
                <option value="">All teams</option>
                @for (team of b.teams; track team.id) {
                  <option [value]="team.id">{{ team.name }}</option>
                }
              </select>
              <div class="small text-body-secondary mt-2">
                {{ plottedCount() }} of {{ b.players.length }} player(s) on the map at this frame.
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Raw feed: exact sample values, for when the map isn't enough. -->
      <div class="card mt-3">
        <div class="card-header py-2">
          <button
            type="button"
            class="btn btn-sm btn-link p-0 text-decoration-none"
            (click)="toggleRawFeed()"
          >
            <i class="bi" [class.bi-chevron-right]="!showRaw()" [class.bi-chevron-down]="showRaw()"></i>
            Raw location pings
          </button>
        </div>
        @if (showRaw()) {
          <div class="card-body">
            <div class="row g-2 align-items-end mb-3">
              <div class="col-auto">
                <label class="form-label small mb-0" for="f-user">User id</label>
                <input
                  id="f-user"
                  class="form-control form-control-sm"
                  type="number"
                  [ngModel]="filterUser()"
                  (ngModelChange)="filterUser.set($event)"
                />
              </div>
              <div class="col-auto">
                <label class="form-label small mb-0" for="f-team">Team id</label>
                <input
                  id="f-team"
                  class="form-control form-control-sm"
                  type="number"
                  [ngModel]="filterTeam()"
                  (ngModelChange)="filterTeam.set($event)"
                />
              </div>
              <div class="col-auto">
                <label class="form-label small mb-0" for="f-from">From</label>
                <input
                  id="f-from"
                  class="form-control form-control-sm"
                  type="datetime-local"
                  [ngModel]="filterFrom()"
                  (ngModelChange)="filterFrom.set($event)"
                />
              </div>
              <div class="col-auto">
                <label class="form-label small mb-0" for="f-to">To</label>
                <input
                  id="f-to"
                  class="form-control form-control-sm"
                  type="datetime-local"
                  [ngModel]="filterTo()"
                  (ngModelChange)="filterTo.set($event)"
                />
              </div>
              <div class="col-auto">
                <button
                  type="button"
                  class="btn btn-sm btn-primary"
                  [disabled]="rawLoading()"
                  (click)="loadRawFeed()"
                >
                  @if (rawLoading()) {
                    <span class="spinner-border spinner-border-sm me-1"></span>
                  }
                  Apply
                </button>
              </div>
            </div>

            @if (rawFeed(); as h) {
              <p class="text-body-secondary small">
                {{ h.pings.length }} ping(s) · kept for {{ h.retention_days }} days after
                recording, then purged.
              </p>
              @if (h.pings.length) {
                <div class="table-responsive">
                  <table class="table table-sm align-middle">
                    <thead>
                      <tr>
                        <th>Player</th>
                        <th>Team</th>
                        <th>Position</th>
                        <th class="text-end">Accuracy (m)</th>
                        <th>Recorded</th>
                        <th>Received</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (p of h.pings; track $index) {
                        <tr>
                          <td>{{ p.username }}</td>
                          <td>
                            @if (p.team_name; as team) {
                              <span class="badge" [style.background-color]="p.team_color || '#6c757d'">
                                {{ team }}
                              </span>
                            } @else {
                              <span class="text-body-secondary">—</span>
                            }
                          </td>
                          <td class="small font-monospace">
                            {{ p.lat.toFixed(6) }}, {{ p.lng.toFixed(6) }}
                          </td>
                          <td class="text-end small">{{ p.accuracy !== null ? p.accuracy : '—' }}</td>
                          <td class="small">{{ p.recorded_at | date: 'medium' }}</td>
                          <td class="small text-body-secondary">
                            {{ p.received_at | date: 'shortTime' }}
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
              } @else {
                <div class="alert alert-info mb-0">
                  No location pings recorded for this selection.
                </div>
              }
            }
          </div>
        }
      </div>
    }
  `,
})
export class SessionReplayComponent {
  private readonly api = inject(StaffApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly destroyRef = inject(DestroyRef);

  private readonly mapContainer = viewChild<ElementRef<HTMLDivElement>>('mapContainer');

  protected readonly sessionId = Number(this.route.snapshot.paramMap.get('id'));
  protected readonly bundle = signal<SessionReplayBundle | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly frameIndex = signal(0);
  protected readonly playing = signal(false);
  protected readonly speedMs = signal(500);
  protected readonly teamFilter = signal<number | null>(null);

  protected readonly showRaw = signal(false);
  protected readonly rawFeed = signal<LocationHistory | null>(null);
  protected readonly rawLoading = signal(false);
  protected readonly filterUser = signal<number | null>(null);
  protected readonly filterTeam = signal<number | null>(null);
  protected readonly filterFrom = signal<string>('');
  protected readonly filterTo = signal<string>('');

  private playHandle: ReturnType<typeof setInterval> | null = null;
  private readonly teamColors = new TeamColorResolver();

  private map: L.Map | null = null;
  private zonesLayer: L.LayerGroup | null = null;
  private towersLayer: L.LayerGroup | null = null;
  private playersLayer: L.LayerGroup | null = null;

  /** Every frame, reconstructed once per bundle. Scrubbing only indexes this. */
  protected readonly frames = computed<ReplayFrame[]>(() => {
    const bundle = this.bundle();
    return bundle ? buildReplayFrames(bundleToReplayInput(bundle)) : [];
  });
  protected readonly maxFrame = computed(() => Math.max(0, this.frames().length - 1));
  protected readonly currentFrame = computed<ReplayFrame | null>(() => {
    const frames = this.frames();
    if (!frames.length) return null;
    return frames[Math.min(this.frameIndex(), frames.length - 1)];
  });

  /** Players drawn at this frame, after the team filter. */
  protected readonly plottedPlayers = computed(() => {
    const team = this.teamFilter();
    const players = this.currentFrame()?.players ?? [];
    return team === null ? players : players.filter((p) => p.teamId === team);
  });
  protected readonly plottedCount = computed(() => this.plottedPlayers().length);

  /**
   * Leading fraction of the timeline that retention has purged.
   *
   * Measured to the retention cutoff, not to the first surviving ping:
   * a session whose players simply started pinging a few minutes in has
   * lost nothing, and shading that gap would claim otherwise.
   */
  protected readonly purgedFraction = computed(() => {
    const bundle = this.bundle();
    if (!bundle?.availability.history_truncated) return 0;
    const cutoff = bundle.availability.retention_cutoff;
    if (!cutoff) return 0;
    const from = Date.parse(bundle.window.from);
    const to = Date.parse(bundle.window.to);
    if (!(to > from)) return 0;
    return Math.min(1, Math.max(0, (Date.parse(cutoff) - from) / (to - from)));
  });

  /** Plain statements of what this replay cannot show, and why. */
  protected readonly notices = computed<string[]>(() => {
    const bundle = this.bundle();
    if (!bundle) return [];
    const out: string[] = [];
    const { availability } = bundle;
    if (!availability.location_tracking_enabled) {
      out.push(
        'Location tracking was disabled for this session, so there are no player tracks. ' +
          'Tower ownership and standings still replay.',
      );
    } else if (availability.consented_players < availability.roster_players) {
      out.push(
        `${availability.consented_players} of ${availability.roster_players} players consented ` +
          'to location tracking; only those are plotted.',
      );
    }
    if (availability.history_truncated) {
      out.push(
        'Part of this session’s location history has been purged by retention' +
          (availability.retention_days ? ` (${availability.retention_days} days).` : '.'),
      );
    }
    if (bundle.interval_coarsened) {
      out.push(
        `The timeline was coarsened to ${bundle.interval_seconds}s per frame to cover the ` +
          'whole session.',
      );
    }
    return out;
  });

  constructor() {
    if (!this.sessionId) {
      this.loadError.set('Invalid session.');
    } else {
      this.load();
    }

    afterNextRender(() => this.initMap());

    effect(() => {
      // Re-render whenever the frame, the filter, or the bundle changes.
      const frame = this.currentFrame();
      const players = this.plottedPlayers();
      this.renderMap(frame, players);
    });

    this.destroyRef.onDestroy(() => {
      this.stopPlay();
      this.map?.remove();
    });
  }

  // ---- data ---------------------------------------------------------------

  private load(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.sessionReplay(this.sessionId).subscribe({
      next: (bundle) => {
        for (const team of bundle.teams) this.teamColors.learn(team.id, team.color);
        this.bundle.set(bundle);
        // Open on the end state, which is what a reader usually wants
        // first; the scrubber walks back from there.
        this.frameIndex.set(Math.max(0, bundle.frame_count - 1));
        this.loading.set(false);
        this.fitMapToContent();
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected toggleRawFeed(): void {
    const next = !this.showRaw();
    this.showRaw.set(next);
    if (next && this.rawFeed() === null) this.loadRawFeed();
  }

  protected loadRawFeed(): void {
    this.rawLoading.set(true);
    this.api
      .sessionLocationHistory(this.sessionId, {
        user: this.filterUser() ?? undefined,
        team: this.filterTeam() ?? undefined,
        from: this.filterFrom() ? new Date(this.filterFrom()).toISOString() : undefined,
        to: this.filterTo() ? new Date(this.filterTo()).toISOString() : undefined,
      })
      .subscribe({
        next: (feed) => {
          this.rawFeed.set(feed);
          this.rawLoading.set(false);
        },
        error: (err) => {
          this.rawLoading.set(false);
          this.loadError.set(extractErrorMessage(err));
        },
      });
  }

  // ---- playback -----------------------------------------------------------

  protected colorFor(teamId: number | null): string {
    return this.teamColors.colorFor(teamId);
  }

  protected seek(frame: number): void {
    this.frameIndex.set(Math.min(Math.max(0, frame), this.maxFrame()));
  }

  protected step(delta: number): void {
    this.seek(this.frameIndex() + delta);
  }

  protected togglePlay(): void {
    if (this.playing()) {
      this.stopPlay();
      return;
    }
    // Replaying from the end restarts rather than sitting still.
    if (this.frameIndex() >= this.maxFrame()) this.frameIndex.set(0);
    this.playing.set(true);
    this.playHandle = setInterval(() => {
      const next = this.frameIndex() + 1;
      if (next > this.maxFrame()) {
        this.stopPlay();
        return;
      }
      this.frameIndex.set(next);
    }, this.speedMs());
  }

  private stopPlay(): void {
    if (this.playHandle !== null) clearInterval(this.playHandle);
    this.playHandle = null;
    this.playing.set(false);
  }

  // ---- map ----------------------------------------------------------------

  private initMap(): void {
    const container = this.mapContainer()?.nativeElement;
    if (!container) return;
    this.map = L.map(container).setView(FALLBACK_CENTER, FALLBACK_ZOOM);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);
    this.zonesLayer = L.layerGroup().addTo(this.map);
    this.towersLayer = L.layerGroup().addTo(this.map);
    this.playersLayer = L.layerGroup().addTo(this.map);
    this.renderZones();
    this.renderMap(this.currentFrame(), this.plottedPlayers());
    this.fitMapToContent();
  }

  private renderZones(): void {
    const bundle = this.bundle();
    if (!this.zonesLayer || !bundle) return;
    this.zonesLayer.clearLayers();
    for (const zone of bundle.zones) {
      if (!zone.shape) continue;
      try {
        L.geoJSON(JSON.parse(zone.shape) as GeoJSON.GeometryObject, {
          style: { color: '#5F6B7A', weight: 1, fillOpacity: 0.05 },
        })
          .bindTooltip(zone.name)
          .addTo(this.zonesLayer);
      } catch {
        // A zone with unparseable geometry is skipped rather than
        // taking the whole map down with it.
      }
    }
  }

  private renderMap(frame: ReplayFrame | null, players: ReplayFrame['players']): void {
    if (!this.map || !this.towersLayer || !this.playersLayer) return;
    this.towersLayer.clearLayers();
    this.playersLayer.clearLayers();
    if (!frame) return;

    for (const tower of frame.towers) {
      if (tower.lat === null || tower.lng === null) continue;
      const owned = tower.ownerTeamId !== null;
      L.circleMarker([tower.lat, tower.lng], {
        radius: 10,
        color: '#1E2A32',
        weight: 2,
        fillColor: owned ? this.teamColors.colorFor(tower.ownerTeamId) : UNCLAIMED_COLOR,
        fillOpacity: owned ? 0.9 : 0.25,
      })
        .bindTooltip(`${tower.name} · ${tower.ownerTeamName ?? 'unclaimed'}`)
        .addTo(this.towersLayer);
    }

    for (const player of players) {
      L.circleMarker([player.lat, player.lng], {
        radius: 6,
        color: '#fff',
        weight: 1.5,
        fillColor: this.teamColors.colorFor(player.teamId),
        fillOpacity: 0.95,
      })
        .bindTooltip(`${player.username}${player.teamName ? ' · ' + player.teamName : ''}`)
        .addTo(this.playersLayer);
    }
  }

  /** Frame the map on the session's towers, falling back to its tracks. */
  private fitMapToContent(): void {
    const bundle = this.bundle();
    if (!this.map || !bundle) return;
    const points: [number, number][] = bundle.towers.map((t) => [t.lat, t.lng]);
    if (!points.length) {
      for (const position of bundle.positions) points.push([position.lat, position.lng]);
    }
    if (!points.length) return;
    this.map.fitBounds(L.latLngBounds(points).pad(0.2));
  }
}
