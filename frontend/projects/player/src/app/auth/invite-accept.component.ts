import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { DatePipe } from '@angular/common';

import {
  AuthService,
  InvitePreview,
  InvitesService,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiFieldComponent,
  UiIconComponent,
  UiInputDirective,
  UiSpinnerComponent,
} from 'shared';

import { extractErrorMessage } from './form-error';

@Component({
  selector: 'app-invite-accept',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    RouterLink,
    DatePipe,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiFieldComponent,
    UiIconComponent,
    UiInputDirective,
    UiSpinnerComponent,
  ],
  template: `
    <div class="auth-page">
      <div class="auth-page__brand">
        <span class="auth-page__mark"><ui-icon name="compass" [size]="17" /></span>
        <span class="tr-eyebrow auth-page__eyebrow">Tower Rush</span>
      </div>
      <h1 class="tr-h1 auth-page__title">You've been invited</h1>

      @if (loadError(); as msg) {
        <ui-alert tone="danger" class="auth-page__card">{{ msg }}</ui-alert>
        <div class="auth-page__links">
          <a routerLink="/login" class="tr-button-label auth-page__link">Back to sign in</a>
        </div>
      } @else if (preview(); as p) {
        <ui-card eyebrow="Active invitation" [title]="p.team_name" class="auth-page__card">
          @if (p.team_group) {
            <p class="tr-body">{{ p.team_group }}</p>
          }
          <p class="tr-meta-tiny auth-page__expiry">Expires {{ p.expires_at | date: 'medium' }}</p>
        </ui-card>

        @if (isAuthenticated()) {
          <ui-card class="auth-page__card">
            @if (errorMessage(); as msg) {
              <ui-alert tone="danger">{{ msg }}</ui-alert>
            }
            <ui-button
              [block]="true"
              [loading]="pending()"
              [disabled]="pending()"
              (pressed)="acceptAsExistingUser()"
            >
              Accept invite
            </ui-button>
          </ui-card>
        } @else {
          <ui-card class="auth-page__card">
            <p class="tr-body">
              Create an account to accept this invite. Already have one?
              <a [routerLink]="['/login']" [queryParams]="{ next: currentUrl }" class="auth-page__inline-link"
                >Sign in</a
              >
              first.
            </p>
            <form [formGroup]="form" (ngSubmit)="acceptAsNewUser()" novalidate class="auth-page__form">
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
                Create account & accept
              </ui-button>
            </form>
          </ui-card>
        }
      } @else {
        <div class="auth-page__loading">
          <ui-spinner [size]="20" />
          <span class="tr-body">Loading invite…</span>
        </div>
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
      width: 100%;
      max-width: 420px;
    }
    .auth-page__expiry {
      color: var(--color-text-muted);
    }
    .auth-page__form {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
    }
    .auth-page__inline-link {
      color: var(--color-brand-onSurface);
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
    .auth-page__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      color: var(--color-text-secondary);
    }
  `,
})
export class InviteAcceptComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly auth = inject(AuthService);
  private readonly invites = inject(InvitesService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly isAuthenticated = this.auth.isAuthenticated;
  protected readonly preview = signal<InvitePreview | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly pending = signal(false);
  protected readonly errorMessage = signal<string | null>(null);

  protected readonly form = this.fb.group({
    username: ['', [Validators.required, Validators.maxLength(150)]],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(8)]],
    first_name: [''],
    last_name: [''],
  });

  private readonly token = this.route.snapshot.paramMap.get('token') ?? '';
  protected readonly currentUrl = `/invite/${this.token}`;

  constructor() {
    if (!this.token) {
      this.loadError.set('Invalid invite link.');
      return;
    }
    this.invites.preview(this.token).subscribe({
      next: (p) => this.preview.set(p),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected acceptAsExistingUser(): void {
    if (this.pending()) {
      return;
    }
    this.pending.set(true);
    this.errorMessage.set(null);
    this.invites.accept(this.token).subscribe({
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

  protected acceptAsNewUser(): void {
    if (this.form.invalid || this.pending()) {
      return;
    }
    this.pending.set(true);
    this.errorMessage.set(null);
    this.invites.accept(this.token, this.form.getRawValue()).subscribe({
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
