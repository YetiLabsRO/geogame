import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { AuthService, JoinCodePreview, TeamFormationService, TeamJoinRequest } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-join-code',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-6">
        <h1 class="h3 mb-3">Join a team</h1>

        @if (error(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }

        @if (preview(); as p) {
          <div class="card">
            <div class="card-body text-center">
              <span class="badge mb-2" [style.background-color]="p.color">&nbsp;</span>
              <h2 class="h4">{{ p.team_name }}</h2>
              @if (p.team_group) {
                <div class="text-body-secondary">{{ p.team_group }}</div>
              }
              <div class="text-body-secondary small mb-3">
                {{ p.game_name }} · {{ p.session_name }}
              </div>

              @if (result(); as r) {
                @if (r.status === 'APPROVED') {
                  <div class="alert alert-success">
                    You joined <strong>{{ r.team_name }}</strong>!
                  </div>
                  <a class="btn btn-primary" routerLink="/">Go to the map</a>
                } @else {
                  <div class="alert alert-warning">
                    Your request is <strong>pending</strong> — the
                    {{ p.join_confirmation === 'STAFF' ? 'staff' : 'team captain' }}
                    must approve it.
                  </div>
                  <a class="btn btn-outline-secondary" routerLink="/teams">Browse teams</a>
                }
              } @else if (isAuthenticated()) {
                @if (p.join_confirmation !== 'AUTO_APPROVE') {
                  <p class="form-text">
                    This team confirms joins — your request will wait for approval.
                  </p>
                }
                <button
                  type="button"
                  class="btn btn-primary"
                  [disabled]="busy()"
                  (click)="join()"
                >
                  @if (busy()) {
                    <span class="spinner-border spinner-border-sm me-1"></span>
                  }
                  Join {{ p.team_name }}
                </button>
              } @else {
                <p>Sign in or create an account to join this team.</p>
                <a class="btn btn-primary me-2" routerLink="/login">Sign in</a>
                <a class="btn btn-outline-primary" routerLink="/register">Register</a>
              }
            </div>
          </div>
        } @else if (!error()) {
          <div class="d-flex align-items-center text-body-secondary">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading…
          </div>
        }
      </div>
    </div>
  `,
})
export class JoinCodeComponent {
  private readonly teamFormation = inject(TeamFormationService);
  private readonly auth = inject(AuthService);
  private readonly route = inject(ActivatedRoute);

  private readonly code = this.route.snapshot.paramMap.get('code') ?? '';

  protected readonly isAuthenticated = this.auth.isAuthenticated;
  protected readonly preview = signal<JoinCodePreview | null>(null);
  protected readonly result = signal<TeamJoinRequest | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);

  constructor() {
    this.teamFormation.joinCodePreview(this.code).subscribe({
      next: (p) => this.preview.set(p),
      error: (err) => this.error.set(extractErrorMessage(err)),
    });
  }

  protected join(): void {
    this.busy.set(true);
    this.error.set(null);
    this.teamFormation.requestJoin({ code: this.code }).subscribe({
      next: (r) => {
        this.busy.set(false);
        this.result.set(r);
        this.auth.fetchProfile().subscribe({ error: () => {} });
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(extractErrorMessage(err));
      },
    });
  }
}
