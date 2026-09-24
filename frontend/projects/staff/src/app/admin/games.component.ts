import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AdminGame, PageHeaderComponent, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface Row {
  game: AdminGame;
  busy: boolean;
  error: string | null;
  notice: string | null;
}

@Component({
  selector: 'app-admin-games',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, PageHeaderComponent],
  template: `
    <app-page-header
      title="Games"
      subtitle="Reusable event configuration — map defaults, rules, and the challenge bank."
    >
      <a actions routerLink="/games/new" class="btn btn-primary btn-sm">
        <i class="bi bi-plus-lg"></i> New game
      </a>
    </app-page-header>

    <p class="text-body-secondary small">
      Each Game can host one or more Sessions on the <a routerLink="/sessions">Sessions</a> page.
      Open a game to edit its rules, mechanics, roles, and score multipliers in the game wizard.
    </p>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading() && rows().length === 0) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (rows().length === 0) {
      <div class="alert alert-info">
        No games yet. <a routerLink="/games/new">Create the first one</a>.
      </div>
    } @else {
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Slug</th>
              <th>Name</th>
              <th>Created by</th>
              <th>Active</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.game.id) {
              <tr>
                <td><code>{{ row.game.slug }}</code></td>
                <td>
                  <a [routerLink]="['/games', row.game.id, 'edit']" class="fw-semibold">
                    {{ row.game.name }}
                  </a>
                  @if (row.game.cloned_from !== null) {
                    <span class="badge text-bg-info ms-1">clone of #{{ row.game.cloned_from }}</span>
                  }
                </td>
                <td class="small text-body-secondary">
                  {{ row.game.created_by_username || '—' }}
                </td>
                <td class="text-center">
                  <div class="form-check form-switch d-inline-block">
                    <input
                      type="checkbox"
                      class="form-check-input"
                      role="switch"
                      [checked]="row.game.is_active"
                      [disabled]="row.busy"
                      (change)="toggleActive(row)"
                    />
                  </div>
                </td>
                <td class="text-end">
                  <div class="d-flex gap-2 justify-content-end">
                    <a
                      class="btn btn-sm btn-outline-secondary"
                      [routerLink]="['/games', row.game.id, 'edit']"
                    >
                      <i class="bi bi-pencil"></i> Edit
                    </a>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      [disabled]="row.busy"
                      (click)="clone(row)"
                    >
                      Clone
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-warning"
                      [disabled]="row.busy"
                      (click)="pauseAll(row)"
                    >
                      Pause all sessions
                    </button>
                  </div>
                  @if (row.error; as msg) {
                    <div class="small text-danger mt-1">{{ msg }}</div>
                  }
                  @if (row.notice; as msg) {
                    <div class="small text-body-secondary mt-1">{{ msg }}</div>
                  }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    }
  `,
})
export class GamesComponent {
  private readonly api = inject(StaffApiService);

  protected readonly rows = signal<Row[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  constructor() {
    this.refresh();
  }

  private refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listGames().subscribe({
      next: (list) => {
        this.rows.set(list.map((game) => ({ game, busy: false, error: null, notice: null })));
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected toggleActive(row: Row): void {
    this.patch(row, { busy: true, error: null });
    this.api.updateGame(row.game.id, { is_active: !row.game.is_active }).subscribe({
      next: (updated) => {
        this.rows.update((rows) =>
          rows.map((r) => (r.game.id === row.game.id ? { game: updated, busy: false, error: null, notice: null } : r)),
        );
      },
      error: (err) => this.patch(row, { busy: false, error: extractErrorMessage(err) }),
    });
  }

  protected clone(row: Row): void {
    this.patch(row, { busy: true, notice: 'Cloning…', error: null });
    this.api.cloneGame(row.game.id).subscribe({
      next: (created) => {
        this.rows.update((rows) => [
          ...rows,
          { game: created, busy: false, error: null, notice: `Cloned as "${created.name}" (${created.slug}).` },
        ]);
        this.patch(row, { busy: false, notice: null });
      },
      error: (err) => this.patch(row, { busy: false, error: extractErrorMessage(err), notice: null }),
    });
  }

  protected pauseAll(row: Row): void {
    this.patch(row, { busy: true, notice: 'Pausing…', error: null });
    this.api.pauseAllSessions(row.game.id).subscribe({
      next: (res) => {
        const n = res.paused_sessions.length;
        this.patch(row, {
          busy: false,
          notice: n ? `Paused ${n} active session${n === 1 ? '' : 's'}.` : 'No active sessions to pause.',
        });
      },
      error: (err) => this.patch(row, { busy: false, error: extractErrorMessage(err), notice: null }),
    });
  }

  private patch(row: Row, patch: Partial<Row>): void {
    this.rows.update((rows) => rows.map((r) => (r.game.id === row.game.id ? { ...r, ...patch } : r)));
  }
}
