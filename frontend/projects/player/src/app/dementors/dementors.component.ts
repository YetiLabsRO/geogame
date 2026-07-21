import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  DementorMe,
  DementorsService,
  ProximityIdentityInfo,
  ProximityObservation,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

const POLL_INTERVAL_MS = 3_000;

/**
 * Player Dementors screen (mode-dementors-ble) — wireframe.
 *
 * Everything shown here is server state polled from /api/dementors/me/:
 * energy bar, WIZARD/DEMENTOR role badge and the live drain/gain pulse
 * that betrays an unseen dementor nearby. Real BLE advertise/scan is
 * owned by the native shell (Web Bluetooth cannot advertise), so this
 * page ships a debug simulator panel that exercises the same API
 * contract with synthetic reports.
 */
@Component({
  selector: 'app-dementors',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FormsModule],
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-7">
        <h1 class="h3 mb-3">Dementors</h1>

        @if (loadError(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }

        @if (me(); as m) {
          @if (!m.alive) {
            <div class="alert alert-dark">
              <i class="bi bi-emoji-dizzy me-1"></i>
              You have been drained completely and are out of play.
            </div>
          }

          <div class="card mb-3">
            <div class="card-body">
              <div class="d-flex justify-content-between align-items-center mb-2">
                <span
                  class="badge fs-6"
                  [class]="m.role === 'WIZARD' ? 'text-bg-primary' : 'text-bg-dark'"
                >
                  <i
                    class="bi me-1"
                    [class]="m.role === 'WIZARD' ? 'bi-stars' : 'bi-tornado'"
                  ></i>
                  {{ m.role === 'WIZARD' ? 'Wizard' : 'Dementor' }}
                </span>
                @switch (m.trend) {
                  @case ('DRAINING') {
                    <span class="text-danger fw-semibold">
                      <span class="spinner-grow spinner-grow-sm me-1"></span>
                      <i class="bi bi-arrow-down"></i>
                      Being drained! ({{ m.last_delta }})
                    </span>
                  }
                  @case ('GAINING') {
                    <span class="text-success fw-semibold">
                      <i class="bi bi-arrow-up"></i>
                      Gaining energy (+{{ m.last_delta }})
                    </span>
                  }
                  @default {
                    <span class="text-body-secondary">
                      <i class="bi bi-dash-lg"></i> Stable
                    </span>
                  }
                }
              </div>

              <div
                class="progress"
                style="height: 1.75rem"
                role="progressbar"
                [attr.aria-valuenow]="m.energy"
                aria-valuemin="0"
                [attr.aria-valuemax]="energyScale()"
              >
                <div
                  class="progress-bar"
                  [class]="energyBarClass()"
                  [class.progress-bar-striped]="m.trend !== 'STABLE'"
                  [class.progress-bar-animated]="m.trend !== 'STABLE'"
                  [style.width.%]="energyPercent()"
                >
                  {{ m.energy }} / {{ energyScale() }}
                </div>
              </div>
              <div class="small text-body-secondary mt-1">
                @if (m.role === 'DEMENTOR') {
                  Regain {{ m.conversion_threshold }} energy near groups of
                  wizards to turn back into a wizard.
                } @else {
                  If your energy reaches zero, the dementors take you.
                }
                Last update:
                @if (m.last_tick_at) {
                  {{ m.last_tick_at | date: 'HH:mm:ss' }}
                } @else {
                  —
                }
              </div>
            </div>
          </div>

          @if (m.reports_stale) {
            <div class="alert alert-warning d-flex align-items-center">
              <i class="bi bi-phone-vibrate fs-4 me-2"></i>
              <div>
                <strong>Keep your phone out and active!</strong>
                Bluetooth sensing only works while the app is open with
                the screen on. Your reports have gone stale — you are
                invisible to the game right now.
              </div>
            </div>
          } @else {
            <div class="alert alert-light border small mb-3">
              <i class="bi bi-broadcast me-1"></i>
              Keep your phone out with the screen on — that is how the
              magic senses who is around you, even through trees.
            </div>
          }
        } @else if (!loadError()) {
          <div class="d-flex align-items-center text-body-secondary">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading your fate…
          </div>
        }

        <div class="card border-secondary-subtle mb-3">
          <div class="card-header d-flex justify-content-between align-items-center">
            <span>
              <i class="bi bi-bug me-1"></i>
              BLE simulator (debug)
            </span>
            <button
              type="button"
              class="btn btn-sm btn-outline-secondary"
              (click)="simulatorOpen.set(!simulatorOpen())"
            >
              {{ simulatorOpen() ? 'Hide' : 'Show' }}
            </button>
          </div>
          @if (simulatorOpen()) {
            <div class="card-body">
              <p class="small text-body-secondary">
                Web browsers cannot advertise over BLE, so the real
                advertise/scan loop lives in the native app. This panel
                exercises the same server contract with synthetic
                reports.
              </p>

              @if (simulatorError(); as msg) {
                <div class="alert alert-danger py-2 small">{{ msg }}</div>
              }

              <div class="mb-3">
                <button
                  type="button"
                  class="btn btn-sm btn-outline-primary me-2"
                  (click)="requestIdentity(false)"
                >
                  Get advertising ID
                </button>
                <button
                  type="button"
                  class="btn btn-sm btn-outline-secondary"
                  [disabled]="!identity()"
                  (click)="requestIdentity(true)"
                >
                  Rotate
                </button>
                @if (identity(); as id) {
                  <div class="small mt-2">
                    Advertising as <code>{{ id.token }}</code>
                    · report every {{ id.report_interval_seconds }}s
                    · freshness window {{ id.freshness_window_seconds }}s
                  </div>
                }
              </div>

              <div class="row g-2 align-items-end mb-2">
                <div class="col-6">
                  <label class="form-label small mb-0" for="sim-token">Seen token</label>
                  <input
                    id="sim-token"
                    class="form-control form-control-sm"
                    placeholder="e.g. a1b2c3d4"
                    [(ngModel)]="observedToken"
                  />
                </div>
                <div class="col-3">
                  <label class="form-label small mb-0" for="sim-rssi">RSSI (dBm)</label>
                  <input
                    id="sim-rssi"
                    type="number"
                    class="form-control form-control-sm"
                    [(ngModel)]="observedRssi"
                  />
                </div>
                <div class="col-3">
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-secondary w-100"
                    (click)="addObservation()"
                  >
                    Add
                  </button>
                </div>
              </div>

              @if (observations().length > 0) {
                <ul class="list-group list-group-flush mb-2">
                  @for (obs of observations(); track $index) {
                    <li
                      class="list-group-item d-flex justify-content-between py-1 small"
                    >
                      <span><code>{{ obs.token }}</code> @ {{ obs.rssi }} dBm</span>
                      <button
                        type="button"
                        class="btn btn-sm btn-link text-danger py-0"
                        (click)="removeObservation($index)"
                      >
                        remove
                      </button>
                    </li>
                  }
                </ul>
              }

              <button
                type="button"
                class="btn btn-sm btn-primary"
                [disabled]="!identity() || sending()"
                (click)="sendReport()"
              >
                @if (sending()) {
                  <span class="spinner-border spinner-border-sm me-1"></span>
                }
                Send report ({{ observations().length }} seen)
              </button>
              @if (lastReport(); as r) {
                <span class="small text-body-secondary ms-2">
                  recorded {{ r.recorded }}, discarded {{ r.discarded }},
                  {{ r.events_derived }} pair(s) derived
                </span>
              }
            </div>
          }
        </div>
      </div>
    </div>
  `,
})
export class DementorsComponent {
  private readonly api = inject(DementorsService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly me = signal<DementorMe | null>(null);
  protected readonly loadError = signal<string | null>(null);

  protected readonly simulatorOpen = signal(false);
  protected readonly simulatorError = signal<string | null>(null);
  protected readonly identity = signal<ProximityIdentityInfo | null>(null);
  protected readonly observations = signal<ProximityObservation[]>([]);
  protected readonly sending = signal(false);
  protected readonly lastReport = signal<{
    recorded: number;
    discarded: number;
    events_derived: number;
  } | null>(null);

  protected observedToken = '';
  protected observedRssi = -60;

  protected readonly energyScale = computed(() => {
    const m = this.me();
    if (!m) return 100;
    return Math.max(
      m.starting_energy,
      m.conversion_threshold,
      Math.ceil(m.energy),
      1,
    );
  });

  protected readonly energyPercent = computed(() => {
    const m = this.me();
    if (!m) return 0;
    return Math.max(0, Math.min(100, (m.energy / this.energyScale()) * 100));
  });

  protected readonly energyBarClass = computed(() => {
    const m = this.me();
    if (!m) return 'bg-secondary';
    if (m.role === 'DEMENTOR') return 'bg-dark';
    const pct = this.energyPercent();
    if (pct <= 25) return 'bg-danger';
    if (pct <= 50) return 'bg-warning';
    return 'bg-success';
  });

  private pollHandle: ReturnType<typeof setInterval> | null = null;
  private wakeLock: { release(): Promise<void> } | null = null;
  private readonly onVisibility = () => {
    if (document.visibilityState === 'visible') this.acquireWakeLock();
  };

  constructor() {
    this.refresh();
    this.pollHandle = setInterval(() => this.refresh(), POLL_INTERVAL_MS);
    // BLE detection is foreground-only: keep the screen awake while the
    // Dementors screen is open (best-effort; unsupported browsers just
    // fall back to the "phone out" prompt).
    this.acquireWakeLock();
    document.addEventListener('visibilitychange', this.onVisibility);
    this.destroyRef.onDestroy(() => {
      if (this.pollHandle) clearInterval(this.pollHandle);
      document.removeEventListener('visibilitychange', this.onVisibility);
      this.wakeLock?.release().catch(() => {});
      this.wakeLock = null;
    });
  }

  private acquireWakeLock(): void {
    const wakeLockApi = (
      navigator as Navigator & {
        wakeLock?: { request(type: 'screen'): Promise<{ release(): Promise<void> }> };
      }
    ).wakeLock;
    wakeLockApi
      ?.request('screen')
      .then((lock) => (this.wakeLock = lock))
      .catch(() => {});
  }

  protected refresh(): void {
    this.api.me().subscribe({
      next: (m) => {
        this.me.set(m);
        this.loadError.set(null);
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected requestIdentity(rotate: boolean): void {
    this.simulatorError.set(null);
    this.api.identity(rotate).subscribe({
      next: (id) => this.identity.set(id),
      error: (err) => this.simulatorError.set(extractErrorMessage(err)),
    });
  }

  protected addObservation(): void {
    const token = this.observedToken.trim();
    if (!token) return;
    this.observations.update((list) => [
      ...list,
      { token, rssi: Number(this.observedRssi) },
    ]);
    this.observedToken = '';
  }

  protected removeObservation(index: number): void {
    this.observations.update((list) => list.filter((_, i) => i !== index));
  }

  protected sendReport(): void {
    this.simulatorError.set(null);
    this.sending.set(true);
    this.api.report(this.observations()).subscribe({
      next: (result) => {
        this.sending.set(false);
        this.lastReport.set(result);
        this.refresh();
      },
      error: (err) => {
        this.sending.set(false);
        this.simulatorError.set(extractErrorMessage(err));
      },
    });
  }
}
