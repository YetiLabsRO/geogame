import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';

import {
  DementorTickPayload,
  DementorTotals,
  DementorsService,
  GameApiService,
  REALTIME_EVENTS,
  RealtimeService,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

const POLL_INTERVAL_MS = 5_000;

/**
 * Staff dementors dashboard (mode-dementors-ble) — wireframe.
 *
 * Live wizard/dementor totals for the staff user's current session,
 * polled from /api/staff/dementors/session/<id>/totals/ (the graceful
 * fallback for a future Channels push), plus a per-player feed usable
 * on a tablet at the park entrance.
 */
@Component({
  selector: 'app-dementors-dashboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe],
  template: `
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div>
        <h1 class="h3 mb-0">Dementors</h1>
        <div class="small text-body-secondary">
          Refreshes every 5s · last updated
          @if (lastUpdated(); as t) {
            {{ t }}
          } @else {
            —
          }
        </div>
      </div>
      <button
        type="button"
        class="btn btn-sm btn-outline-secondary"
        [disabled]="loading()"
        (click)="refresh()"
      >
        @if (loading()) {
          <span class="spinner-border spinner-border-sm me-1"></span>
        }
        Refresh now
      </button>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (totals(); as t) {
      @if (!t.enabled) {
        <div class="alert alert-info">
          Dementors mode is not enabled for the current session. Turn it
          on via the Game/Session config (dementors_enabled).
        </div>
      }

      <div class="row g-3 mb-4">
        <div class="col-sm-4">
          <div class="card text-center border-primary">
            <div class="card-body">
              <div class="display-5 fw-bold text-primary">
                {{ t.totals.wizards }}
              </div>
              <div class="text-body-secondary">
                <i class="bi bi-stars me-1"></i>Wizards
              </div>
            </div>
          </div>
        </div>
        <div class="col-sm-4">
          <div class="card text-center border-dark">
            <div class="card-body">
              <div class="display-5 fw-bold">{{ t.totals.dementors }}</div>
              <div class="text-body-secondary">
                <i class="bi bi-tornado me-1"></i>Dementors
              </div>
            </div>
          </div>
        </div>
        <div class="col-sm-4">
          <div class="card text-center">
            <div class="card-body">
              <div class="display-5 fw-bold text-body-secondary">
                {{ t.totals.out_of_play }}
              </div>
              <div class="text-body-secondary">
                <i class="bi bi-emoji-dizzy me-1"></i>Out of play
              </div>
            </div>
          </div>
        </div>
      </div>

      @if (t.players.length === 0) {
        <div class="alert alert-info">No players in this run yet.</div>
      } @else {
        <div class="table-responsive">
          <table class="table table-sm align-middle">
            <thead>
              <tr>
                <th>Player</th>
                <th>Team</th>
                <th>Role</th>
                <th class="text-end">Energy</th>
                <th class="text-end">Last delta</th>
                <th class="text-end">Last tick</th>
              </tr>
            </thead>
            <tbody>
              @for (p of t.players; track p.player_id) {
                <tr [class.table-secondary]="!p.alive">
                  <td class="fw-semibold">{{ p.username }}</td>
                  <td class="text-body-secondary">{{ p.team ?? '—' }}</td>
                  <td>
                    @if (!p.alive) {
                      <span class="badge text-bg-secondary">Out</span>
                    } @else if (p.role === 'WIZARD') {
                      <span class="badge text-bg-primary">Wizard</span>
                    } @else {
                      <span class="badge text-bg-dark">Dementor</span>
                    }
                  </td>
                  <td class="text-end">{{ p.energy }}</td>
                  <td
                    class="text-end"
                    [class.text-danger]="p.last_delta < 0"
                    [class.text-success]="p.last_delta > 0"
                  >
                    {{ p.last_delta }}
                  </td>
                  <td class="text-end small text-body-secondary">
                    @if (p.last_tick_at) {
                      {{ p.last_tick_at | date: 'HH:mm:ss' }}
                    } @else {
                      —
                    }
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    } @else if (!loadError()) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    }
  `,
})
export class DementorsDashboardComponent {
  private readonly api = inject(DementorsService);
  private readonly gameApi = inject(GameApiService);
  protected readonly realtime = inject(RealtimeService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly totals = signal<DementorTotals | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly lastUpdated = signal<string | null>(null);

  private sessionId: number | null = null;
  private pollHandle: ReturnType<typeof setInterval> | null = null;
  private seenConnections = 0;

  constructor() {
    this.refresh();
    this.connectRealtime();
    // Polling stays as the graceful fallback: skip it while the socket
    // is delivering tick snapshots (5.3).
    this.pollHandle = setInterval(() => {
      if (!this.realtime.connected()) this.refresh();
    }, POLL_INTERVAL_MS);

    // Reconcile the full feed from REST after every reconnect.
    effect(() => {
      const count = this.realtime.connections();
      if (count > this.seenConnections && this.seenConnections > 0) {
        this.refresh();
      }
      this.seenConnections = Math.max(this.seenConnections, count);
    });

    // 5.3 — apply live totals + role/energy from each tick push, keeping
    // the username/team join from the last REST snapshot.
    this.realtime
      .eventsOfType<DementorTickPayload>(REALTIME_EVENTS.dementorTick)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((envelope) => this.applyTick(envelope.payload));

    this.destroyRef.onDestroy(() => {
      if (this.pollHandle) clearInterval(this.pollHandle);
      this.realtime.disconnect();
    });
  }

  private connectRealtime(): void {
    this.gameApi.currentSession().subscribe({
      next: (session) => this.realtime.connect(session.id, session.realtime_enabled),
      error: () => {},
    });
  }

  private applyTick(payload: DementorTickPayload): void {
    const current = this.totals();
    if (!current) {
      // No baseline yet (username/team unknown) — pull the full feed.
      this.refresh();
      return;
    }
    const known = new Set(current.players.map((row) => row.player_id));
    if (payload.players.some((p) => !known.has(p.player_id))) {
      // A player we have never seen (roster changed) — reconcile via REST.
      this.refresh();
      return;
    }
    const live = new Map(payload.players.map((p) => [p.player_id, p]));
    const players = current.players.map((row) => {
      const p = live.get(row.player_id);
      return p
        ? { ...row, role: p.role, energy: p.energy, alive: p.alive, last_delta: p.last_delta }
        : row;
    });
    this.totals.set({ ...current, totals: payload.totals, players });
    this.lastUpdated.set(new Date().toLocaleTimeString());
  }

  protected refresh(): void {
    this.loading.set(true);
    if (this.sessionId !== null) {
      this.loadTotals(this.sessionId);
      return;
    }
    this.gameApi.currentSession().subscribe({
      next: (session) => {
        this.sessionId = session.id;
        this.loadTotals(session.id);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  private loadTotals(sessionId: number): void {
    this.api.totals(sessionId).subscribe({
      next: (totals) => {
        this.totals.set(totals);
        this.lastUpdated.set(new Date().toLocaleTimeString());
        this.loading.set(false);
        this.loadError.set(null);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }
}
