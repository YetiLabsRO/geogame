import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import { AuthService } from 'shared';

import { extractErrorMessage } from './form-error';

@Component({
  selector: 'app-login',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-md-6 col-lg-5">
        <h1 class="h3 mb-4">Sign in</h1>
        <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
          <div class="mb-3">
            <label class="form-label" for="login">Username or email</label>
            <input
              id="login"
              type="text"
              class="form-control"
              formControlName="login"
              autocomplete="username"
            />
          </div>
          <div class="mb-3">
            <label class="form-label" for="password">Password</label>
            <input
              id="password"
              type="password"
              class="form-control"
              formControlName="password"
              autocomplete="current-password"
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
            Sign in
          </button>
        </form>

        <div class="mt-3 d-flex justify-content-between small">
          <a routerLink="/reset">Forgot your password?</a>
          <a routerLink="/register">Create an account</a>
        </div>
      </div>
    </div>
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
