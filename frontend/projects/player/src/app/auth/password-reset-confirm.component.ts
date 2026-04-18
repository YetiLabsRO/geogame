import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { AuthService } from 'shared';

import { extractErrorMessage } from './form-error';

@Component({
  selector: 'app-password-reset-confirm',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-md-6 col-lg-5">
        <h1 class="h3 mb-4">Choose a new password</h1>

        @if (done()) {
          <div class="alert alert-success">
            Your password has been updated. Please sign in with your new password.
          </div>
          <a class="btn btn-primary" routerLink="/login">Sign in</a>
        } @else {
          <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
            <div class="mb-3">
              <label class="form-label" for="new_password">New password</label>
              <input
                id="new_password"
                type="password"
                class="form-control"
                formControlName="new_password"
                autocomplete="new-password"
              />
              <div class="form-text">Minimum 8 characters.</div>
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
              Save new password
            </button>
          </form>
        }
      </div>
    </div>
  `,
})
export class PasswordResetConfirmComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);

  protected readonly pending = signal(false);
  protected readonly done = signal(false);
  protected readonly errorMessage = signal<string | null>(null);

  protected readonly form = this.fb.group({
    new_password: ['', [Validators.required, Validators.minLength(8)]],
  });

  protected submit(): void {
    if (this.form.invalid || this.pending()) {
      return;
    }
    const params = this.route.snapshot.paramMap;
    const uid = params.get('uid');
    const token = params.get('token');
    if (!uid || !token) {
      this.errorMessage.set('Invalid reset link.');
      return;
    }
    this.pending.set(true);
    this.errorMessage.set(null);
    this.auth.confirmPasswordReset(uid, token, this.form.getRawValue().new_password).subscribe({
      next: () => {
        this.pending.set(false);
        this.done.set(true);
      },
      error: (err) => {
        this.pending.set(false);
        this.errorMessage.set(extractErrorMessage(err));
      },
    });
  }
}
