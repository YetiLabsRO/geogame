import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

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
  selector: 'app-register',
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
      <h1 class="tr-h1 auth-page__title">Join the expedition</h1>

      <ui-card class="auth-page__card">
        <form [formGroup]="form" (ngSubmit)="submit()" novalidate class="auth-page__form">
          <ui-field label="Username">
            <input uiInput type="text" formControlName="username" autocomplete="username" />
          </ui-field>
          <ui-field label="Email" icon="key">
            <input uiInput type="email" formControlName="email" autocomplete="email" />
          </ui-field>
          <div class="row g-2">
            <div class="col-6">
              <ui-field label="First name">
                <input uiInput type="text" formControlName="first_name" autocomplete="given-name" />
              </ui-field>
            </div>
            <div class="col-6">
              <ui-field label="Last name">
                <input uiInput type="text" formControlName="last_name" autocomplete="family-name" />
              </ui-field>
            </div>
          </div>
          <ui-field label="Password" help="Minimum 8 characters.">
            <input uiInput type="password" formControlName="password" autocomplete="new-password" />
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
            Create account
          </ui-button>
        </form>
      </ui-card>

      <div class="auth-page__links">
        <a routerLink="/login" class="tr-button-label auth-page__link">Already have an account? Sign in</a>
      </div>
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
      width: 100%;
      max-width: 400px;
    }
    .auth-page__form {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
    }
    .auth-page__links {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--spacing-sm);
      margin-top: var(--spacing-sm);
    }
    .auth-page__link {
      color: var(--color-brand-onSurface);
      text-decoration: none;
    }
  `,
})
export class RegisterComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly pending = signal(false);
  protected readonly errorMessage = signal<string | null>(null);

  protected readonly form = this.fb.group({
    username: ['', [Validators.required, Validators.maxLength(150)]],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(8)]],
    first_name: [''],
    last_name: [''],
  });

  protected submit(): void {
    if (this.form.invalid || this.pending()) {
      return;
    }
    this.pending.set(true);
    this.errorMessage.set(null);
    this.auth.register(this.form.getRawValue()).subscribe({
      next: () => {
        this.auth.fetchProfile().subscribe();
        this.router.navigateByUrl('/');
      },
      error: (err) => {
        this.pending.set(false);
        this.errorMessage.set(extractErrorMessage(err));
      },
    });
  }
}
