import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';

import { CurrentSession, GameApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-my-sessions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-8">
        <h1 class="h3 mb-3">My sessions</h1>

        @if (loadError(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }

        @if (loading() && sessions().length === 0) {
          <div class="d-flex align-items-center text-body-secondary">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading…
          </div>
        } @else if (sessions().length === 0) {
          <div class="alert alert-info">
            You have not participated in any session yet.
          </div>
        } @else {
          <div class="list-group">
            @for (s of sessions(); track s.id) {
              <a
                class="list-group-item list-group-item-action d-flex justify-content-between align-items-start"
                [routerLink]="['/history', s.id]"
              >
                <div>
                  <div class="fw-semibold">{{ s.name }}</div>
                  <div class="small text-body-secondary">
                    {{ s.game.name }} · <code>{{ s.slug }}</code>
                  </div>
                  <div class="small text-body-secondary">
                    {{ s.start_time | date: 'medium' }} —
                    {{ s.end_time | date: 'medium' }}
                  </div>
                </div>
                <span
                  class="badge"
                  [class]="s.is_active ? 'text-bg-success' : 'text-bg-secondary'"
                >
                  {{ s.is_active ? 'Active' : 'Past' }}
                </span>
              </a>
            }
          </div>
        }
      </div>
    </div>
  `,
})
export class MySessionsComponent {
  private readonly api = inject(GameApiService);

  protected readonly sessions = signal<CurrentSession[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  constructor() {
    this.loading.set(true);
    this.api.mySessions().subscribe({
      next: (list) => {
        this.sessions.set(list);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }
}
