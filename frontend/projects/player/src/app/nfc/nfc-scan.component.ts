import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  extractNfcToken,
  GameApiService,
  GeolocationService,
  HapticsService,
  NfcCaptureResponse,
  NfcService,
  ToastService,
  UiAlertComponent,
  UiAlertTone,
  UiButtonComponent,
  UiCardComponent,
  UiFieldComponent,
  UiIconComponent,
  UiInputDirective,
} from 'shared';

/**
 * nfc-native-and-secure-links: player scan flow (wireframe).
 *
 * Transports, all resolving to the same token capture call:
 * - `NfcService` — Web NFC `NDEFReader` where the platform supports it
 *   (Android Chrome), the native `@exxili/capacitor-nfc` bridge inside
 *   the Capacitor shell (iOS + Android);
 * - the app-link deep link (`/nfc/:token`) when the native shell / OS
 *   routes a tag tap straight into the SPA with the token in the URL;
 * - manual code entry as the universal fallback (iOS browsers etc.).
 * A camera-QR scan lands on the same app-link URL, which is this route.
 */
@Component({
  selector: 'app-nfc-scan',
  standalone: true,
  imports: [
    FormsModule,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiFieldComponent,
    UiIconComponent,
    UiInputDirective,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="nfc-screen">
      <ui-card class="nfc-panel">
        <div class="nfc-icon"><ui-icon name="key" [size]="40" /></div>
        <h2 class="tr-h2 nfc-title">Scan the tag</h2>
        <p class="tr-body nfc-instructions">
          Hold your phone near the tag hidden at this tower — we verify your distance by GPS.
        </p>

        @if (nfcSupported()) {
          <ui-button
            variant="primary"
            [block]="true"
            icon="key"
            [loading]="scanning()"
            (pressed)="startNfc()"
          >
            {{ scanning() ? 'Hold your phone near the tag…' : 'Start scanning' }}
          </ui-button>
        } @else {
          <ui-alert tone="info" [withIcon]="true">
            NFC isn't available in this browser — use the camera (QR) or enter the code below.
          </ui-alert>
        }

        <ui-button variant="tinted" [block]="true" icon="camera" (pressed)="explainQr()">
          Scan QR instead
        </ui-button>

        <form class="nfc-manual" (ngSubmit)="capture(manualToken)">
          <ui-field label="Manual code">
            <input
              uiInput
              type="text"
              name="token"
              [(ngModel)]="manualToken"
              placeholder="Tag code"
              autocomplete="off"
            />
          </ui-field>
          <ui-button type="submit" variant="secondary" [disabled]="!manualToken">Send</ui-button>
        </form>

        @if (result(); as res) {
          <ui-alert [tone]="resultTone(res)" [withIcon]="true">
            <strong>{{ res.outcome }}</strong>
            @if (res.tower) {
              — {{ res.tower.name }}
            }
            @if (res.detail) {
              <div>{{ res.detail }}</div>
            }
          </ui-alert>
        }
        @if (error(); as err) {
          <ui-alert tone="danger" [withIcon]="true">{{ err }}</ui-alert>
        }

        <p class="tr-meta-tiny nfc-footnote">
          Scanning only works from inside the app, at the tower where the tag is hidden.
        </p>
      </ui-card>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .nfc-screen {
      display: flex;
      justify-content: center;
    }
    .nfc-panel {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--spacing-md);
      width: 100%;
      max-width: 28rem;
      text-align: center;
    }
    .nfc-icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 72px;
      height: 72px;
      border-radius: var(--radius-full);
      background: var(--color-brand-tint);
      color: var(--color-brand-onSurface);
    }
    .nfc-title {
      color: var(--color-text-primary);
    }
    .nfc-instructions {
      color: var(--color-text-secondary);
    }
    .nfc-manual {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
      width: 100%;
    }
    .nfc-footnote {
      color: var(--color-text-muted);
    }
  `,
})
export class NfcScanComponent implements OnInit {
  /** Token from the deep link /nfc/:token (empty on the plain /scan route). */
  readonly token = input<string>('');

  private readonly api = inject(GameApiService);
  private readonly nfc = inject(NfcService);
  private readonly geolocation = inject(GeolocationService);
  private readonly haptics = inject(HapticsService);
  private readonly toast = inject(ToastService);

  readonly scanning = signal(false);
  readonly result = signal<NfcCaptureResponse | null>(null);
  readonly error = signal<string | null>(null);
  manualToken = '';

  private abortController: AbortController | null = null;

  ngOnInit(): void {
    // Deep-linked from an app-link / QR scan: capture immediately.
    if (this.token()) {
      this.capture(this.token());
    }
  }

  nfcSupported(): boolean {
    return this.nfc.supported;
  }

  async startNfc(): Promise<void> {
    this.error.set(null);
    this.scanning.set(true);
    this.abortController = new AbortController();
    try {
      const token = await this.nfc.scan(this.abortController.signal);
      this.scanning.set(false);
      this.capture(token);
    } catch {
      this.scanning.set(false);
      this.error.set('NFC scan failed — use the manual code or camera instead.');
    }
  }

  /** "Scan QR instead" has no in-app camera UI — a QR tag deep-links
   *  straight back into this route via the OS camera, so this just
   *  points the player at that flow. */
  protected explainQr(): void {
    this.toast.show('Open your camera app and point it at the tag — it will bring you back here.', {
      tone: 'brand',
    });
  }

  protected resultTone(res: NfcCaptureResponse): UiAlertTone {
    if (res.outcome === 'CONFIRMED') return 'success';
    if (res.outcome === 'PENDING') return 'warning';
    if (res.outcome.startsWith('REJECTED')) return 'danger';
    return 'info';
  }

  capture(rawToken: string): void {
    const token = extractNfcToken([{ payload: rawToken }]) ?? rawToken.trim();
    if (!token) return;
    this.error.set(null);
    this.result.set(null);
    this.geolocation
      .current({ enableHighAccuracy: true, maximumAge: 5000, timeout: 15000 })
      .then((pos) => {
        this.api
          .nfcCapture({
            token,
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
          })
          .subscribe({
            next: (res) => {
              this.result.set(res);
              if (res.outcome === 'CONFIRMED') {
                this.haptics.notify('success');
              }
            },
            error: (err) => this.error.set(err?.error?.detail ?? 'Scan was rejected.'),
          });
      })
      .catch(() => this.error.set('Could not get your location — turn on GPS.'));
  }
}
