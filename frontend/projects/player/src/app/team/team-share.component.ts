import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  JoinCodePayload,
  QrCodeComponent,
  TeamFormationService,
  ToastService,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiIconComponent,
  UiSpinnerComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-team-share',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    QrCodeComponent,
    RouterLink,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiIconComponent,
    UiSpinnerComponent,
  ],
  template: `
    <div class="team-screen">
      @if (error(); as msg) {
        <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
      }

      @if (payload(); as p) {
        <ui-card class="team-screen__share-panel">
          <h1 class="tr-h2 team-screen__share-title">{{ p.team_name }}</h1>

          @if (p.join_url; as url) {
            <div class="team-screen__qr">
              <lib-qr-code [value]="url" [size]="220" />
            </div>

            @if (p.join_code; as code) {
              <span class="team-screen__code tr-h2">{{ code }}</span>
            }

            <ui-button variant="secondary" [block]="true" (pressed)="copy(url)">
              Copy link
            </ui-button>

            <p class="tr-meta-tiny team-screen__hint">
              This QR / link is not tied to a person — anyone holding it can use it, so feel free
              to forward it to your whole group. Rotate it to invalidate every copy already out
              there.
            </p>
          } @else {
            <ui-alert tone="warning" [withIcon]="true">
              The join code is currently revoked. Generate a new one to let people join.
            </ui-alert>
          }

          <div cardActions class="team-screen__share-footer">
            <ui-button
              variant="secondary"
              size="sm"
              [loading]="busy()"
              (pressed)="rotate()"
            >
              Rotate code
            </ui-button>
            @if (p.join_code) {
              <ui-button
                variant="secondary"
                size="sm"
                [loading]="busy()"
                (pressed)="revoke()"
              >
                Revoke
              </ui-button>
            }
          </div>
        </ui-card>

        <a class="team-screen__requests-link" [routerLink]="['/team', id, 'requests']">
          <span class="tr-body" style="color: var(--color-brand-onSurface)">
            Pending join requests
          </span>
          <ui-icon name="arrow-right" [size]="18" />
        </a>
      } @else if (!error()) {
        <div class="team-screen__loading">
          <ui-spinner />
          <span class="tr-body">Loading…</span>
        </div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .team-screen {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
      padding: var(--spacing-2xl) var(--spacing-xl) var(--spacing-3xl);
    }
    ui-card.team-screen__share-panel {
      align-items: center;
      text-align: center;
      max-width: 420px;
      width: 100%;
      margin-inline: auto;
    }
    .team-screen__share-title {
      color: var(--color-text-primary);
    }
    .team-screen__qr {
      padding: var(--spacing-md);
      border-radius: var(--radius-lg);
      background: #fff;
    }
    .team-screen__code {
      color: var(--color-brand-onSurface);
      font-family: ui-monospace, monospace;
      letter-spacing: 0.1em;
    }
    .team-screen__share-footer {
      display: flex;
      gap: var(--spacing-sm);
      width: 100%;
    }
    .team-screen__share-footer > * {
      flex: 1;
    }
    .team-screen__hint {
      color: var(--color-text-muted);
    }
    .team-screen__requests-link {
      display: flex;
      align-items: center;
      justify-content: center;
      gap: var(--spacing-2xs);
      max-width: 420px;
      width: 100%;
      margin-inline: auto;
      padding-block: var(--spacing-sm);
      text-decoration: none;
    }
  `,
})
export class TeamShareComponent {
  private readonly teamFormation = inject(TeamFormationService);
  private readonly route = inject(ActivatedRoute);
  private readonly toast = inject(ToastService);

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
      this.toast.show('Link copied', { tone: 'success' });
      setTimeout(() => this.copied.set(false), 2000);
    });
  }
}
