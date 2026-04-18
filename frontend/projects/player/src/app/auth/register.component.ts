import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from 'shared';

import { extractErrorMessage } from './form-error';

@Component({
  selector: 'app-register',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-md-6 col-lg-5">
        <h1 class="h3 mb-4">Create an account</h1>
        <form [formGroup]="form" (ngSubmit)="submit()" novalidate>
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
            Create account
          </button>
        </form>

        <div class="mt-3 small">
          Already have an account? <a routerLink="/login">Sign in</a>
        </div>
      </div>
    </div>
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
