import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  AuthService,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiFieldComponent,
  UiIconComponent,
  UiInputDirective,
} from 'shared';

import { extractErrorMessage } from './form-error';

@Component({
  selector: 'app-password-reset-confirm',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiFieldComponent,
    UiIconComponent,
    UiInputDirective,
  ],
  template: `
    <div class="auth-page">
      <div class="auth-page__brand">
        <span class="auth-page__mark"><ui-icon name="compass" [size]="17" /></span>
        <span class="tr-eyebrow auth-page__eyebrow">Tower Rush</span>
      </div>
      <h1 class="tr-h1 auth-page__title">Choose a new passphrase</h1>

      @if (done()) {
        <ui-card class="auth-page__card">
          <ui-alert tone="success">
            Your password has been updated. Please sign in with your new password.
          </ui-alert>
          <a routerLink="/login" class="auth-page__cta tr-button-serif">Sign in</a>
        </ui-card>
      } @else {
        <ui-card class="auth-page__card">
          <form [formGroup]="form" (ngSubmit)="submit()" novalidate class="auth-page__form">
            <ui-field label="New password" help="Minimum 8 characters.">
              <input uiInput type="password" formControlName="new_password" autocomplete="new-password" />
            </ui-field>

            @if (errorMessage(); as msg) {
              <ui-alert tone="danger">{{ msg }}</ui-alert>
            }

            <ui-button
              type="submit"
              [block]="true"
              [loading]="pending()"
              [disabled]="form.invalid || pending()"
            >
              Set new password
            </ui-button>
          </form>
        </ui-card>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .auth-page {
      box-sizing: border-box;
      display: flex;
      min-height: 100dvh;
      flex-direction: column;
      align-items: center;
      gap: var(--spacing-md);
      padding: var(--spacing-3xl) var(--spacing-xl) var(--spacing-xl);
      background: var(--color-bg-canvas);
    }
    .auth-page__brand {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--spacing-xs);
    }
    .auth-page__mark {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      border-radius: var(--radius-full);
      background: var(--color-brand-primary);
      color: var(--color-text-onBrand);
    }
    .auth-page__eyebrow {
      color: var(--color-brand-onSurface);
    }
    .auth-page__title {
      color: var(--color-text-primary);
      text-align: center;
    }
    .auth-page__card {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
      width: 100%;
      max-width: 400px;
    }
    .auth-page__form {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
    }
    .auth-page__cta {
      box-sizing: border-box;
      display: flex;
      align-items: center;
      justify-content: center;
      height: 56px;
      padding-inline: var(--spacing-xl);
      border-radius: var(--radius-xl);
      background: var(--color-brand-primary);
      color: var(--color-text-onBrand);
      text-decoration: none;
      box-shadow: var(--elevation-brand-glow);
    }
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
