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
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { LowerCasePipe } from '@angular/common';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import * as L from 'leaflet';

import {
  AdminGame,
  ConfirmService,
  CreateSimulationRunPayload,
  DementorTickPayload,
  FieldRowComponent,
  PageHeaderComponent,
  REALTIME_EVENTS,
  RealtimeEnvelope,
  RealtimeService,
  ScoreboardUpdatedPayload,
  SimPlayer,
  SimTowerState,
  SimulationEvent,
  SimulationRun,
  SimulationState,
  StaffApiService,
  StatTileComponent,
  StatusPillComponent,
  TeamColorResolver,
  TowerOwnershipChangedPayload,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';
import { ReplayDisplayFrame, buildReplayFrames } from './replay';

// Cluj-Napoca — mirrors simulator/driver.py's DEFAULT_CENTER, used only
// until a run's resolved config.center_lat/lng is known.
const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 16;

/** Auto-play multipliers on top of the run's configured tick_seconds. */
const LIVE_SPEED_OPTIONS = [0.5, 1, 2, 4, 8] as const;
/** Replay playback intervals, ms between advancing one tick. */
const REPLAY_SPEED_OPTIONS_MS = [1000, 500, 250, 100] as const;

/**
 * Marker paint for dementors-mode roles. Fixed hex (not CSS tokens) —
 * these render on Leaflet's SVG canvas over non-theme-reactive OSM
 * tiles, matching the existing precedent in map.component.ts /
 * field-mode.component.ts of hardcoding Leaflet paint colors.
 */
const ROLE_COLOR = {
  WIZARD: '#2C74B3',
  DEMENTOR: '#1E2A32',
  UNKNOWN: '#9AAAB3',
} as const;
const UNCLAIMED_COLOR = '#9AAAB3';

type WorkspaceMode = 'live' | 'replay';
type GameMode = 'DOMINATION' | 'DEMENTORS';

/** Unified shape rendered on the map, whichever source (live/replay) feeds it. */
interface DisplayPlayer {
  profile_id: number;
  username: string;
  team_id: number | null;
  team_name: string | null;
  lat: number;
  lng: number;
  role: string;
  energy: number | null;
  alive: boolean;
}

@Component({
  selector: 'app-simulator',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FieldRowComponent, LowerCasePipe, PageHeaderComponent, ReactiveFormsModule, StatTileComponent, StatusPillComponent],
  template: `
    <app-page-header
      title="Simulator"
      subtitle="Drive a real Game/Session with a fake roster — step or auto-play ticks live, then scrub the recorded tape."
      [topoBg]="true"
    >
      <button
        actions
        type="button"
        class="btn btn-sm btn-outline-secondary"
        (click)="loadRuns()"
        [disabled]="runsLoading()"
      >
        @if (runsLoading()) {
          <span class="spinner-border spinner-border-sm me-1"></span>
        }
        <i class="bi bi-arrow-clockwise"></i> Refresh runs
      </button>
    </app-page-header>

    <div class="row g-4 mb-4">
      <div class="col-lg-7">
        <div class="card h-100">
          <div class="card-body">
            <h2 class="h6 mb-3"><i class="bi bi-play-circle me-1"></i>New run</h2>
            <form [formGroup]="createForm" (ngSubmit)="createRun()" novalidate>
              <div class="row g-3">
                <div class="col-sm-6">
                  <app-field-row label="Run name" for="sim-name">
                    <input class="form-control" id="sim-name" type="text" formControlName="name" />
                  </app-field-row>
                </div>
                <div class="col-sm-6">
                  <app-field-row
                    label="Template game"
                    for="sim-template"
                    hint="Clone an existing Game's towers/zones/challenge bank. Leave as 'new' for a bare throwaway map — fine for dementors-mode testing, but there will be no towers to capture."
                  >
                    <select class="form-select" id="sim-template" formControlName="templateGameId">
                      <option [ngValue]="null">— create a new game —</option>
                      @for (g of games(); track g.id) {
                        <option [ngValue]="g.id">{{ g.name }}</option>
                      }
                    </select>
                  </app-field-row>
                </div>
                @if (createForm.controls.templateGameId.value === null) {
                  <div class="col-sm-6">
                    <app-field-row
                      label="New game name"
                      for="sim-game-name"
                      help="Optional — defaults to the run name."
                    >
                      <input class="form-control" id="sim-game-name" type="text" formControlName="gameName" />
                    </app-field-row>
                  </div>
                }
                <div class="col-sm-6">
                  <app-field-row
                    label="Game mode"
                    for="sim-mode"
                    hint="Domination: teams race to capture towers. Dementors: wizards vs dementors chase/flee on an energy economy."
                  >
                    <select class="form-select" id="sim-mode" formControlName="mode">
                      <option value="DOMINATION">Domination (tower captures)</option>
                      <option value="DEMENTORS">Dementors (wizards vs dementors)</option>
                    </select>
                  </app-field-row>
                </div>
                <div class="col-sm-3">
                  <app-field-row label="Players" for="sim-n-players" [error]="fieldError('nPlayers')">
                    <input class="form-control" id="sim-n-players" type="number" min="1" formControlName="nPlayers" />
                  </app-field-row>
                </div>
                <div class="col-sm-3">
                  <app-field-row label="Teams" for="sim-n-teams" [error]="fieldError('nTeams')">
                    <input class="form-control" id="sim-n-teams" type="number" min="1" formControlName="nTeams" />
                  </app-field-row>
                </div>
                <div class="col-sm-4">
                  <app-field-row
                    label="Tick (seconds)"
                    for="sim-tick-seconds"
                    hint="Simulated seconds per step; also paces the Play auto-loop."
                    [error]="fieldError('tickSeconds')"
                  >
                    <input class="form-control" id="sim-tick-seconds" type="number" min="1" formControlName="tickSeconds" />
                  </app-field-row>
                </div>
                <div class="col-sm-4">
                  <app-field-row
                    label="Capture probability"
                    for="sim-capture-prob"
                    hint="Chance a team in range of an eligible tower captures it each tick."
                    [error]="fieldError('captureProbability')"
                  >
                    <input
                      class="form-control"
                      id="sim-capture-prob"
                      type="number"
                      min="0"
                      max="1"
                      step="0.05"
                      formControlName="captureProbability"
                    />
                  </app-field-row>
                </div>
                <div class="col-sm-4">
                  <app-field-row label="Seed" for="sim-seed" hint="Same seed + config replays identically.">
                    <input class="form-control" id="sim-seed" type="number" formControlName="seed" />
                  </app-field-row>
                </div>
                <div class="col-sm-4">
                  <app-field-row
                    label="Center latitude"
                    for="sim-center-lat"
                    help="Blank uses the game's base point (or Cluj-Napoca)."
                  >
                    <input class="form-control" id="sim-center-lat" type="number" step="any" formControlName="centerLat" />
                  </app-field-row>
                </div>
                <div class="col-sm-4">
                  <app-field-row label="Center longitude" for="sim-center-lng">
                    <input class="form-control" id="sim-center-lng" type="number" step="any" formControlName="centerLng" />
                  </app-field-row>
                </div>
                <div class="col-sm-4">
                  <app-field-row label="Spawn radius (m)" for="sim-radius" [error]="fieldError('radiusM')">
                    <input class="form-control" id="sim-radius" type="number" min="10" formControlName="radiusM" />
                  </app-field-row>
                </div>
              </div>

              @if (createError(); as msg) {
                <div class="alert alert-danger py-2 mt-3 mb-0">{{ msg }}</div>
              }

              <button type="submit" class="btn btn-primary mt-3" [disabled]="createForm.invalid || creating()">
                @if (creating()) {
                  <span class="spinner-border spinner-border-sm me-1"></span>
                }
                Create + set up run
              </button>
            </form>
          </div>
        </div>
      </div>

      <div class="col-lg-5">
        <div class="card h-100">
          <div class="card-body">
            <h2 class="h6 mb-3"><i class="bi bi-list-ul me-1"></i>Runs</h2>
            @if (runsError(); as msg) {
              <div class="alert alert-danger py-2">{{ msg }}</div>
            }
            @if (runsLoading() && runs().length === 0) {
              <div class="d-flex align-items-center text-body-secondary">
                <span class="spinner-border spinner-border-sm me-2"></span> Loading…
              </div>
            } @else if (runs().length === 0) {
              <div class="alert alert-info py-2 mb-0">No runs yet — create one to get started.</div>
            } @else {
              <div class="table-responsive">
                <table class="table table-sm align-middle mb-0">
                  <thead>
                    <tr>
                      <th>Name</th>
                      <th>Status</th>
                      <th class="text-end">Ticks</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (run of runs(); track run.id) {
                      <tr [class.table-active]="activeRun()?.id === run.id">
                        <td>
                          <div class="fw-semibold">{{ run.name }}</div>
                          <div class="small text-body-secondary">#{{ run.id }} · seed {{ run.seed }}</div>
                        </td>
                        <td><app-status-pill [status]="run.status" /></td>
                        <td class="text-end tabular-nums">{{ run.tick_count }}</td>
                        <td class="text-end">
                          <div class="btn-group btn-group-sm">
                            <button type="button" class="btn btn-outline-primary" (click)="selectRun(run)">
                              <i class="bi bi-eye"></i> Open
                            </button>
                            <button type="button" class="btn btn-outline-danger" (click)="teardownRun(run)">
                              <i class="bi bi-trash"></i>
                            </button>
                          </div>
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
          </div>
        </div>
      </div>
    </div>

    @if (workspaceError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }
    @if (workspaceLoading()) {
      <div class="d-flex align-items-center text-body-secondary mb-3">
        <span class="spinner-border spinner-border-sm me-2"></span> Loading run…
      </div>
    }

    <div class="sim-workspace">
      <div class="sim-workspace__header">
        <div>
          <h2 class="h5 mb-0">
            @if (activeRun(); as run) {
              {{ run.name }}
              <app-status-pill class="ms-2" [status]="run.status" />
            } @else {
              No run selected
            }
          </h2>
          @if (activeRun(); as run) {
            <div class="small text-body-secondary">
              #{{ run.id }} · tick {{ run.tick_count }}
              @if (realtime.connected()) {
                <span class="text-success ms-2"><i class="bi bi-broadcast"></i> live</span>
              } @else if (realtime.status() === 'reconnecting') {
                <span class="text-warning ms-2"><i class="bi bi-arrow-repeat"></i> reconnecting…</span>
              }
            </div>
          }
        </div>
        @if (activeRun()) {
          <div class="d-flex align-items-center gap-2">
            <div class="btn-group btn-group-sm" role="group" aria-label="Workspace mode">
              <button
                type="button"
                class="btn"
                [class.btn-primary]="workspaceMode() === 'live'"
                [class.btn-outline-primary]="workspaceMode() !== 'live'"
                (click)="switchMode('live')"
              >
                <i class="bi bi-broadcast"></i> Live drive
              </button>
              <button
                type="button"
                class="btn"
                [class.btn-primary]="workspaceMode() === 'replay'"
                [class.btn-outline-primary]="workspaceMode() !== 'replay'"
                (click)="switchMode('replay')"
              >
                <i class="bi bi-clock-history"></i> Replay
              </button>
            </div>
            <button type="button" class="btn btn-sm btn-outline-secondary" (click)="closeWorkspace()" title="Close">
              <i class="bi bi-x-lg"></i>
            </button>
          </div>
        }
      </div>

      <div class="sim-workspace__body">
        <div class="sim-map-col">
          <div class="sim-map" #mapContainer>
            @if (!activeRun()) {
              <div class="sim-map__empty">
                <i class="bi bi-map"></i>
                <p class="mb-0">Create or open a run to see it on the map.</p>
              </div>
            }
          </div>

          <div class="sim-legend small text-body-secondary mt-2 d-flex flex-wrap gap-3">
            @if (dementorsEnabled()) {
              <span><span class="sim-legend__dot" [style.background]="roleColor.WIZARD"></span> Wizard</span>
              <span><span class="sim-legend__dot" [style.background]="roleColor.DEMENTOR"></span> Dementor</span>
              <span><span class="sim-legend__dot" [style.background]="roleColor.UNKNOWN"></span> Unassigned / out</span>
            } @else {
              <span>Marker fill = team color. Gray = unclaimed tower.</span>
            }
          </div>

          @if (workspaceMode() === 'replay' && activeRun()) {
            <div class="card mt-3">
              <div class="card-body">
                @if (timelineLoading()) {
                  <div class="d-flex align-items-center text-body-secondary">
                    <span class="spinner-border spinner-border-sm me-2"></span> Loading tape…
                  </div>
                } @else {
                  <div class="d-flex align-items-center gap-2 mb-2">
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-primary"
                      (click)="toggleReplayPlay()"
                      [disabled]="replayMaxTick() === 0"
                    >
                      <i class="bi" [class.bi-play-fill]="!replayPlaying()" [class.bi-pause-fill]="replayPlaying()"></i>
                    </button>
                    <input
                      type="range"
                      class="form-range flex-grow-1"
                      min="0"
                      [max]="replayMaxTick()"
                      [value]="replayTick()"
                      (input)="onScrub($any($event.target).valueAsNumber)"
                    />
                    <span class="small tabular-nums" style="min-width:6rem;text-align:right">
                      tick {{ replayTick() }} / {{ replayMaxTick() }}
                    </span>
                  </div>
                  <div class="d-flex align-items-center gap-1">
                    <span class="small text-body-secondary me-1">Speed:</span>
                    @for (ms of replaySpeedOptionsMs; track ms) {
                      <button
                        type="button"
                        class="btn btn-sm"
                        [class.btn-secondary]="replaySpeedMs() === ms"
                        [class.btn-outline-secondary]="replaySpeedMs() !== ms"
                        (click)="setReplaySpeed(ms)"
                      >
                        {{ 1000 / ms }}x
                      </button>
                    }
                  </div>
                  @if (replayMaxTick() === 0) {
                    <div class="small text-body-secondary mt-2">
                      No ticks recorded yet — step the simulation in Live drive first.
                    </div>
                  }
                }
              </div>
            </div>
          }
        </div>

        <div class="sim-side-col">
          @if (activeRun(); as run) {
            <div class="card mb-3">
              <div class="card-body">
                <h3 class="h6 mb-2">Controls</h3>
                @if (workspaceMode() === 'live') {
                  <div class="d-flex flex-wrap gap-2 mb-2">
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-primary"
                      (click)="step()"
                      [disabled]="!canStep() || stepping() || autoPlaying()"
                    >
                      <i class="bi bi-skip-forward-fill"></i> Step
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm"
                      [class.btn-primary]="!autoPlaying()"
                      [class.btn-warning]="autoPlaying()"
                      (click)="toggleLivePlay()"
                      [disabled]="!canStep()"
                    >
                      <i class="bi" [class.bi-play-fill]="!autoPlaying()" [class.bi-pause-fill]="autoPlaying()"></i>
                      {{ autoPlaying() ? 'Playing…' : 'Play' }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      (click)="pauseRun()"
                      [disabled]="run.status !== 'RUNNING'"
                    >
                      <i class="bi bi-pause-fill"></i> Pause
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      (click)="stopRun()"
                      [disabled]="run.status === 'FINISHED'"
                    >
                      <i class="bi bi-stop-fill"></i> Stop
                    </button>
                  </div>
                  <div class="d-flex align-items-center gap-1 mb-3">
                    <span class="small text-body-secondary me-1">Auto-play speed:</span>
                    @for (mult of liveSpeedOptions; track mult) {
                      <button
                        type="button"
                        class="btn btn-sm"
                        [class.btn-secondary]="liveSpeedMultiplier() === mult"
                        [class.btn-outline-secondary]="liveSpeedMultiplier() !== mult"
                        (click)="setLiveSpeed(mult)"
                      >
                        {{ mult }}x
                      </button>
                    }
                  </div>
                  @if (run.status !== 'RUNNING') {
                    <p class="small text-body-secondary mb-2">
                      This run is {{ run.status | lowercase }} — stepping is disabled. There is no
                      resume; Stop/teardown are the only ways forward from here.
                    </p>
                  }
                } @else {
                  <p class="small text-body-secondary mb-2">
                    Replay mode scrubs the recorded tape client-side — it never calls the backend
                    or advances the run.
                  </p>
                }
                <button type="button" class="btn btn-sm btn-outline-danger" (click)="teardownRun(run)">
                  <i class="bi bi-trash"></i> Teardown run
                </button>
              </div>
            </div>

            @if (workspaceMode() === 'live') {
              <div class="row g-2 mb-3">
                @for (entry of liveState()?.scoreboard ?? []; track entry.team_id) {
                  <div class="col-6">
                    <app-stat-tile [label]="entry.name" [value]="entry.score" icon="bi-flag-fill" tone="primary" />
                  </div>
                }
              </div>
            } @else {
              <div class="row g-2 mb-3">
                @for (entry of replayOwnershipCounts(); track entry.team_id) {
                  <div class="col-6">
                    <app-stat-tile
                      [label]="entry.name + ' — towers held'"
                      [value]="entry.count"
                      icon="bi-flag-fill"
                      tone="info"
                    />
                  </div>
                }
                @if (replayOwnershipCounts().length === 0) {
                  <div class="col-12 small text-body-secondary">No tower captures recorded yet at this tick.</div>
                }
              </div>
            }

            @if (dementorsEnabled()) {
              <div class="card">
                <div class="card-body">
                  <h3 class="h6 mb-2">Roles</h3>
                  <div class="table-responsive">
                    <table class="table table-sm align-middle mb-0">
                      <thead>
                        <tr>
                          <th>Player</th>
                          <th>Team</th>
                          <th>Role</th>
                          <th class="text-end">Energy</th>
                        </tr>
                      </thead>
                      <tbody>
                        @for (p of displayPlayers(); track p.profile_id) {
                          <tr [class.table-secondary]="!p.alive">
                            <td>{{ p.username }}</td>
                            <td class="small text-body-secondary">{{ p.team_name ?? '—' }}</td>
                            <td>
                              @if (!p.alive) {
                                <span class="badge text-bg-secondary">Out</span>
                              } @else if (p.role === 'WIZARD') {
                                <span class="badge text-bg-primary">Wizard</span>
                              } @else if (p.role === 'DEMENTOR') {
                                <span class="badge text-bg-dark">Dementor</span>
                              } @else {
                                <span class="text-body-secondary">—</span>
                              }
                            </td>
                            <td class="text-end tabular-nums">{{ p.energy ?? '—' }}</td>
                          </tr>
                        }
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            }
          } @else {
            <div class="alert alert-info mb-0">Create or open a run above to drive it.</div>
          }
        </div>
      </div>
    </div>
  `,
  styles: `
    .sim-workspace {
      display: flex;
      flex-direction: column;
      gap: var(--space-4);
    }

    .sim-workspace__header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-3);
    }

    .sim-workspace__body {
      display: grid;
      grid-template-columns: 1fr;
      gap: var(--space-4);
      align-items: start;
    }

    @media (min-width: 768px) {
      .sim-workspace__body {
        grid-template-columns: minmax(0, 2fr) minmax(260px, 1fr);
      }
    }

    .sim-map {
      position: relative;
      height: 480px;
      border-radius: var(--radius);
      overflow: hidden;
      border: 1px solid var(--border);
      background: var(--panel-sunken);
    }

    .sim-map__empty {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: var(--space-2);
      color: var(--ink-muted);
      text-align: center;
      padding: var(--space-4);
    }

    .sim-map__empty i {
      font-size: var(--text-3xl);
    }

    .sim-legend__dot {
      display: inline-block;
      width: 0.6rem;
      height: 0.6rem;
      border-radius: 50%;
      margin-right: 0.25rem;
    }
  `,
})
export class SimulatorComponent {
  private readonly staffApi = inject(StaffApiService);
  private readonly confirmService = inject(ConfirmService);
  protected readonly realtime = inject(RealtimeService);
  private readonly fb = inject(FormBuilder);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly roleColor = ROLE_COLOR;
  protected readonly liveSpeedOptions = LIVE_SPEED_OPTIONS;
  protected readonly replaySpeedOptionsMs = REPLAY_SPEED_OPTIONS_MS;

  private readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');

  // ---- runs list -------------------------------------------------------
  protected readonly runs = signal<SimulationRun[]>([]);
  protected readonly runsLoading = signal(false);
  protected readonly runsError = signal<string | null>(null);

  // ---- template games ----------------------------------------------------
  protected readonly games = signal<AdminGame[]>([]);

  // ---- create-run form -----------------------------------------------------
  protected readonly createForm = this.fb.group({
    name: this.fb.control<string>('Simulation run'),
    templateGameId: this.fb.control<number | null>(null),
    gameName: this.fb.control<string>(''),
    nPlayers: this.fb.control<number | null>(8, [Validators.required, Validators.min(1)]),
    nTeams: this.fb.control<number | null>(2, [Validators.required, Validators.min(1)]),
    mode: this.fb.control<GameMode>('DOMINATION'),
    tickSeconds: this.fb.control<number | null>(5, [Validators.required, Validators.min(1)]),
    captureProbability: this.fb.control<number | null>(
      0.5,
      [Validators.required, Validators.min(0), Validators.max(1)],
    ),
    seed: this.fb.control<number | null>(0),
    centerLat: this.fb.control<number | null>(null),
    centerLng: this.fb.control<number | null>(null),
    radiusM: this.fb.control<number | null>(250, [Validators.required, Validators.min(10)]),
  });
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);

  // ---- active run / workspace -----------------------------------------------
  protected readonly activeRun = signal<SimulationRun | null>(null);
  protected readonly liveState = signal<SimulationState | null>(null);
  protected readonly workspaceMode = signal<WorkspaceMode>('live');
  protected readonly workspaceError = signal<string | null>(null);
  protected readonly workspaceLoading = signal(false);
  protected readonly canStep = computed(() => this.activeRun()?.status === 'RUNNING');
  protected readonly dementorsEnabled = computed(() =>
    Boolean(this.activeRun()?.config?.['dementors_enabled']),
  );

  // ---- live-drive controls ---------------------------------------------------
  protected readonly stepping = signal(false);
  protected readonly autoPlaying = signal(false);
  protected readonly liveSpeedMultiplier = signal<number>(1);
  private livePlayHandle: ReturnType<typeof setInterval> | null = null;

  // ---- replay -----------------------------------------------------------
  protected readonly timeline = signal<SimulationEvent[]>([]);
  protected readonly timelineLoading = signal(false);
  protected readonly replayFrames = signal<ReplayDisplayFrame[]>([]);
  protected readonly replayTick = signal(0);
  protected readonly replayPlaying = signal(false);
  protected readonly replaySpeedMs = signal<number>(500);
  private replayHandle: ReturnType<typeof setInterval> | null = null;

  protected readonly replayMaxTick = computed(() => Math.max(0, this.replayFrames().length - 1));
  protected readonly currentReplayFrame = computed<ReplayDisplayFrame | null>(() => {
    const frames = this.replayFrames();
    if (frames.length === 0) return null;
    return frames[Math.min(this.replayTick(), frames.length - 1)];
  });
  /** Towers held per team at the scrubbed tick — the one thing about
   *  "score" that's actually reconstructable client-side from the tape
   *  (true score accrues over time from zone control, not just captures). */
  protected readonly replayOwnershipCounts = computed(() => {
    const towers = this.currentReplayFrame()?.towers ?? [];
    const counts = new Map<number, { name: string; count: number }>();
    for (const t of towers) {
      if (t.owner_team_id === null) continue;
      const entry = counts.get(t.owner_team_id) ?? {
        name: t.owner_team_name ?? `Team ${t.owner_team_id}`,
        count: 0,
      };
      entry.count += 1;
      counts.set(t.owner_team_id, entry);
    }
    return Array.from(counts.entries()).map(([team_id, v]) => ({ team_id, ...v }));
  });

  /** What actually gets drawn on the map / roles table — unifies live vs replay. */
  protected readonly displayPlayers = computed<DisplayPlayer[]>(() => {
    if (this.workspaceMode() === 'replay') {
      return (this.currentReplayFrame()?.players ?? []).map((p) => ({ ...p, alive: true }));
    }
    return (this.liveState()?.players ?? []).map((p) => ({
      profile_id: p.profile_id,
      username: p.username,
      team_id: p.team_id,
      team_name: p.team_name,
      lat: p.lat,
      lng: p.lng,
      role: p.role,
      energy: p.energy,
      alive: p.alive,
    }));
  });
  protected readonly displayTowers = computed<SimTowerState[]>(() => {
    if (this.workspaceMode() === 'replay') {
      return this.currentReplayFrame()?.towers ?? [];
    }
    return this.liveState()?.towers ?? [];
  });

  private readonly teamColors = new TeamColorResolver();
  /** tower_id -> [lat, lng], fetched once per selected run (state() has no geometry). */
  private readonly towerLocations = new Map<number, [number, number]>();

  private map: L.Map | null = null;
  private towersLayer: L.LayerGroup | null = null;
  private playersLayer: L.LayerGroup | null = null;
  private seenConnections = 0;

  constructor() {
    this.loadRuns();
    this.staffApi.listGames().subscribe({ next: (list) => this.games.set(list), error: () => {} });

    afterNextRender(() => this.initMap());

    // Redraw the map whenever the derived live/replay display data changes.
    effect(() => {
      const players = this.displayPlayers();
      const towers = this.displayTowers();
      this.renderMap(players, towers);
    });

    this.realtime.events$
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((envelope) => this.applyRealtimeEvent(envelope));

    // After every (re)connect, reconcile from a fresh REST snapshot.
    effect(() => {
      const count = this.realtime.connections();
      if (count > this.seenConnections && this.seenConnections > 0) {
        this.refreshLiveState();
      }
      this.seenConnections = Math.max(this.seenConnections, count);
    });

    this.destroyRef.onDestroy(() => {
      this.stopLivePlay();
      this.stopReplayPlay();
      this.realtime.disconnect();
      this.map?.remove();
    });
  }

  // ---- map ---------------------------------------------------------------

  private initMap(): void {
    this.map = L.map(this.mapContainer().nativeElement).setView(FALLBACK_CENTER, FALLBACK_ZOOM);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);
    this.towersLayer = L.layerGroup().addTo(this.map);
    this.playersLayer = L.layerGroup().addTo(this.map);
    const run = this.activeRun();
    if (run) this.centerMapOn(run);
    this.renderMap(this.displayPlayers(), this.displayTowers());
  }

  private centerMapOn(run: SimulationRun): void {
    if (!this.map) return;
    const lat = run.config['center_lat'];
    const lng = run.config['center_lng'];
    if (typeof lat === 'number' && typeof lng === 'number') {
      this.map.setView([lat, lng], FALLBACK_ZOOM);
    }
  }

  private renderMap(players: DisplayPlayer[], towers: SimTowerState[]): void {
    if (!this.map || !this.towersLayer || !this.playersLayer) return;
    this.towersLayer.clearLayers();
    this.playersLayer.clearLayers();

    for (const tower of towers) {
      const loc = this.towerLocations.get(tower.id);
      if (!loc) continue;
      const color =
        tower.owner_team_id !== null ? this.teamColors.colorFor(tower.owner_team_id) : UNCLAIMED_COLOR;
      L.circleMarker(loc, {
        radius: 10,
        color: '#1E2A32',
        weight: 2,
        fillColor: color,
        fillOpacity: tower.owner_team_id !== null ? 0.9 : 0.25,
      })
        .bindTooltip(`${tower.name} · ${tower.owner_team_name ?? 'unclaimed'}`)
        .addTo(this.towersLayer);
    }

    const dementors = this.dementorsEnabled();
    for (const player of players) {
      let fillColor: string;
      let label: string;
      if (dementors) {
        fillColor =
          player.role === 'DEMENTOR'
            ? ROLE_COLOR.DEMENTOR
            : player.role === 'WIZARD'
              ? ROLE_COLOR.WIZARD
              : ROLE_COLOR.UNKNOWN;
        const energyLabel = player.energy !== null ? ` · ${player.energy} energy` : '';
        label = `${player.username} · ${player.role || 'unassigned'}${energyLabel}`;
      } else {
        fillColor = this.teamColors.colorFor(player.team_id);
        label = `${player.username}${player.team_name ? ' · ' + player.team_name : ''}`;
      }
      L.circleMarker([player.lat, player.lng], {
        radius: 6,
        color: '#fff',
        weight: 1.5,
        fillColor,
        fillOpacity: player.alive ? 0.95 : 0.3,
      })
        .bindTooltip(label)
        .addTo(this.playersLayer);
    }
  }

  private loadTowerLocations(): void {
    this.staffApi.listTowers().subscribe({
      next: (towers) => {
        this.towerLocations.clear();
        for (const t of towers) {
          if (t.location) {
            const [lng, lat] = t.location.coordinates;
            this.towerLocations.set(t.id, [lat, lng]);
          }
        }
        this.renderMap(this.displayPlayers(), this.displayTowers());
      },
      error: () => {},
    });
  }

  // ---- runs list -----------------------------------------------------------

  protected loadRuns(): void {
    this.runsLoading.set(true);
    this.staffApi.listSimulationRuns().subscribe({
      next: (runs) => {
        this.runs.set(runs);
        this.runsLoading.set(false);
        this.runsError.set(null);
      },
      error: (err) => {
        this.runsLoading.set(false);
        this.runsError.set(extractErrorMessage(err));
      },
    });
  }


  // ---- create run ------------------------------------------------------------

  protected fieldError(
    name: 'nPlayers' | 'nTeams' | 'tickSeconds' | 'captureProbability' | 'radiusM',
  ): string | undefined {
    const control = this.createForm.controls[name];
    if (!control.touched || control.valid) return undefined;
    if (control.hasError('required')) return 'Required.';
    if (control.hasError('min')) return `Must be at least ${control.getError('min').min}.`;
    if (control.hasError('max')) return `Must be at most ${control.getError('max').max}.`;
    return 'Invalid value.';
  }

  protected createRun(): void {
    if (this.createForm.invalid || this.creating()) return;
    this.creating.set(true);
    this.createError.set(null);
    const v = this.createForm.getRawValue();

    const payload: CreateSimulationRunPayload = {
      name: v.name?.trim() || 'Simulation run',
      n_players: v.nPlayers ?? 8,
      n_teams: v.nTeams ?? 2,
      mode: v.mode ?? 'DOMINATION',
      dementors_enabled: v.mode === 'DEMENTORS',
      tick_seconds: v.tickSeconds ?? 5,
      capture_probability: v.captureProbability ?? 0.5,
      radius_m: v.radiusM ?? 250,
    };
    if (v.seed !== null && v.seed !== undefined) payload.seed = v.seed;
    if (v.templateGameId !== null && v.templateGameId !== undefined) {
      payload.template_game_id = v.templateGameId;
    } else if (v.gameName?.trim()) {
      payload.game_name = v.gameName.trim();
    }
    if (v.centerLat !== null && v.centerLat !== undefined) payload.center_lat = v.centerLat;
    if (v.centerLng !== null && v.centerLng !== undefined) payload.center_lng = v.centerLng;

    this.staffApi.createSimulationRun(payload).subscribe({
      next: (run) => {
        this.creating.set(false);
        this.runs.update((list) => [run, ...list]);
        this.selectRun(run);
      },
      error: (err) => {
        this.creating.set(false);
        this.createError.set(extractErrorMessage(err));
      },
    });
  }

  // ---- selecting / closing a run -------------------------------------------

  protected selectRun(run: SimulationRun): void {
    this.stopLivePlay();
    this.stopReplayPlay();
    this.workspaceError.set(null);
    this.workspaceMode.set('live');
    this.timeline.set([]);
    this.replayFrames.set([]);
    this.replayTick.set(0);
    this.activeRun.set(run);
    this.workspaceLoading.set(true);
    this.realtime.disconnect();

    this.staffApi.getSimulationRun(run.id).subscribe({
      next: (detail) => {
        this.activeRun.set(detail);
        this.liveState.set(detail.state);
        this.workspaceLoading.set(false);
        this.centerMapOn(detail);
        this.loadTowerLocations();
        if (detail.session !== null) {
          this.realtime.connect(detail.session, true);
        }
      },
      error: (err) => {
        this.workspaceLoading.set(false);
        this.workspaceError.set(extractErrorMessage(err));
      },
    });
  }

  protected closeWorkspace(): void {
    this.stopLivePlay();
    this.stopReplayPlay();
    this.realtime.disconnect();
    this.activeRun.set(null);
    this.liveState.set(null);
    this.timeline.set([]);
    this.replayFrames.set([]);
    this.workspaceError.set(null);
  }

  private refreshLiveState(): void {
    const run = this.activeRun();
    if (!run) return;
    this.staffApi.getSimulationRun(run.id).subscribe({
      next: (detail) => {
        this.activeRun.set(detail);
        this.liveState.set(detail.state);
      },
      error: () => {},
    });
  }

  // ---- live-drive controls ---------------------------------------------------

  protected step(): void {
    const run = this.activeRun();
    if (!run || this.stepping()) return;
    this.stepping.set(true);
    this.staffApi.stepSimulation(run.id, 1).subscribe({
      next: (state) => {
        this.stepping.set(false);
        this.liveState.set(state);
        this.activeRun.update((r) =>
          r ? { ...r, status: state.status, tick_count: state.tick_count } : r,
        );
        this.workspaceError.set(null);
      },
      error: (err) => {
        this.stepping.set(false);
        this.workspaceError.set(extractErrorMessage(err));
        this.stopLivePlay();
      },
    });
  }

  protected toggleLivePlay(): void {
    if (this.autoPlaying()) {
      this.stopLivePlay();
      return;
    }
    const run = this.activeRun();
    if (!run) return;
    this.autoPlaying.set(true);
    const tickSeconds = Number(run.config['tick_seconds'] ?? 5) || 5;
    const intervalMs = Math.max(200, (tickSeconds * 1000) / this.liveSpeedMultiplier());
    this.livePlayHandle = setInterval(() => this.step(), intervalMs);
  }

  protected stopLivePlay(): void {
    this.autoPlaying.set(false);
    if (this.livePlayHandle) {
      clearInterval(this.livePlayHandle);
      this.livePlayHandle = null;
    }
  }

  protected setLiveSpeed(multiplier: number): void {
    this.liveSpeedMultiplier.set(multiplier);
    if (this.autoPlaying()) {
      this.stopLivePlay();
      this.toggleLivePlay();
    }
  }

  protected pauseRun(): void {
    const run = this.activeRun();
    if (!run) return;
    this.stopLivePlay();
    this.staffApi.pauseSimulation(run.id).subscribe({
      next: (updated) => {
        this.activeRun.set(updated);
        this.workspaceError.set(null);
      },
      error: (err) => this.workspaceError.set(extractErrorMessage(err)),
    });
  }

  protected stopRun(): void {
    const run = this.activeRun();
    if (!run) return;
    this.stopLivePlay();
    this.staffApi.stopSimulation(run.id).subscribe({
      next: (updated) => {
        this.activeRun.set(updated);
        this.workspaceError.set(null);
        this.loadRuns();
      },
      error: (err) => this.workspaceError.set(extractErrorMessage(err)),
    });
  }

  protected async teardownRun(run: SimulationRun): Promise<void> {
    const ok = await this.confirmService.confirm({
      title: 'Delete this run?',
      message:
        `This permanently deletes "${run.name}"'s simulated Game/Session and every fake ` +
        'player it created. This cannot be undone.',
      danger: true,
      confirmLabel: 'Delete run',
      requireTyping: run.name,
    });
    if (!ok) return;
    this.staffApi.deleteSimulationRun(run.id).subscribe({
      next: () => {
        this.runs.update((list) => list.filter((r) => r.id !== run.id));
        if (this.activeRun()?.id === run.id) this.closeWorkspace();
      },
      error: (err) => this.runsError.set(extractErrorMessage(err)),
    });
  }

  // ---- replay ------------------------------------------------------------

  protected switchMode(mode: WorkspaceMode): void {
    if (this.workspaceMode() === mode) return;
    this.stopLivePlay();
    this.stopReplayPlay();
    this.workspaceMode.set(mode);
    if (mode === 'replay' && this.timeline().length === 0) {
      this.loadTimeline();
    }
  }

  private loadTimeline(): void {
    const run = this.activeRun();
    if (!run) return;
    this.timelineLoading.set(true);
    this.staffApi.simulationTimeline(run.id).subscribe({
      next: (events) => {
        this.timeline.set(events);
        const baselinePlayers: SimPlayer[] = this.liveState()?.players ?? [];
        const baselineTowers: SimTowerState[] = this.liveState()?.towers ?? [];
        const frames = buildReplayFrames(events, baselinePlayers, baselineTowers);
        this.replayFrames.set(frames);
        this.replayTick.set(frames.length ? frames.length - 1 : 0);
        this.timelineLoading.set(false);
      },
      error: (err) => {
        this.timelineLoading.set(false);
        this.workspaceError.set(extractErrorMessage(err));
      },
    });
  }

  protected onScrub(tick: number): void {
    this.replayTick.set(Math.min(Math.max(0, tick), this.replayMaxTick()));
  }

  protected toggleReplayPlay(): void {
    if (this.replayPlaying()) {
      this.stopReplayPlay();
      return;
    }
    if (this.replayTick() >= this.replayMaxTick()) this.replayTick.set(0);
    this.replayPlaying.set(true);
    this.replayHandle = setInterval(() => {
      const next = this.replayTick() + 1;
      if (next > this.replayMaxTick()) {
        this.stopReplayPlay();
        return;
      }
      this.replayTick.set(next);
    }, this.replaySpeedMs());
  }

  protected stopReplayPlay(): void {
    this.replayPlaying.set(false);
    if (this.replayHandle) {
      clearInterval(this.replayHandle);
      this.replayHandle = null;
    }
  }

  protected setReplaySpeed(ms: number): void {
    this.replaySpeedMs.set(ms);
    if (this.replayPlaying()) {
      this.stopReplayPlay();
      this.toggleReplayPlay();
    }
  }

  // ---- realtime ------------------------------------------------------------

  private applyRealtimeEvent(envelope: RealtimeEnvelope): void {
    const run = this.activeRun();
    if (!run || envelope.session !== run.session) return;
    switch (envelope.type) {
      case REALTIME_EVENTS.scoreboardUpdated: {
        const payload = envelope.payload as ScoreboardUpdatedPayload;
        for (const entry of payload.entries) this.teamColors.learn(entry.team_id, entry.team_color);
        this.liveState.update((state) => {
          if (!state) return state;
          const byId = new Map(payload.entries.map((e) => [e.team_id, e]));
          const scoreboard = state.scoreboard.map((s) => {
            const match = byId.get(s.team_id);
            return match ? { ...s, score: match.current_score, name: match.team_name } : s;
          });
          return { ...state, scoreboard };
        });
        break;
      }
      case REALTIME_EVENTS.towerOwnershipChanged: {
        const payload = envelope.payload as TowerOwnershipChangedPayload;
        if (payload.team) this.teamColors.learn(payload.team.team_id, payload.team.team_color);
        this.liveState.update((state) => {
          if (!state) return state;
          const towers = state.towers.map((t) =>
            t.id === payload.tower_id
              ? {
                  ...t,
                  owner_team_id: payload.team?.team_id ?? null,
                  owner_team_name: payload.team?.team_name ?? null,
                }
              : t,
          );
          return { ...state, towers };
        });
        break;
      }
      case REALTIME_EVENTS.dementorTick: {
        const payload = envelope.payload as DementorTickPayload;
        this.liveState.update((state) => {
          if (!state) return state;
          const live = new Map(payload.players.map((p) => [p.player_id, p]));
          const players = state.players.map((p) => {
            const match = live.get(p.profile_id);
            return match
              ? { ...p, role: match.role, energy: match.energy, alive: match.alive }
              : p;
          });
          return { ...state, players };
        });
        break;
      }
      case REALTIME_EVENTS.sessionStateChanged: {
        this.refreshLiveState();
        break;
      }
      default:
        break;
    }
  }
}
