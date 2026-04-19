import {
  ChangeDetectionStrategy,
  Component,
  inject,
  signal,
} from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { Router } from '@angular/router';

import { CurrentSession, GameApiService } from 'shared';

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
  template: `
    <div class="row justify-content-center">
      <div class="col-md-7">
        <h1 class="h3 mb-3">Choose your session</h1>

        @switch (state().kind) {
          @case ('loading') {
            <div class="d-flex align-items-center text-body-secondary">
              <span class="spinner-border spinner-border-sm me-2"></span>
              Resolving your sessions…
            </div>
          }
          @case ('none') {
            <div class="alert alert-warning">
              {{ stateMessage() }}
            </div>
            <p class="text-body-secondary small">
              Ask a staff member to send you an invite, then come back.
            </p>
          }
          @case ('choose') {
            <p class="text-body-secondary">
              You belong to more than one active session. Pick the one you
              want to play right now — you can switch later from the
              staff UI or by asking staff to update you.
            </p>
            <div class="list-group">
              @for (c of candidates(); track c.id) {
                <button
                  type="button"
                  class="list-group-item list-group-item-action d-flex justify-content-between align-items-start"
                  [disabled]="submittingId() !== null"
                  (click)="pick(c)"
                >
                  <div>
                    <div class="fw-semibold">{{ c.name }}</div>
                    <div class="small text-body-secondary">
                      {{ c.game.name }} · <code>{{ c.slug }}</code>
                    </div>
                  </div>
                  @if (submittingId() === c.id) {
                    <span class="spinner-border spinner-border-sm ms-2"></span>
                  }
                </button>
              }
            </div>
          }
          @case ('error') {
            <div class="alert alert-danger">{{ stateMessage() }}</div>
          }
        }
      </div>
    </div>
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
