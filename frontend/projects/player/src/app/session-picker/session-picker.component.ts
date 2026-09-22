import {
  ChangeDetectionStrategy,
  Component,
  inject,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { DatePipe } from '@angular/common';
import { Router } from '@angular/router';

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

type State =
  | { kind: 'loading' }
  | { kind: 'single'; session: CurrentSession }
  | { kind: 'choose'; candidates: CurrentSession[] }
  | { kind: 'none'; message: string }
  | { kind: 'error'; message: string };

@Component({
  selector: 'app-session-picker',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, UiAlertComponent, UiCardComponent, UiChipComponent, UiEmptyStateComponent, UiSpinnerComponent],
  template: `
    <div class="session-picker">
      <h1 class="tr-h1 session-picker__title">Choose your run</h1>

      @switch (state().kind) {
        @case ('loading') {
          <div class="session-picker__loading">
            <ui-spinner [size]="20" />
            <span class="tr-body">Resolving your sessions…</span>
          </div>
        }
        @case ('none') {
          <ui-empty-state icon="compass" title="No sessions yet" [description]="stateMessage()">
            <p class="tr-body">Ask a staff member to send you an invite, then come back.</p>
          </ui-empty-state>
        }
        @case ('choose') {
          <p class="tr-body session-picker__intro">
            You belong to more than one active session. Pick the one you want to play right now
            — you can switch later from the staff UI or by asking staff to update you.
          </p>
          <div class="session-picker__list">
            @for (c of candidates(); track c.id) {
              <button
                type="button"
                class="session-picker__card-tap"
                [disabled]="submittingId() !== null"
                (click)="pick(c)"
              >
                <ui-card class="session-picker__card">
                  <div class="session-picker__row">
                    <div class="session-picker__info">
                      <span class="tr-eyebrow session-picker__eyebrow">{{ c.game.name }}</span>
                      <span class="tr-h3 session-picker__name">{{ c.name }}</span>
                      <span class="tr-meta-tiny session-picker__dates">
                        {{ c.start_time | date: 'mediumDate' }} – {{ c.end_time | date: 'mediumDate' }}
                      </span>
                    </div>
                    <div class="session-picker__trailing">
                      @if (submittingId() === c.id) {
                        <ui-spinner [size]="18" />
                      } @else {
                        <ui-chip [tone]="c.is_active ? 'brand' : 'neutral'">
                          {{ c.is_active ? 'Active' : 'Past' }}
                        </ui-chip>
                      }
                    </div>
                  </div>
                </ui-card>
              </button>
            }
          </div>
        }
        @case ('error') {
          <ui-alert tone="danger">{{ stateMessage() }}</ui-alert>
        }
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .session-picker {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
      padding: var(--spacing-xl) var(--spacing-xl) var(--spacing-2xl);
      max-width: 560px;
      margin: 0 auto;
    }
    .session-picker__title {
      color: var(--color-text-primary);
    }
    .session-picker__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      color: var(--color-text-secondary);
    }
    .session-picker__intro {
      color: var(--color-text-secondary);
    }
    .session-picker__list {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .session-picker__card-tap {
      all: unset;
      display: block;
      box-sizing: border-box;
      width: 100%;
      min-height: var(--tap-min);
      cursor: pointer;
    }
    .session-picker__card-tap:disabled {
      cursor: not-allowed;
      opacity: 0.6;
    }
    .session-picker__card-tap:focus-visible {
      outline: 2px solid var(--color-brand-primary);
      outline-offset: 2px;
      border-radius: var(--radius-lg);
    }
    .session-picker__row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
    }
    .session-picker__info {
      display: flex;
      min-width: 0;
      flex-direction: column;
      gap: 2px;
    }
    .session-picker__eyebrow {
      color: var(--color-brand-onSurface);
    }
    .session-picker__name {
      overflow: hidden;
      color: var(--color-text-primary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .session-picker__dates {
      color: var(--color-text-muted);
    }
    .session-picker__trailing {
      display: flex;
      flex-shrink: 0;
      align-items: center;
    }
  `,
})
export class SessionPickerComponent {
  private readonly api = inject(GameApiService);
  private readonly router = inject(Router);

  protected readonly state = signal<State>({ kind: 'loading' });
  protected readonly submittingId = signal<number | null>(null);

  protected readonly candidates = () => {
    const s = this.state();
    return s.kind === 'choose' ? s.candidates : [];
  };
  protected readonly stateMessage = () => {
    const s = this.state();
    return s.kind === 'none' || s.kind === 'error' ? s.message : '';
  };

  constructor() {
    this.resolve();
  }

  private resolve(): void {
    this.state.set({ kind: 'loading' });
    this.api.currentSession().subscribe({
      next: (session) => {
        // Backend auto-resolved to exactly one — jump straight to the map.
        this.state.set({ kind: 'single', session });
        this.router.navigateByUrl('/');
      },
      error: (err: unknown) => this.handleError(err),
    });
  }

  private handleError(err: unknown): void {
    if (!(err instanceof HttpErrorResponse)) {
      this.state.set({ kind: 'error', message: extractErrorMessage(err) });
      return;
    }
    if (err.status === 409) {
      const body = err.error as { candidates?: CurrentSession[] };
      const candidates = body?.candidates ?? [];
      this.state.set({ kind: 'choose', candidates });
      return;
    }
    if (err.status === 404) {
      const body = err.error as { detail?: string };
      this.state.set({
        kind: 'none',
        message: body?.detail ?? 'No active session available.',
      });
      return;
    }
    this.state.set({ kind: 'error', message: extractErrorMessage(err) });
  }

  protected pick(candidate: CurrentSession): void {
    if (this.submittingId() !== null) return;
    this.submittingId.set(candidate.id);
    this.api.setCurrentSession(candidate.id).subscribe({
      next: () => {
        this.submittingId.set(null);
        this.router.navigateByUrl('/');
      },
      error: (err) => {
        this.submittingId.set(null);
        this.state.set({ kind: 'error', message: extractErrorMessage(err) });
      },
    });
  }
}
