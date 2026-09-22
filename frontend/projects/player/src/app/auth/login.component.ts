import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

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
  selector: 'app-login',
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
      <h1 class="tr-h1 auth-page__title">Begin your journey</h1>

      <ui-card class="auth-page__card">
        <form [formGroup]="form" (ngSubmit)="submit()" novalidate class="auth-page__form">
          <ui-field label="Username or email" icon="key">
            <input uiInput type="text" formControlName="login" autocomplete="username" />
          </ui-field>
          <ui-field label="Password">
            <input uiInput type="password" formControlName="password" autocomplete="current-password" />
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
            Sign in
          </ui-button>
        </form>
      </ui-card>

      <div class="auth-page__links">
        <a routerLink="/reset" class="tr-button-label auth-page__link">Forgot password?</a>
        <a routerLink="/register" class="tr-button-label auth-page__link">Create an account</a>
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
export class LoginComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly pending = signal(false);
  protected readonly errorMessage = signal<string | null>(null);

  protected readonly form = this.fb.group({
    login: ['', [Validators.required]],
    password: ['', [Validators.required]],
  });

  protected submit(): void {
    if (this.form.invalid || this.pending()) {
      return;
    }
    this.pending.set(true);
    this.errorMessage.set(null);
    const { login, password } = this.form.getRawValue();
    this.auth.login(login, password).subscribe({
      next: () => {
        this.auth.fetchProfile().subscribe();
        const next = this.route.snapshot.queryParamMap.get('next') ?? '/';
        this.router.navigateByUrl(next);
      },
      error: (err) => {
        this.pending.set(false);
        this.errorMessage.set(extractErrorMessage(err));
      },
    });
  }
}
