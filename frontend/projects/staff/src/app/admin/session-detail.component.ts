import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import {
  AdminSession,
  AdminSessionPayload,
  FailCounterInfo,
  FailCounterReset,
  GameApiService,
  PauseHistory,
  Phase10Overrides,
  SessionScoreboard,
  SessionTimeline,
  StaffApiService,
  TeamBuildResult,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

const OVERRIDE_FIELDS: (keyof Phase10Overrides)[] = [
  'pause_freezes_floating_score',
  'pause_restores_ownerships_on_resume',
  'pause_rejects_submissions',
  'fail_point_penalty',
  'fail_cooloff_scaling',
  'fail_tower_lockout_minutes',
  'fail_difficulty_rollback',
  'fail_counter_reset',
];

@Component({
  selector: 'app-staff-session-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FormsModule, RouterLink],
  template: `
    <a routerLink="/sessions" class="small text-body-secondary">
      &larr; Back to sessions
    </a>

    @if (loadError(); as msg) {
      <div class="alert alert-danger mt-3">{{ msg }}</div>
    } @else if (scoreboard(); as sb) {
      <h1 class="h3 mt-2 mb-1">
        {{ sb.session.name }}
        @if (session()?.is_paused) {
          <span class="badge text-bg-warning ms-2">Paused</span>
        }
      </h1>
      <div class="text-body-secondary small mb-3">
        {{ sb.session.game.name }} · <code>{{ sb.session.slug }}</code>
        @if (!sb.session.is_active) {
          <span class="badge text-bg-secondary ms-2">Past</span>
        } @else {
          <span class="badge text-bg-success ms-2">Active</span>
        }
      </div>

      <!-- Day pausing ------------------------------------------------------ -->
      <div class="card mb-4">
        <div class="card-body">
          <div class="d-flex justify-content-between align-items-center">
            <h2 class="h6 mb-0">Day pausing</h2>
            @if (session(); as s) {
              @if (s.is_paused) {
                <button
                  type="button"
                  class="btn btn-sm btn-success"
                  [disabled]="pauseBusy()"
                  (click)="resume()"
                >
                  @if (pauseBusy()) {
                    <span class="spinner-border spinner-border-sm me-1"></span>
                  }
                  Resume
                </button>
              } @else {
                <button
                  type="button"
                  class="btn btn-sm btn-warning"
                  [disabled]="pauseBusy() || !s.is_active"
                  (click)="pause()"
                >
                  @if (pauseBusy()) {
                    <span class="spinner-border spinner-border-sm me-1"></span>
                  }
                  Pause
                </button>
              }
            }
          </div>
          @if (pauseError(); as msg) {
            <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
          }
          @if (pauseHistory(); as ph) {
            @if (ph.windows.length === 0) {
              <p class="text-body-secondary small mb-0 mt-2">No pauses yet.</p>
            } @else {
              <div class="table-responsive mt-2">
                <table class="table table-sm mb-0">
                  <thead>
                    <tr><th>Started</th><th>Ended</th><th>Restores on resume</th></tr>
                  </thead>
                  <tbody>
                    @for (w of ph.windows; track w.id) {
                      <tr>
                        <td class="small">{{ w.started_at | date: 'medium' }}</td>
                        <td class="small">
                          @if (w.ended_at; as e) {
                            {{ e | date: 'medium' }}
                          } @else {
                            <span class="badge text-bg-warning">open</span>
                          }
                        </td>
                        <td class="small">{{ w.restore_on_resume ? 'yes' : 'no' }}</td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
          }
        </div>
      </div>

      <!-- Scoreboard ------------------------------------------------------- -->
      <h2 class="h5 mt-4 mb-2">Scoreboard</h2>
      <div class="table-responsive">
        <table class="table">
          <thead>
            <tr>
              <th style="width: 3rem">#</th>
              <th>Team</th>
              <th>Group</th>
              <th class="text-end">Locked</th>
              <th class="text-end">Floating</th>
              <th class="text-end">Score</th>
            </tr>
          </thead>
          <tbody>
            @for (e of sb.entries; track e.team_id; let i = $index) {
              <tr>
                <td class="fw-semibold">{{ i + 1 }}</td>
                <td>
                  <span
                    class="d-inline-block me-2"
                    style="width: 0.9rem; height: 0.9rem; border-radius: 50%; vertical-align: middle"
                    [style.background-color]="e.team_color"
                  ></span>
                  <span class="fw-semibold">{{ e.team_name }}</span>
                </td>
                <td class="small text-body-secondary">
                  {{ e.group_name || '—' }}
                </td>
                <td class="text-end">{{ e.locked_score }}</td>
                <td class="text-end">{{ e.floating_score }}</td>
                <td class="text-end fw-semibold">{{ e.current_score }}</td>
              </tr>
            }
          </tbody>
        </table>
      </div>

      <!-- Failure lockouts ------------------------------------------------- -->
      <h2 class="h5 mt-4 mb-2">Failure lockouts &amp; consecutive fails</h2>
      @if (failCounters().length === 0) {
        <div class="alert alert-info">No active fail counters.</div>
      } @else {
        <div class="table-responsive">
          <table class="table">
            <thead>
              <tr>
                <th>Team</th>
                <th>Tower</th>
                <th class="text-end">Consecutive fails</th>
                <th>Locked until</th>
              </tr>
            </thead>
            <tbody>
              @for (c of failCounters(); track c.team_id + '-' + c.tower_id) {
                <tr>
                  <td>
                    <span
                      class="d-inline-block me-2"
                      style="width: 0.8rem; height: 0.8rem; border-radius: 50%; vertical-align: middle"
                      [style.background-color]="c.team_color"
                    ></span>
                    {{ c.team_name }}
                  </td>
                  <td>{{ c.tower_name }}</td>
                  <td class="text-end fw-semibold">{{ c.consecutive_fails }}</td>
                  <td class="small">
                    @if (c.is_locked && c.locked_until) {
                      <span class="badge text-bg-danger me-1">locked</span>
                      {{ c.locked_until | date: 'medium' }}
                    } @else {
                      <span class="text-body-secondary">—</span>
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }

      <!-- Per-session overrides -------------------------------------------- -->
      @if (session(); as s) {
        <h2 class="h5 mt-4 mb-2">Rule overrides</h2>
        <p class="text-body-secondary small">
          Leave a field on <em>Inherit</em> (or blank) to use the Game default.
        </p>
        <div class="row g-3">
          <div class="col-md-6">
            @for (b of boolOverrides; track b.field) {
              <div class="mb-2">
                <label class="form-label small mb-0">{{ b.label }}</label>
                <select
                  class="form-select form-select-sm"
                  [ngModel]="override()[b.field]"
                  (ngModelChange)="setOverride(b.field, $event)"
                >
                  <option [ngValue]="null">Inherit</option>
                  <option [ngValue]="true">On</option>
                  <option [ngValue]="false">Off</option>
                </select>
              </div>
            }
            <div class="mb-2">
              <label class="form-label small mb-0">Players may create teams</label>
              <select
                class="form-select form-select-sm"
                [ngModel]="teamFormationOverride()"
                (ngModelChange)="setTeamFormationOverride($event)"
              >
                <option [ngValue]="null">Inherit</option>
                <option [ngValue]="true">On</option>
                <option [ngValue]="false">Off</option>
              </select>
            </div>
          </div>
          <div class="col-md-6">
            @for (n of numOverrides; track n.field) {
              <div class="mb-2">
                <label class="form-label small mb-0">{{ n.label }}</label>
                <input
                  class="form-control form-control-sm"
                  type="number"
                  [step]="n.step"
                  [ngModel]="override()[n.field]"
                  (ngModelChange)="setOverride(n.field, $event)"
                  placeholder="Inherit"
                />
              </div>
            }
            <div class="mb-2">
              <label class="form-label small mb-0">Counter reset</label>
              <select
                class="form-select form-select-sm"
                [ngModel]="override().fail_counter_reset"
                (ngModelChange)="setOverride('fail_counter_reset', $event)"
              >
                <option [ngValue]="null">Inherit</option>
                @for (o of resetOptions; track o.value) {
                  <option [ngValue]="o.value">{{ o.label }}</option>
                }
              </select>
            </div>
          </div>
        </div>
        <button
          type="button"
          class="btn btn-primary btn-sm mt-2"
          [disabled]="!overrideDirty() || overrideSaving()"
          (click)="saveOverrides(s.id)"
        >
          @if (overrideSaving()) {
            <span class="spinner-border spinner-border-sm me-1"></span>
          }
          Save overrides
        </button>
        @if (overrideError(); as msg) {
          <div class="small text-danger mt-1">{{ msg }}</div>
        }
      }

      <!-- Team building (shuffle / balance) -------------------------------- -->
      <h2 class="h5 mt-4 mb-2">Team building</h2>
      <div class="card mb-4">
        <div class="card-body">
          <p class="text-body-secondary small">
            Distribute unassigned players (players in this session without a
            team) into new teams. Best-effort — edit the result on the
            <a routerLink="/teams">Teams</a> page before the session starts.
          </p>
          <div class="row g-2 align-items-end">
            <div class="col-auto">
              <label class="form-label small mb-0" for="team-count">Number of teams</label>
              <input
                id="team-count"
                class="form-control form-control-sm"
                type="number"
                min="1"
                [ngModel]="buildCount()"
                (ngModelChange)="buildCount.set($event)"
              />
            </div>
            <div class="col-auto">
              <button
                type="button"
                class="btn btn-sm btn-outline-primary"
                [disabled]="buildBusy() || !buildCount()"
                (click)="shuffleTeams()"
              >
                <i class="bi bi-shuffle"></i> Random shuffle
              </button>
            </div>
            <div class="col-auto">
              <label class="form-label small mb-0" for="balance-keys">
                Balance by attribute keys (comma-separated)
              </label>
              <input
                id="balance-keys"
                class="form-control form-control-sm"
                type="text"
                placeholder="e.g. age_group, experience"
                [ngModel]="buildKeys()"
                (ngModelChange)="buildKeys.set($event)"
              />
            </div>
            <div class="col-auto">
              <button
                type="button"
                class="btn btn-sm btn-outline-primary"
                [disabled]="buildBusy() || !buildCount() || !buildKeys().trim()"
                (click)="balanceTeams()"
              >
                <i class="bi bi-sliders"></i> Balanced build
              </button>
            </div>
          </div>
          @if (buildError(); as msg) {
            <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
          }
          @if (buildResult(); as res) {
            <div class="alert alert-success py-2 mt-2 mb-2">
              Assigned {{ res.assigned }} player(s) into {{ res.teams.length }} team(s).
            </div>
            <ul class="list-group">
              @for (t of res.teams; track t.id) {
                <li class="list-group-item py-1 small">
                  <span class="fw-semibold">{{ t.name }}</span>:
                  {{ t.members.join(', ') || '—' }}
                </li>
              }
            </ul>
          }
        </div>
      </div>

      <!-- Ownership timeline ----------------------------------------------- -->
      <h2 class="h5 mt-4 mb-2">Ownership timeline</h2>
      @if (timeline(); as tl) {
        @if (tl.events.length === 0) {
          <div class="alert alert-info">No tower captures recorded.</div>
        } @else {
          <div class="table-responsive">
            <table class="table">
              <thead>
                <tr>
                  <th>Team</th>
                  <th>Tower</th>
                  <th>Captured</th>
                  <th>Released</th>
                </tr>
              </thead>
              <tbody>
                @for (ev of tl.events; track ev.id) {
                  <tr>
                    <td>
                      <span
                        class="d-inline-block me-2"
                        style="width: 0.8rem; height: 0.8rem; border-radius: 50%; vertical-align: middle"
                        [style.background-color]="ev.team_color"
                      ></span>
                      {{ ev.team_name }}
                    </td>
                    <td>{{ ev.tower_name }}</td>
                    <td class="small text-body-secondary">
                      {{ ev.timestamp_start | date: 'medium' }}
                    </td>
                    <td class="small text-body-secondary">
                      @if (ev.timestamp_end; as ended) {
                        {{ ended | date: 'medium' }}
                      } @else {
                        <em>still held</em>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      }
    } @else {
      <div class="d-flex align-items-center text-body-secondary mt-3">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading session…
      </div>
    }
  `,
})
export class StaffSessionDetailComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(GameApiService);
  private readonly staff = inject(StaffApiService);

  protected readonly scoreboard = signal<SessionScoreboard | null>(null);
  protected readonly timeline = signal<SessionTimeline | null>(null);
  protected readonly session = signal<AdminSession | null>(null);
  protected readonly pauseHistory = signal<PauseHistory | null>(null);
  protected readonly failCounters = signal<FailCounterInfo[]>([]);
  protected readonly loadError = signal<string | null>(null);

  protected readonly pauseBusy = signal(false);
  protected readonly pauseError = signal<string | null>(null);

  protected readonly override = signal<Phase10Overrides>(blankOverrides());
  protected readonly teamFormationOverride = signal<boolean | null>(null);

  protected readonly buildCount = signal<number | null>(null);
  protected readonly buildKeys = signal('');
  protected readonly buildBusy = signal(false);
  protected readonly buildError = signal<string | null>(null);
  protected readonly buildResult = signal<TeamBuildResult | null>(null);
  protected readonly overrideDirty = signal(false);
  protected readonly overrideSaving = signal(false);
  protected readonly overrideError = signal<string | null>(null);

  protected readonly boolOverrides: { field: keyof Phase10Overrides; label: string }[] = [
    { field: 'pause_freezes_floating_score', label: 'Freeze floating score while paused' },
    { field: 'pause_restores_ownerships_on_resume', label: 'Restore ownerships on resume' },
    { field: 'pause_rejects_submissions', label: 'Reject submissions while paused' },
    { field: 'fail_difficulty_rollback', label: 'Difficulty rollback after failure' },
  ];

  protected readonly numOverrides: { field: keyof Phase10Overrides; label: string; step: number }[] = [
    { field: 'fail_point_penalty', label: 'Point penalty', step: 1 },
    { field: 'fail_cooloff_scaling', label: 'Cooloff scaling (≥1)', step: 0.1 },
    { field: 'fail_tower_lockout_minutes', label: 'Tower lockout (min)', step: 1 },
  ];

  protected readonly resetOptions: { value: FailCounterReset; label: string }[] = [
    { value: 'TOWER_SUCCESS_ONLY', label: 'Reset only on success at the same tower' },
    { value: 'ANY_SUCCESS_ELSEWHERE', label: 'Reset on any confirmed submission' },
    { value: 'ANY_ATTEMPT_ELSEWHERE', label: 'Reset on any submission anywhere' },
  ];

  private readonly sessionId = Number(this.route.snapshot.paramMap.get('id'));

  constructor() {
    if (!this.sessionId) {
      this.loadError.set('Invalid session.');
      return;
    }
    forkJoin({
      scoreboard: this.api.sessionScoreboard(this.sessionId),
      timeline: this.api.sessionTimeline(this.sessionId),
      session: this.staff.getSession(this.sessionId),
      pauseHistory: this.staff.sessionPauseHistory(this.sessionId),
      failCounters: this.staff.sessionFailCounters(this.sessionId),
    }).subscribe({
      next: (r) => {
        this.scoreboard.set(r.scoreboard);
        this.timeline.set(r.timeline);
        this.setSession(r.session);
        this.pauseHistory.set(r.pauseHistory);
        this.failCounters.set(r.failCounters);
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  private setSession(s: AdminSession): void {
    this.session.set(s);
    this.override.set(pickOverrides(s));
    this.teamFormationOverride.set(s.allow_player_team_creation);
    this.overrideDirty.set(false);
  }

  protected pause(): void {
    this.runPause(this.staff.pauseSession(this.sessionId));
  }

  protected resume(): void {
    this.runPause(this.staff.resumeSession(this.sessionId));
  }

  private runPause(call: ReturnType<StaffApiService['pauseSession']>): void {
    this.pauseBusy.set(true);
    this.pauseError.set(null);
    call.subscribe({
      next: (s) => {
        this.setSession(s);
        this.reloadState();
      },
      error: (err) => {
        this.pauseBusy.set(false);
        this.pauseError.set(extractErrorMessage(err));
      },
    });
  }

  private reloadState(): void {
    forkJoin({
      scoreboard: this.api.sessionScoreboard(this.sessionId),
      timeline: this.api.sessionTimeline(this.sessionId),
      pauseHistory: this.staff.sessionPauseHistory(this.sessionId),
      failCounters: this.staff.sessionFailCounters(this.sessionId),
    }).subscribe({
      next: (r) => {
        this.scoreboard.set(r.scoreboard);
        this.timeline.set(r.timeline);
        this.pauseHistory.set(r.pauseHistory);
        this.failCounters.set(r.failCounters);
        this.pauseBusy.set(false);
      },
      error: (err) => {
        this.pauseBusy.set(false);
        this.pauseError.set(extractErrorMessage(err));
      },
    });
  }

  protected setOverride<K extends keyof Phase10Overrides>(
    field: K,
    value: Phase10Overrides[K],
  ): void {
    this.override.update((o) => ({ ...o, [field]: value }));
    this.overrideDirty.set(true);
  }

  protected setTeamFormationOverride(value: boolean | null): void {
    this.teamFormationOverride.set(value);
    this.overrideDirty.set(true);
  }

  protected shuffleTeams(): void {
    this.runBuild(this.staff.shuffleTeams(this.sessionId, this.buildCount() ?? 0));
  }

  protected balanceTeams(): void {
    const keys = this.buildKeys()
      .split(',')
      .map((k) => k.trim())
      .filter((k) => k.length > 0);
    this.runBuild(this.staff.balanceTeams(this.sessionId, this.buildCount() ?? 0, keys));
  }

  private runBuild(call: ReturnType<StaffApiService['shuffleTeams']>): void {
    this.buildBusy.set(true);
    this.buildError.set(null);
    this.buildResult.set(null);
    call.subscribe({
      next: (res) => {
        this.buildBusy.set(false);
        this.buildResult.set(res);
        this.reloadState();
      },
      error: (err) => {
        this.buildBusy.set(false);
        this.buildError.set(extractErrorMessage(err));
      },
    });
  }

  protected saveOverrides(id: number): void {
    if (!this.overrideDirty() || this.overrideSaving()) return;
    this.overrideSaving.set(true);
    this.overrideError.set(null);
    const payload: AdminSessionPayload = {
      ...this.override(),
      allow_player_team_creation: this.teamFormationOverride(),
    };
    this.staff.updateSession(id, payload).subscribe({
      next: (s) => {
        this.overrideSaving.set(false);
        this.setSession(s);
      },
      error: (err) => {
        this.overrideSaving.set(false);
        this.overrideError.set(extractErrorMessage(err));
      },
    });
  }
}

function blankOverrides(): Phase10Overrides {
  return {
    pause_freezes_floating_score: null,
    pause_restores_ownerships_on_resume: null,
    pause_rejects_submissions: null,
    fail_point_penalty: null,
    fail_cooloff_scaling: null,
    fail_tower_lockout_minutes: null,
    fail_difficulty_rollback: null,
    fail_counter_reset: null,
  };
}

function pickOverrides(s: AdminSession): Phase10Overrides {
  const out = blankOverrides();
  for (const field of OVERRIDE_FIELDS) {
    (out[field] as Phase10Overrides[typeof field]) = s[field];
  }
  return out;
}
