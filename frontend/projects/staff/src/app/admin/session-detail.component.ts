import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { HttpErrorResponse } from '@angular/common/http';

import {
  AdminSession,
  AdminSessionPayload,
  FailCounterInfo,
  FailCounterReset,
  GameApiService,
  PauseHistory,
  Phase10Overrides,
  SessionScoreboard,
  SessionState,
  SessionTimeline,
  SessionTransitionAction,
  StaffApiService,
  StartReadiness,
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
        @if (session(); as s) {
          <span class="badge ms-2" [class]="stateBadgeClass(s.state)">
            {{ stateLabel(s.state) }}
          </span>
        }
      </h1>
      <div class="text-body-secondary small mb-3">
        {{ sb.session.game.name }} · <code>{{ sb.session.slug }}</code>
        @if (session()?.scheduled_start; as scheduled) {
          · <i class="bi bi-clock"></i>
          scheduled start {{ scheduled | date: 'medium' }}
        }
      </div>

      <!-- Lifecycle -------------------------------------------------------- -->
      @if (session(); as s) {
        <div class="card mb-4">
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
              <h2 class="h6 mb-0">
                Lifecycle
                <span class="badge ms-2" [class]="stateBadgeClass(s.state)">
                  {{ stateLabel(s.state) }}
                </span>
              </h2>
              <div class="d-flex gap-2 flex-wrap">
                @for (a of s.allowed_transitions; track a) {
                  <button
                    type="button"
                    class="btn btn-sm"
                    [class]="actionButtonClass(a)"
                    [disabled]="lifecycleBusy()"
                    (click)="transition(a)"
                  >
                    @if (lifecycleBusy()) {
                      <span class="spinner-border spinner-border-sm me-1"></span>
                    }
                    {{ actionLabel(a) }}
                  </button>
                }
                @if (s.state === 'DRAFT') {
                  <button
                    type="button"
                    class="btn btn-sm btn-success"
                    [disabled]="lifecycleBusy()"
                    (click)="openAndStart()"
                  >
                    @if (lifecycleBusy()) {
                      <span class="spinner-border spinner-border-sm me-1"></span>
                    }
                    Open &amp; start
                  </button>
                }
                @if (s.state === 'FINISHED') {
                  <span class="text-body-secondary small align-self-center">
                    Finished sessions are terminal.
                  </span>
                }
              </div>
            </div>
            <p class="text-body-secondary small mb-0 mt-2">
              DRAFT → OPEN_FOR_PARTICIPANTS → RUNNING ⇄ PAUSED → FINISHED.
              Rosters form while participation is open; finishing closes all
              ownerships and keeps history.
            </p>
            @if (lifecycleError(); as msg) {
              <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
            }
          </div>
        </div>
      }

      <!-- Start readiness (team rules; read-only — starting goes through the
           lifecycle transitions above, which enforce these blockers) -------- -->
      @if (readiness(); as r) {
        <div class="card mb-4">
          <div class="card-body">
            <h2 class="h6 mb-0">
              Start readiness
              @if (r.can_start) {
                <span class="badge text-bg-success ms-2">Ready to start</span>
              } @else {
                <span class="badge text-bg-warning ms-2">Blocked</span>
              }
            </h2>
            @if (r.blockers.length > 0) {
              <ul class="small text-danger mt-2 mb-2">
                @for (b of r.blockers; track $index) {
                  <li>{{ b.message }}</li>
                }
              </ul>
            }
            @if (r.teams.length === 0) {
              <p class="text-body-secondary small mb-0 mt-2">No teams yet.</p>
            } @else {
              <div class="table-responsive mt-2">
                <table class="table table-sm mb-0">
                  <thead>
                    <tr>
                      <th>Team</th>
                      <th class="text-end">Members</th>
                      <th class="text-end">Required</th>
                      <th>Readiness</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (t of r.teams; track t.id) {
                      <tr>
                        <td>
                          <span
                            class="d-inline-block me-2"
                            style="width: 0.8rem; height: 0.8rem; border-radius: 50%; vertical-align: middle"
                            [style.background-color]="t.color"
                          ></span>
                          {{ t.name }}
                        </td>
                        <td class="text-end">{{ t.active_member_count }}</td>
                        <td class="text-end">{{ r.min_members_per_team }}</td>
                        <td>
                          @if (t.is_ready) {
                            <span class="badge text-bg-success">ready</span>
                          } @else if (t.members_needed > 0) {
                            <span class="badge text-bg-warning">
                              needs {{ t.members_needed }} more
                            </span>
                          } @else {
                            <span class="badge text-bg-danger">over the cap</span>
                          }
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
          </div>
        </div>
      }

      <!-- Day pausing ------------------------------------------------------ -->
      <div class="card mb-4">
        <div class="card-body">
          <h2 class="h6 mb-0">Pause history</h2>
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

  protected readonly lifecycleBusy = signal(false);
  protected readonly lifecycleError = signal<string | null>(null);

  // Start readiness (team rules) — read-only; the lifecycle `start`
  // transition enforces these blockers server-side.
  protected readonly readiness = signal<StartReadiness | null>(null);

  protected readonly override = signal<Phase10Overrides>(blankOverrides());
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
    this.overrideDirty.set(false);
    this.refreshReadiness();
  }

  private refreshReadiness(): void {
    this.staff.sessionStartBlockers(this.sessionId).subscribe({
      next: (r) => this.readiness.set(r),
      error: () => this.readiness.set(null),
    });
  }

  // ---- Lifecycle controls (session-lifecycle) -----------------------------

  protected stateLabel(state: SessionState): string {
    return STATE_LABELS[state] ?? state;
  }

  protected stateBadgeClass(state: SessionState): string {
    return STATE_BADGES[state] ?? 'text-bg-secondary';
  }

  protected actionLabel(action: SessionTransitionAction): string {
    return ACTION_LABELS[action] ?? action;
  }

  protected actionButtonClass(action: SessionTransitionAction): string {
    return ACTION_BUTTONS[action] ?? 'btn-outline-secondary';
  }

  protected transition(action: SessionTransitionAction, override = false): void {
    if (this.lifecycleBusy()) return;
    if (action === 'finish' && !override) {
      const ok = window.confirm(
        'Finish this session? All open tower/zone ownerships will be closed ' +
          'and the session becomes terminal (history is kept).',
      );
      if (!ok) return;
    }
    this.lifecycleBusy.set(true);
    this.lifecycleError.set(null);
    this.staff.transitionSession(this.sessionId, action, override).subscribe({
      next: (s) => {
        this.setSession(s);
        this.reloadState();
      },
      error: (err) => {
        this.lifecycleBusy.set(false);
        // Out-of-window open_participation: offer the staff override.
        if (
          action === 'open_participation' &&
          !override &&
          err instanceof HttpErrorResponse &&
          err.status === 409 &&
          err.error?.requires_override
        ) {
          const ok = window.confirm(
            'The participation window is outside the allowed range ' +
              '(7 days to 1 hour before the scheduled start). Open anyway?',
          );
          if (ok) {
            this.transition(action, true);
            return;
          }
        }
        this.lifecycleError.set(extractErrorMessage(err));
      },
    });
  }

  /** DRAFT fast path: chain open_participation then start. */
  protected openAndStart(): void {
    if (this.lifecycleBusy()) return;
    this.lifecycleBusy.set(true);
    this.lifecycleError.set(null);
    this.staff.transitionSession(this.sessionId, 'open_participation').subscribe({
      next: () => {
        this.staff.transitionSession(this.sessionId, 'start').subscribe({
          next: (s) => {
            this.setSession(s);
            this.reloadState();
          },
          error: (err) => {
            this.lifecycleBusy.set(false);
            this.lifecycleError.set(extractErrorMessage(err));
            this.refreshSession();
          },
        });
      },
      error: (err) => {
        this.lifecycleBusy.set(false);
        this.lifecycleError.set(extractErrorMessage(err));
      },
    });
  }

  private refreshSession(): void {
    this.staff.getSession(this.sessionId).subscribe({
      next: (s) => this.setSession(s),
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
        this.lifecycleBusy.set(false);
      },
      error: (err) => {
        this.lifecycleBusy.set(false);
        this.lifecycleError.set(extractErrorMessage(err));
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

  protected saveOverrides(id: number): void {
    if (!this.overrideDirty() || this.overrideSaving()) return;
    this.overrideSaving.set(true);
    this.overrideError.set(null);
    const payload: AdminSessionPayload = { ...this.override() };
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

const STATE_LABELS: Record<SessionState, string> = {
  DRAFT: 'Draft',
  OPEN_FOR_PARTICIPANTS: 'Open for participants',
  RUNNING: 'Running',
  PAUSED: 'Paused',
  FINISHED: 'Finished',
};

const STATE_BADGES: Record<SessionState, string> = {
  DRAFT: 'text-bg-secondary',
  OPEN_FOR_PARTICIPANTS: 'text-bg-info',
  RUNNING: 'text-bg-success',
  PAUSED: 'text-bg-warning',
  FINISHED: 'text-bg-dark',
};

const ACTION_LABELS: Record<SessionTransitionAction, string> = {
  open_participation: 'Open participation',
  close_participation: 'Close participation',
  start: 'Start',
  pause: 'Pause',
  resume: 'Resume',
  finish: 'Finish',
};

const ACTION_BUTTONS: Record<SessionTransitionAction, string> = {
  open_participation: 'btn-outline-primary',
  close_participation: 'btn-outline-secondary',
  start: 'btn-success',
  pause: 'btn-warning',
  resume: 'btn-success',
  finish: 'btn-outline-danger',
};

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
