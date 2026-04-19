import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';

import { CurrentSession, GameApiService, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-game-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe],
  template: `
    <h1 class="h3 mb-3">Game state</h1>

    @if (session(); as s) {
      <div class="card mb-4">
        <div class="card-body">
          <h2 class="h6 text-body-secondary">
            Current session · <span class="fw-normal">{{ s.game.name }}</span>
          </h2>
          <div class="fs-4 fw-semibold">{{ s.name }}</div>
          <div class="small text-body-secondary">
            {{ s.start_time | date: 'medium' }} — {{ s.end_time | date: 'medium' }}
          </div>
          <span class="badge mt-1" [class]="s.is_active ? 'text-bg-success' : 'text-bg-secondary'">
            {{ s.is_active ? 'Active' : 'Inactive' }}
          </span>
        </div>
      </div>
    } @else if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (notice(); as msg) {
      <div class="alert alert-success">{{ msg }}</div>
    }
    @if (actionError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    <div class="card border-warning">
      <div class="card-body">
        <h2 class="h6 text-warning">End round</h2>
        <p class="small mb-3">
          Closes every active tower and zone ownership. Team scores are preserved.
          Use this when the current round finishes.
        </p>
        <button
          type="button"
          class="btn btn-warning"
          [disabled]="acting()"
          (click)="endRound()"
        >
          @if (acting() === 'end-round') {
            <span class="spinner-border spinner-border-sm me-1"></span>
          }
          Unassign all towers
        </button>
      </div>
    </div>

    <div class="card border-danger mt-3">
      <div class="card-body">
        <h2 class="h6 text-danger">Reset scores</h2>
        <p class="small mb-3">
          Zeroes every team's cumulative score <strong>and</strong> closes every active
          ownership. Use this when starting a brand-new round. This cannot be undone.
        </p>
        <button
          type="button"
          class="btn btn-danger"
          [disabled]="acting()"
          (click)="resetScores()"
        >
          @if (acting() === 'reset-scores') {
            <span class="spinner-border spinner-border-sm me-1"></span>
          }
          Reset all scores
        </button>
      </div>
    </div>
  `,
})
export class GameStateComponent {
  private readonly gameApi = inject(GameApiService);
  private readonly staffApi = inject(StaffApiService);

  protected readonly session = signal<CurrentSession | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly acting = signal<'end-round' | 'reset-scores' | null>(null);
  protected readonly notice = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);

  constructor() {
    this.gameApi.currentSession().subscribe({
      next: (s) => this.session.set(s),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected endRound(): void {
    if (this.acting()) return;
    if (!confirm('Close every active tower ownership? Scores are preserved.')) return;
    this.acting.set('end-round');
    this.notice.set(null);
    this.actionError.set(null);
    this.staffApi.unassignAllTowers().subscribe({
      next: (res) => {
        this.acting.set(null);
        this.notice.set(`Round ended. ${res.unassigned.length} tower(s) unassigned.`);
      },
      error: (err) => {
        this.acting.set(null);
        this.actionError.set(extractErrorMessage(err));
      },
    });
  }

  protected resetScores(): void {
    if (this.acting()) return;
    if (
      !confirm(
        'Reset every team score to zero AND close every open ownership? This cannot be undone.',
      )
    ) {
      return;
    }
    this.acting.set('reset-scores');
    this.notice.set(null);
    this.actionError.set(null);
    this.staffApi.resetScores().subscribe({
      next: (res) => {
        this.acting.set(null);
        this.notice.set(`Scores reset for ${res.teams_reset} team(s).`);
      },
      error: (err) => {
        this.acting.set(null);
        this.actionError.set(extractErrorMessage(err));
      },
    });
  }
}
