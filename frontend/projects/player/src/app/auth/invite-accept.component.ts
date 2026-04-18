import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { DatePipe } from '@angular/common';

import { AuthService, InvitePreview, InvitesService } from 'shared';

import { extractErrorMessage } from './form-error';

@Component({
  selector: 'app-invite-accept',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink, DatePipe],
  template: `
    <div class="row justify-content-center">
      <div class="col-md-7 col-lg-6">
        <h1 class="h3 mb-4">Team invite</h1>

        @if (loadError(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
          <a routerLink="/login" class="btn btn-outline-secondary">Back to sign in</a>
        } @else if (preview(); as p) {
          <div class="card mb-3">
            <div class="card-body">
              <div class="text-body-secondary small">You've been invited to join</div>
              <div class="fs-4 fw-semibold">{{ p.team_name }}</div>
              @if (p.team_group) {
                <div class="text-body-secondary">{{ p.team_group }}</div>
              }
              <div class="small text-body-secondary mt-2">
                Expires {{ p.expires_at | date: 'medium' }}
              </div>
            </div>
          </div>

          @if (isAuthenticated()) {
            @if (errorMessage(); as msg) {
              <div class="alert alert-danger py-2">{{ msg }}</div>
            }
            <button
              type="button"
              class="btn btn-primary w-100"
              [disabled]="pending()"
              (click)="acceptAsExistingUser()"
            >
              @if (pending()) {
                <span class="spinner-border spinner-border-sm me-2"></span>
              }
              Accept invite
            </button>
          } @else {
            <p class="text-body-secondary">
              Create an account to accept this invite. Already have one?
              <a routerLink="/login" [queryParams]="{ next: currentUrl }">Sign in</a> first.
            </p>
            <form [formGroup]="form" (ngSubmit)="acceptAsNewUser()" novalidate>
              <div class="mb-3">
                <label class="form-label" for="username">Username</label>
                <input
                  id="username"
                  type="text"
                  class="form-control"
                  formControlName="username"
                  autocomplete="username"
                />
              </div>
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
              <div class="row">
                <div class="col mb-3">
                  <label class="form-label" for="first_name">First name</label>
                  <input
                    id="first_name"
                    type="text"
                    class="form-control"
                    formControlName="first_name"
                    autocomplete="given-name"
                  />
                </div>
                <div class="col mb-3">
                  <label class="form-label" for="last_name">Last name</label>
                  <input
                    id="last_name"
                    type="text"
                    class="form-control"
                    formControlName="last_name"
                    autocomplete="family-name"
                  />
                </div>
              </div>
              <div class="mb-3">
                <label class="form-label" for="password">Password</label>
                <input
                  id="password"
                  type="password"
                  class="form-control"
                  formControlName="password"
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
                Create account & accept
              </button>
            </form>
          }
        } @else {
          <div class="d-flex align-items-center text-body-secondary">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading invite…
          </div>
        }
      </div>
    </div>
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
