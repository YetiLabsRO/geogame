import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import {
  DialogService,
  GameApiService,
  LocationConsentStatus,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiIconComponent,
  UiSpinnerComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';
import { LocationStreamService } from './location-stream.service';

/**
 * Location-consent gate (live-location capability).
 *
 * Presents the game's location rules and requires agreement before a
 * location-enabled Session can be played. Also the place to withdraw a
 * standing consent (which stops streaming and purges the session's
 * pings server-side).
 */
@Component({
  selector: 'app-location-consent',
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
    <div class="location-consent-page">
      <a routerLink="/" class="tr-button-label location-consent-page__back">&larr; Back to map</a>

      @if (loadError(); as msg) {
        <ui-alert tone="danger">{{ msg }}</ui-alert>
      } @else if (status(); as s) {
        @if (!s.tracking_enabled) {
          <ui-alert tone="info" [withIcon]="true">
            This session does not track live location. No consent is needed.
          </ui-alert>
        } @else {
          <ui-card class="location-consent-page__card">
            <span class="location-consent-page__icon">
              <ui-icon name="target" [size]="28" />
            </span>
            <h1 class="tr-h2 location-consent-page__title">Share your position</h1>
            <ui-chip [tone]="s.has_consent ? 'brand' : 'neutral'">
              {{ s.has_consent ? 'Sharing enabled' : 'Not shared' }}
            </ui-chip>
            <p class="tr-body" style="white-space: pre-line">
              {{ s.consent_text || defaultConsentText }}
            </p>
            <ul class="location-consent-page__list">
              <li class="tr-body">
                Your position is sent every {{ s.ping_interval_seconds }} seconds while you play —
                the frequency is set by the game and cannot be changed.
              </li>
              <li class="tr-body">
                You can withdraw at any time; streaming stops and your recorded positions for this
                session are deleted.
              </li>
            </ul>

            @if (actionError(); as msg) {
              <ui-alert tone="danger">{{ msg }}</ui-alert>
            }

            @if (s.has_consent) {
              <ui-alert tone="success" [withIcon]="true">
                You agreed to these rules
                @if (s.agreed_at; as at) {
                  on {{ formatDate(at) }}
                }.
              </ui-alert>
              <ui-button
                variant="secondary"
                [block]="true"
                [loading]="busy()"
                [disabled]="busy()"
                (pressed)="withdraw()"
              >
                Withdraw consent
              </ui-button>
            } @else {
              <ui-alert tone="warning">
                You must agree to the location rules before you can play this session.
              </ui-alert>
              <ui-button
                variant="primary"
                [block]="true"
                [loading]="busy()"
                [disabled]="busy()"
                (pressed)="agree()"
              >
                Allow while playing
              </ui-button>
              <a routerLink="/" class="tr-button-label location-consent-page__link">Not now</a>
            }
          </ui-card>
        }
      } @else {
        <div class="location-consent-page__loading">
          <ui-spinner [size]="20" />
          <span class="tr-body">Loading…</span>
        </div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .location-consent-page {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
      padding: var(--spacing-xl) var(--spacing-xl) var(--spacing-2xl);
      max-width: 480px;
      margin: 0 auto;
    }
    .location-consent-page__back {
      align-self: flex-start;
      color: var(--color-brand-onSurface);
      text-decoration: none;
    }
    .location-consent-page__card {
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: var(--spacing-sm);
    }
    .location-consent-page__icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 56px;
      height: 56px;
      border-radius: var(--radius-full);
      background: var(--color-brand-tint);
      color: var(--color-brand-onSurface);
    }
    .location-consent-page__title {
      color: var(--color-text-primary);
    }
    .location-consent-page__list {
      margin: 0;
      padding-left: var(--spacing-md);
      display: flex;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .location-consent-page__list .tr-body {
      color: var(--color-text-secondary);
    }
    .location-consent-page__link {
      align-self: center;
      color: var(--color-brand-onSurface);
      text-decoration: none;
    }
    .location-consent-page__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      margin-top: var(--spacing-xl);
      color: var(--color-text-secondary);
    }
  `,
})
export class LocationConsentComponent implements OnInit {
  private readonly api = inject(GameApiService);
  private readonly stream = inject(LocationStreamService);
  private readonly router = inject(Router);
  private readonly dialogs = inject(DialogService);

  protected readonly status = signal<LocationConsentStatus | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);
  protected readonly busy = signal(false);

  protected readonly defaultConsentText =
    'While this session runs, your live position is shared with the game ' +
    'server so organisers (and, depending on the game settings, your ' +
    'teammates) can see where you are.';

  ngOnInit(): void {
    this.refresh();
  }

  private refresh(): void {
    this.api.locationConsent().subscribe({
      next: (s) => this.status.set(s),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected agree(): void {
    if (this.busy()) return;
    this.busy.set(true);
    this.actionError.set(null);
    this.api.grantLocationConsent().subscribe({
      next: () => {
        this.busy.set(false);
        this.stream.markConsented();
        this.router.navigateByUrl('/');
      },
      error: (err) => {
        this.busy.set(false);
        this.actionError.set(extractErrorMessage(err));
      },
    });
  }

  protected async withdraw(): Promise<void> {
    if (this.busy()) return;
    const ok = await this.dialogs.confirm({
      title: 'Withdraw consent?',
      message:
        'Streaming stops and your recorded positions for this session are ' +
        'deleted. You cannot play a location-enabled session without consent.',
      confirmLabel: 'Withdraw consent',
      cancelLabel: 'Keep sharing',
      danger: true,
    });
    if (!ok) return;
    this.busy.set(true);
    this.actionError.set(null);
    this.api.withdrawLocationConsent().subscribe({
      next: () => {
        this.busy.set(false);
        this.stream.markWithdrawn();
        this.refresh();
      },
      error: (err) => {
        this.busy.set(false);
        this.actionError.set(extractErrorMessage(err));
      },
    });
  }

  protected formatDate(value: string): string {
    return new Date(value).toLocaleString();
  }
}
