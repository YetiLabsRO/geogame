import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { AuthService } from 'shared';

import { extractErrorMessage } from './form-error';

@Component({
  selector: 'app-password-reset-request',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-md-6 col-lg-5">
        <h1 class="h3 mb-4">Reset your password</h1>

        @if (sent()) {
          <div class="alert alert-success">
            If an account exists for that email, we've sent a link to reset your password.
          </div>
          <div class="small">
            <a routerLink="/login">Back to sign in</a>
          </div>
        } @else {
          <p class="text-body-secondary">
            Enter your email and we'll send you a link to choose a new password.
          </p>
          <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
            <div class="mb-3">
              <label class="form-label" for="email">Email</label>
              <input
                id="email"
                type="email"
                class="form-control"
                formControlName="email"
                autocomplete="email"
              />
            </div>

            @if (errorMessage(); as msg) {
              <div class="alert alert-danger py-2">{{ msg }}</div>
            }

            <button
              type="submit"
              class="btn btn-primary w-100"
              [disabled]="form.invalid || pending()"
            >
              @if (pending()) {
                <span class="spinner-border spinner-border-sm me-2"></span>
              }
              Send reset link
            </button>
          </form>

          <div class="mt-3 small">
            <a routerLink="/login">Back to sign in</a>
          </div>
        }
      </div>
    </div>
  `,
})
export class PasswordResetRequestComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly auth = inject(AuthService);

  protected readonly pending = signal(false);
  protected readonly sent = signal(false);
  protected readonly errorMessage = signal<string | null>(null);

  protected readonly form = this.fb.group({
    email: ['', [Validators.required, Validators.email]],
  });

  protected submit(): void {
    if (this.form.invalid || this.pending()) {
      return;
    }
    this.pending.set(true);
    this.errorMessage.set(null);
    this.auth.requestPasswordReset(this.form.getRawValue().email).subscribe({
      next: () => {
        this.pending.set(false);
        this.sent.set(true);
      },
      error: (err) => {
        this.pending.set(false);
        this.errorMessage.set(extractErrorMessage(err));
      },
    });
  }
}
