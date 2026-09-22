import { ChangeDetectionStrategy, Component, OnInit, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import {
  extractNfcToken,
  GameApiService,
  GeolocationService,
  HapticsService,
  NfcCaptureResponse,
  NfcService,
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
  imports: [FormsModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="container py-3" style="max-width: 32rem">
      <h4><i class="bi bi-broadcast-pin"></i> Scanează un tag</h4>

      @if (nfcSupported()) {
        <button class="btn btn-primary w-100 mb-2" (click)="startNfc()" [disabled]="scanning()">
          <i class="bi bi-phone-vibrate"></i>
          {{ scanning() ? 'Apropie telefonul de tag…' : 'Scanează prin NFC' }}
        </button>
      } @else {
        <div class="alert alert-secondary py-2">
          NFC nu este disponibil în acest browser — folosește camera (QR) sau introdu codul de pe
          tag.
        </div>
      }

      <form class="input-group mb-3" (ngSubmit)="capture(manualToken)">
        <input
          class="form-control"
          name="token"
          [(ngModel)]="manualToken"
          placeholder="Cod tag (fallback manual)"
        />
        <button class="btn btn-outline-primary" type="submit" [disabled]="!manualToken">
          Trimite
        </button>
      </form>

      @if (result(); as res) {
        <div
          class="alert"
          [class.alert-success]="res.outcome === 'CONFIRMED'"
          [class.alert-warning]="res.outcome === 'PENDING'"
          [class.alert-danger]="res.outcome.startsWith('REJECTED')"
        >
          <strong>{{ res.outcome }}</strong>
          @if (res.tower) {
            — {{ res.tower.name }}
          }
          @if (res.detail) {
            <div>{{ res.detail }}</div>
          }
        </div>
      }
      @if (error(); as err) {
        <div class="alert alert-danger">{{ err }}</div>
      }

      <p class="text-muted small">
        Scanarea funcționează doar din aplicație, de la locul unde este ascuns tagul (verificăm
        distanța prin GPS).
      </p>
      <a routerLink="/" class="btn btn-sm btn-outline-secondary">Înapoi la hartă</a>
    </div>
  `,
})
export class NfcScanComponent implements OnInit {
  /** Token from the deep link /nfc/:token (empty on the plain /scan route). */
  readonly token = input<string>('');

  private readonly api = inject(GameApiService);
  private readonly nfc = inject(NfcService);
  private readonly geolocation = inject(GeolocationService);
  private readonly haptics = inject(HapticsService);

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
      this.error.set('Scanarea NFC a eșuat — folosește codul manual sau camera.');
    }
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
            error: (err) => this.error.set(err?.error?.detail ?? 'Scanarea a fost respinsă.'),
          });
      })
      .catch(() => this.error.set('Nu am putut obține locația — activează GPS-ul.'));
  }
}
