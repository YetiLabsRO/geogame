import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  inject,
  signal,
} from '@angular/core';
import { Router, RouterLink } from '@angular/router';

import { GameApiService, LocationConsentStatus } from 'shared';

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
  imports: [RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-md-8 col-lg-6">
        <a routerLink="/" class="small text-body-secondary">&larr; Back to map</a>
        <h1 class="h3 mt-2 mb-3">
          <i class="bi bi-geo-alt"></i> Location tracking
        </h1>

        @if (loadError(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        } @else if (status(); as s) {
          @if (!s.tracking_enabled) {
            <div class="alert alert-info">
              This session does not track live location. No consent is needed.
            </div>
          } @else {
            <div class="card mb-3">
              <div class="card-body">
                <h2 class="h6">This game's location rules</h2>
                <p class="mb-2" style="white-space: pre-line">
                  {{ s.consent_text || defaultConsentText }}
                </p>
                <ul class="small text-body-secondary mb-0">
                  <li>
                    Your position is sent every
                    {{ s.ping_interval_seconds }} seconds while you play —
                    the frequency is set by the game and cannot be changed.
                  </li>
                  <li>
                    You can withdraw at any time; streaming stops and your
                    recorded positions for this session are deleted.
                  </li>
                </ul>
              </div>
            </div>

            @if (actionError(); as msg) {
              <div class="alert alert-danger py-2">{{ msg }}</div>
            }

            @if (s.has_consent) {
              <div class="alert alert-success">
                <i class="bi bi-check-circle"></i>
                You agreed to these rules
                @if (s.agreed_at; as at) {
                  on {{ formatDate(at) }}
                }.
              </div>
              <button
                type="button"
                class="btn btn-outline-danger w-100"
                [disabled]="busy()"
                (click)="withdraw()"
              >
                @if (busy()) {
                  <span class="spinner-border spinner-border-sm me-2"></span>
                }
                Withdraw consent (deletes my positions)
              </button>
            } @else {
              <div class="alert alert-warning small">
                You must agree to the location rules before you can play this
                session.
              </div>
              <button
                type="button"
                class="btn btn-primary w-100"
                [disabled]="busy()"
                (click)="agree()"
              >
                @if (busy()) {
                  <span class="spinner-border spinner-border-sm me-2"></span>
                }
                I agree — start playing
              </button>
            }
          }
        } @else {
          <div class="d-flex align-items-center text-body-secondary mt-4">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading…
          </div>
        }
      </div>
    </div>
  `,
})
export class LocationConsentComponent implements OnInit {
  private readonly api = inject(GameApiService);
  private readonly stream = inject(LocationStreamService);
  private readonly router = inject(Router);

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

  protected withdraw(): void {
    if (this.busy()) return;
    const ok = window.confirm(
      'Withdraw consent? Streaming stops and your recorded positions for ' +
        'this session are deleted. You cannot play a location-enabled ' +
        'session without consent.',
    );
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
