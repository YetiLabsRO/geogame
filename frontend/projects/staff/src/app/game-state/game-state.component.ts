import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';

import { AdminSession, CurrentSession, GameApiService, PageHeaderComponent, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface GameBucket {
  game_name: string;
  game_slug: string;
  sessions: AdminSession[];
}

/**
 * Landing page for "Game state". Used to fire unassign-all/reset-scores
 * directly against whatever session the nav switcher happened to have
 * selected (an implicit, easy-to-mismatch scope). Those destructive
 * actions now live in each session's own control console — scoped
 * explicitly to the session you're looking at, behind ConfirmService —
 * see session-detail.component.ts's "Danger zone". This page is now just
 * a quick way to find the right session's console.
 */
@Component({
  selector: 'app-game-state',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, RouterLink, PageHeaderComponent],
  template: `
    <app-page-header
      title="Game state"
      subtitle="Destructive actions (unassign towers, reset scores, finish) live on each session's own console, scoped to that session."
    />

    @if (current(); as s) {
      <div class="card mb-4 border-primary">
        <div class="card-body">
          <h2 class="h6 text-body-secondary mb-1">
            Your current session · <span class="fw-normal">{{ s.game.name }}</span>
          </h2>
          <div class="fs-5 fw-semibold">{{ s.name }}</div>
          <div class="small text-body-secondary">
            {{ s.start_time | date: 'medium' }} — {{ s.end_time | date: 'medium' }}
          </div>
          <a class="btn btn-sm btn-primary mt-2" [routerLink]="['/sessions', s.id]">
            <i class="bi bi-sliders"></i> Open its control console
          </a>
        </div>
      </div>
    } @else if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    <h2 class="h6 mb-2">All sessions</h2>
    @if (loading()) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (buckets().length === 0) {
      <div class="alert alert-info">No sessions yet.</div>
    } @else {
      @for (bucket of buckets(); track bucket.game_slug) {
        <h3 class="h6 text-body-secondary mt-3">{{ bucket.game_name }}</h3>
        <div class="list-group mb-3">
          @for (s of bucket.sessions; track s.id) {
            <a
              class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
              [routerLink]="['/sessions', s.id]"
            >
              <span>
                {{ s.name }}
                <code class="small text-body-secondary ms-1">{{ s.slug }}</code>
              </span>
              <span class="badge" [class]="stateBadgeClass(s.state)">{{ s.state }}</span>
            </a>
          }
        </div>
      }
    }
  `,
})
export class GameStateComponent {
  private readonly gameApi = inject(GameApiService);
  private readonly staffApi = inject(StaffApiService);

  protected readonly current = signal<CurrentSession | null>(null);
  protected readonly sessions = signal<AdminSession[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly buckets = signal<GameBucket[]>([]);

  constructor() {
    this.gameApi.currentSession().subscribe({
      next: (s) => this.current.set(s),
      error: () => this.current.set(null),
    });
    this.loading.set(true);
    this.staffApi.listSessions().subscribe({
      next: (list) => {
        this.sessions.set(list);
        this.buckets.set(groupByGame(list));
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected stateBadgeClass(state: AdminSession['state']): string {
    return STATE_BADGES[state] ?? 'text-bg-secondary';
  }
}

const STATE_BADGES: Record<AdminSession['state'], string> = {
  DRAFT: 'text-bg-secondary',
  OPEN_FOR_PARTICIPANTS: 'text-bg-info',
  RUNNING: 'text-bg-success',
  PAUSED: 'text-bg-warning',
  FINISHED: 'text-bg-dark',
};

function groupByGame(sessions: AdminSession[]): GameBucket[] {
  const byGame = new Map<string, GameBucket>();
  for (const s of sessions) {
    let b = byGame.get(s.game_slug);
    if (!b) {
      b = { game_slug: s.game_slug, game_name: s.game_name, sessions: [] };
      byGame.set(s.game_slug, b);
    }
    b.sessions.push(s);
  }
  return Array.from(byGame.values())
    .sort((a, b) => a.game_name.localeCompare(b.game_name))
    .map((b) => ({
      ...b,
      sessions: b.sessions.slice().sort((a, b) => a.name.localeCompare(b.name)),
    }));
}
