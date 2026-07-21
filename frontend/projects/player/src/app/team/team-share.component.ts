import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { JoinCodePayload, QrCodeComponent, TeamFormationService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-team-share',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [QrCodeComponent, RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-6">
        <h1 class="h3 mb-3">Share your team</h1>

        @if (error(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }

        @if (payload(); as p) {
          <div class="card">
            <div class="card-body text-center">
              <h2 class="h5 mb-3">{{ p.team_name }}</h2>
              @if (p.join_url; as url) {
                <lib-qr-code [value]="url" [size]="220" />
                <div class="input-group mt-3">
                  <input class="form-control" type="text" readonly [value]="url" />
                  <button type="button" class="btn btn-outline-secondary" (click)="copy(url)">
                    <i class="bi bi-clipboard"></i>
                    {{ copied() ? 'Copied!' : 'Copy' }}
                  </button>
                </div>
                <p class="form-text mt-2">
                  This QR / link is <strong>not tied to a person</strong> — anyone
                  holding it can use it, so feel free to forward it to your whole
                  group. Rotate it to invalidate every copy already out there.
                </p>
              } @else {
                <div class="alert alert-secondary mb-0">
                  The join code is currently revoked. Generate a new one to let
                  people join.
                </div>
              }
            </div>
            <div class="card-footer d-flex gap-2 justify-content-center">
              <button
                type="button"
                class="btn btn-sm btn-outline-primary"
                [disabled]="busy()"
                (click)="rotate()"
              >
                <i class="bi bi-arrow-repeat"></i> Rotate code
              </button>
              @if (p.join_code) {
                <button
                  type="button"
                  class="btn btn-sm btn-outline-danger"
                  [disabled]="busy()"
                  (click)="revoke()"
                >
                  <i class="bi bi-x-circle"></i> Revoke
                </button>
              }
            </div>
          </div>
          <div class="mt-3 text-center">
            <a class="btn btn-link" [routerLink]="['/team', id, 'requests']">
              Pending join requests
            </a>
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
export class TeamShareComponent {
  private readonly teamFormation = inject(TeamFormationService);
  private readonly route = inject(ActivatedRoute);

  protected readonly id = Number(this.route.snapshot.paramMap.get('id'));

  protected readonly payload = signal<JoinCodePayload | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly copied = signal(false);

  constructor() {
    this.teamFormation.joinCode(this.id).subscribe({
      next: (p) => this.payload.set(p),
      error: (err) => this.error.set(extractErrorMessage(err)),
    });
  }

  protected rotate(): void {
    this.busy.set(true);
    this.teamFormation.rotateJoinCode(this.id).subscribe({
      next: (p) => {
        this.payload.set(p);
        this.busy.set(false);
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(extractErrorMessage(err));
      },
    });
  }

  protected revoke(): void {
    this.busy.set(true);
    this.teamFormation.revokeJoinCode(this.id).subscribe({
      next: (p) => {
        this.payload.set(p);
        this.busy.set(false);
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(extractErrorMessage(err));
      },
    });
  }

  protected copy(url: string): void {
    navigator.clipboard?.writeText(url).then(() => {
      this.copied.set(true);
      setTimeout(() => this.copied.set(false), 2000);
    });
  }
}
