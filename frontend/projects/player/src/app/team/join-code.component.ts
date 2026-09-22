import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  AuthService,
  JoinCodePreview,
  TeamFormationService,
  TeamJoinRequest,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiIconComponent,
  UiSpinnerComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-join-code',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiChipComponent,
    UiIconComponent,
    UiSpinnerComponent,
  ],
  template: `
    <div class="team-screen">
      <ui-card class="team-screen__join-panel">
        <div class="team-screen__join-icon">
          <ui-icon name="key" [size]="28" />
        </div>
        <h1 class="tr-h2 team-screen__join-title">Join with a code</h1>

        @if (error(); as msg) {
          <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
        }

        @if (preview(); as p) {
          <div class="team-screen__join-preview">
            <ui-chip [teamColor]="p.color">{{ p.team_name }}</ui-chip>
            @if (p.team_group) {
              <span class="tr-body" style="color: var(--color-text-secondary)">
                {{ p.team_group }}
              </span>
            }
            <span class="tr-meta-tiny" style="color: var(--color-text-muted)">
              {{ p.game_name }} · {{ p.session_name }}
            </span>
          </div>

          @if (result(); as r) {
            @if (r.status === 'APPROVED') {
              <ui-alert tone="success" [withIcon]="true">
                You joined <strong>{{ r.team_name }}</strong>!
              </ui-alert>
              <ui-button variant="primary" [block]="true" routerLink="/">Go to the map</ui-button>
            } @else {
              <ui-alert tone="warning" [withIcon]="true">
                Your request is pending — the
                {{ p.join_confirmation === 'STAFF' ? 'staff' : 'team captain' }}
                must approve it.
              </ui-alert>
              <ui-button variant="secondary" [block]="true" routerLink="/teams">
                Browse societies
              </ui-button>
            }
          } @else if (isAuthenticated()) {
            @if (p.join_confirmation !== 'AUTO_APPROVE') {
              <p class="tr-body" style="color: var(--color-text-secondary)">
                This team confirms joins — your request will wait for approval.
              </p>
            }
            <ui-button
              variant="primary"
              [block]="true"
              [loading]="busy()"
              (pressed)="join()"
            >
              Join {{ p.team_name }}
            </ui-button>
          } @else {
            <p class="tr-body" style="color: var(--color-text-secondary)">
              Sign in or create an account to join this team.
            </p>
            <ui-button variant="primary" [block]="true" routerLink="/login">Sign in</ui-button>
            <ui-button variant="secondary" [block]="true" routerLink="/register">
              Register
            </ui-button>
          }
        } @else if (!error()) {
          <div class="team-screen__loading">
            <ui-spinner />
            <span class="tr-body">Loading…</span>
          </div>
        }
      </ui-card>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .team-screen {
      display: flex;
      flex-direction: column;
      padding: var(--spacing-2xl) var(--spacing-xl) var(--spacing-3xl);
    }
    ui-card.team-screen__join-panel {
      align-items: center;
      text-align: center;
      max-width: 420px;
      width: 100%;
      margin-inline: auto;
    }
    .team-screen__join-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 56px;
      height: 56px;
      border-radius: var(--radius-full);
      background: var(--color-brand-tint);
      color: var(--color-brand-onSurface);
    }
    .team-screen__join-title {
      color: var(--color-text-primary);
    }
    .team-screen__join-preview {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--spacing-2xs);
    }
    .team-screen__loading {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: var(--spacing-xs);
      color: var(--color-text-secondary);
      padding-block: var(--spacing-xl);
    }
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
