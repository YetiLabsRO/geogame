import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { RouterLink } from '@angular/router';

import {
  CurrentSession,
  GameApiService,
  UiAlertComponent,
  UiCardComponent,
  UiChipComponent,
  UiEmptyStateComponent,
  UiSpinnerComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-my-sessions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    DatePipe,
    RouterLink,
    UiAlertComponent,
    UiCardComponent,
    UiChipComponent,
    UiEmptyStateComponent,
    UiSpinnerComponent,
  ],
  template: `
    <div class="chronicle-page">
      <span class="tr-eyebrow chronicle-page__eyebrow">Your expeditions</span>
      <h1 class="tr-h1 chronicle-page__title">Chronicle</h1>

      @if (loadError(); as msg) {
        <ui-alert tone="danger">{{ msg }}</ui-alert>
      }

      @if (loading() && sessions().length === 0) {
        <div class="chronicle-page__loading">
          <ui-spinner [size]="20" />
          <span class="tr-body">Loading…</span>
        </div>
      } @else if (sessions().length === 0) {
        <ui-empty-state
          icon="book"
          title="No expeditions yet"
          description="You have not participated in any session yet."
        />
      } @else {
        <div class="chronicle-page__list">
          @for (s of sessions(); track s.id; let i = $index) {
            <a class="chronicle-page__row" [routerLink]="['/history', s.id]">
              <ui-card class="chronicle-page__card">
                <div class="chronicle-page__row-content">
                  <span class="chronicle-page__rank tr-h3">{{ i + 1 }}</span>
                  <div class="chronicle-page__info">
                    <span class="tr-h3 chronicle-page__name">{{ s.name }}</span>
                    <span class="tr-eyebrow chronicle-page__game">{{ s.game.name }}</span>
                    <span class="tr-meta-tiny chronicle-page__dates">
                      {{ s.start_time | date: 'mediumDate' }} – {{ s.end_time | date: 'mediumDate' }}
                    </span>
                  </div>
                  <ui-chip class="chronicle-page__status" [tone]="s.is_active ? 'brand' : 'neutral'">
                    {{ s.is_active ? 'Active' : 'Past' }}
                  </ui-chip>
                </div>
              </ui-card>
            </a>
          }
        </div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .chronicle-page {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
      padding: var(--spacing-xl) var(--spacing-xl) var(--spacing-2xl);
      max-width: 640px;
      margin: 0 auto;
    }
    .chronicle-page__eyebrow {
      color: var(--color-brand-onSurface);
    }
    .chronicle-page__title {
      margin-bottom: var(--spacing-xs);
      color: var(--color-text-primary);
    }
    .chronicle-page__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      color: var(--color-text-secondary);
    }
    .chronicle-page__list {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .chronicle-page__row {
      display: block;
      color: inherit;
      text-decoration: none;
      border-radius: var(--radius-lg);
    }
    .chronicle-page__row:focus-visible {
      outline: 2px solid var(--color-brand-primary);
      outline-offset: 2px;
    }
    .chronicle-page__row-content {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
    }
    .chronicle-page__rank {
      display: flex;
      flex-shrink: 0;
      align-items: center;
      justify-content: center;
      width: 40px;
      height: 40px;
      border-radius: var(--radius-md);
      background: var(--color-bg-inset);
      color: var(--color-text-primary);
    }
    .chronicle-page__info {
      display: flex;
      min-width: 0;
      flex: 1;
      flex-direction: column;
      gap: 2px;
    }
    .chronicle-page__name {
      overflow: hidden;
      color: var(--color-text-primary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .chronicle-page__game {
      color: var(--color-brand-onSurface);
    }
    .chronicle-page__dates {
      color: var(--color-text-muted);
    }
    .chronicle-page__status {
      flex-shrink: 0;
    }
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
