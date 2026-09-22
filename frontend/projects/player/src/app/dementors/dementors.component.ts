import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';

import {
  BleProximityService,
  DementorMe,
  DementorsService,
  GameApiService,
  KeepAwakeService,
  ProximityIdentityInfo,
  ProximityObservation,
  REALTIME_EVENTS,
  RealtimeService,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiFieldComponent,
  UiInputDirective,
  UiProgressMeterComponent,
  UiSpinnerComponent,
  UiStatTileComponent,
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
  imports: [
    DatePipe,
    FormsModule,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiChipComponent,
    UiFieldComponent,
    UiInputDirective,
    UiProgressMeterComponent,
    UiSpinnerComponent,
    UiStatTileComponent,
  ],
  template: `
    <div class="dementors-page">
      <span class="tr-eyebrow dementors-page__eyebrow">Live role mode</span>
      <h1 class="tr-h1 dementors-page__title">Dementors</h1>

      @if (loadError(); as msg) {
        <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
      }

      @if (me(); as m) {
        @if (!m.alive) {
          <ui-alert tone="danger" [withIcon]="true">
            You have been drained completely and are out of play.
          </ui-alert>
        }

        <div class="dementors-page__role-row">
          <ui-chip
            [tone]="m.role === 'WIZARD' ? 'solid' : 'neutral'"
            [class.dementors-page__role-chip--dark]="m.role === 'DEMENTOR'"
            class="dementors-page__role-chip"
          >
            {{ m.role === 'WIZARD' ? 'Wizard' : 'Dementor' }}
          </ui-chip>
          @switch (m.trend) {
            @case ('DRAINING') {
              <span class="dementors-page__trend dementors-page__trend--drain">
                Being drained! ({{ m.last_delta }})
              </span>
            }
            @case ('GAINING') {
              <span class="dementors-page__trend dementors-page__trend--gain">
                Gaining energy (+{{ m.last_delta }})
              </span>
            }
            @default {
              <span class="dementors-page__trend">Stable</span>
            }
          }
        </div>

        <ui-progress-meter
          label="Energy"
          [valueLabel]="m.energy + ' / ' + energyScale()"
          [value]="m.energy"
          [max]="energyScale()"
          [tone]="energyPercent() > 50 ? 'success' : energyPercent() <= 25 ? 'danger' : 'brand'"
        />

        <div class="dementors-page__stats">
          <ui-stat-tile
            [icon]="m.trend === 'DRAINING' ? 'target' : m.trend === 'GAINING' ? 'sparkle' : 'compass'"
            label="Trend"
            [value]="
              m.trend === 'DRAINING'
                ? 'Draining (' + m.last_delta + ')'
                : m.trend === 'GAINING'
                  ? 'Gaining (+' + m.last_delta + ')'
                  : 'Stable'
            "
          />
          <ui-stat-tile
            icon="clock"
            label="Last update"
            [value]="(m.last_tick_at | date: 'HH:mm:ss') ?? '—'"
          />
        </div>

        @if (m.role === 'DEMENTOR') {
          <p class="tr-body dementors-page__hint">
            Regain {{ m.conversion_threshold }} energy near groups of wizards to turn back into a
            wizard.
          </p>
        } @else {
          <p class="tr-body dementors-page__hint">
            If your energy reaches zero, the dementors take you.
          </p>
        }

        @if (m.reports_stale) {
          <ui-alert tone="warning" [withIcon]="true">
            <strong>Keep your phone out and active!</strong>
            Bluetooth sensing only works while the app is open with the screen on. Your reports have
            gone stale — you are invisible to the game right now.
          </ui-alert>
        } @else {
          <ui-alert tone="info">
            Keep your phone out with the screen on — that is how the magic senses who is around you,
            even through trees.
          </ui-alert>
        }
      } @else if (!loadError()) {
        <div class="dementors-page__loading">
          <ui-spinner [size]="20" />
          <span class="tr-body">Loading your fate…</span>
        </div>
      }

      <ui-card variant="flat" class="dementors-page__simulator">
        <div class="dementors-page__simulator-header">
          <span class="tr-eyebrow">BLE simulator (debug)</span>
          <ui-button variant="secondary" size="sm" (pressed)="simulatorOpen.set(!simulatorOpen())">
            {{ simulatorOpen() ? 'Hide' : 'Show' }}
          </ui-button>
        </div>

        @if (simulatorOpen()) {
          <p class="tr-body">
            Web browsers cannot advertise over BLE, so the real advertise/scan loop lives in the
            native app. This panel exercises the same server contract with synthetic reports.
          </p>

          @if (simulatorError(); as msg) {
            <ui-alert tone="danger">{{ msg }}</ui-alert>
          }

          <div class="dementors-page__simulator-actions">
            <ui-button variant="secondary" size="sm" (pressed)="requestIdentity(false)">
              Get advertising ID
            </ui-button>
            <ui-button
              variant="secondary"
              size="sm"
              [disabled]="!identity()"
              (pressed)="requestIdentity(true)"
            >
              Rotate
            </ui-button>
          </div>
          @if (identity(); as id) {
            <p class="tr-meta-tiny dementors-page__identity">
              Advertising as {{ id.token }} · report every {{ id.report_interval_seconds }}s ·
              freshness window {{ id.freshness_window_seconds }}s
            </p>
          }

          <div class="dementors-page__simulator-fields">
            <ui-field label="Seen token">
              <input uiInput type="text" placeholder="e.g. a1b2c3d4" [(ngModel)]="observedToken" />
            </ui-field>
            <ui-field label="RSSI (dBm)">
              <input uiInput type="number" [(ngModel)]="observedRssi" />
            </ui-field>
            <ui-button variant="secondary" size="sm" (pressed)="addObservation()">Add</ui-button>
          </div>

          @if (observations().length > 0) {
            <div class="dementors-page__obs-list">
              @for (obs of observations(); track $index) {
                <div class="dementors-page__obs-row">
                  <span class="tr-body">{{ obs.token }} @ {{ obs.rssi }} dBm</span>
                  <button
                    type="button"
                    class="dementors-page__obs-remove tr-button-label"
                    (click)="removeObservation($index)"
                  >
                    Remove
                  </button>
                </div>
              }
            </div>
          }

          <ui-button
            variant="primary"
            size="sm"
            [loading]="sending()"
            [disabled]="!identity() || sending()"
            (pressed)="sendReport()"
          >
            Send report ({{ observations().length }} seen)
          </ui-button>
          @if (lastReport(); as r) {
            <p class="tr-meta-tiny dementors-page__report">
              recorded {{ r.recorded }}, discarded {{ r.discarded }}, {{ r.events_derived }} pair(s)
              derived
            </p>
          }
        }
      </ui-card>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .dementors-page {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
      padding: var(--spacing-xl) var(--spacing-xl) var(--spacing-2xl);
      max-width: 560px;
      margin: 0 auto;
    }
    .dementors-page__eyebrow {
      color: var(--color-brand-onSurface);
    }
    .dementors-page__title {
      color: var(--color-text-primary);
    }
    .dementors-page__role-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--spacing-sm);
    }
    .dementors-page__role-chip {
      padding: 10px 24px;
      font-size: 14px;
      line-height: 20px;
    }
    .dementors-page__role-chip--dark {
      background: var(--color-brand-deep);
      border-color: var(--color-brand-deep);
      color: #fff;
    }
    .dementors-page__trend {
      color: var(--color-text-secondary);
    }
    .dementors-page__trend--drain {
      color: var(--color-danger);
      font-weight: 600;
    }
    .dementors-page__trend--gain {
      color: var(--color-success);
      font-weight: 600;
    }
    .dementors-page__stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
      gap: var(--spacing-sm);
    }
    .dementors-page__hint {
      color: var(--color-text-secondary);
    }
    .dementors-page__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      color: var(--color-text-secondary);
    }
    .dementors-page__simulator {
      margin-top: var(--spacing-sm);
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .dementors-page__simulator-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
    }
    .dementors-page__simulator-actions {
      display: flex;
      flex-wrap: wrap;
      gap: var(--spacing-xs);
    }
    .dementors-page__identity,
    .dementors-page__report {
      color: var(--color-text-muted);
    }
    .dementors-page__simulator-fields {
      display: flex;
      flex-wrap: wrap;
      align-items: flex-end;
      gap: var(--spacing-xs);
    }
    .dementors-page__simulator-fields ui-field {
      flex: 1;
      min-width: 120px;
    }
    .dementors-page__obs-list {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .dementors-page__obs-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
      padding: var(--spacing-xs) var(--spacing-sm);
      border-radius: var(--radius-md);
      background: var(--color-bg-raised);
      border: 1px solid var(--color-border-subtle);
    }
    .dementors-page__obs-remove {
      border: none;
      background: transparent;
      padding: 0;
      color: var(--color-danger);
      cursor: pointer;
    }
  `,
})
export class DementorsComponent {
  private readonly api = inject(DementorsService);
  private readonly gameApi = inject(GameApiService);
  private readonly keepAwake = inject(KeepAwakeService);
  private readonly ble = inject(BleProximityService);
  protected readonly realtime = inject(RealtimeService);
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
    return Math.max(m.starting_energy, m.conversion_threshold, Math.ceil(m.energy), 1);
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
  private seenConnections = 0;

  // mode-dementors-ble 2.10: native BLE advertise/scan wiring — see initBle().
  private bleCapable = false;
  private readonly bleObservations = new Map<string, { rssi: number; seenAt: number }>();
  private bleReportHandle: ReturnType<typeof setInterval> | null = null;
  private bleRotationHandle: ReturnType<typeof setTimeout> | null = null;
  private bleAdvertisingToken: string | null = null;

  constructor() {
    this.refresh();
    this.connectRealtime();
    // Polling stays as the graceful fallback: skip the periodic refresh
    // while the realtime socket is delivering tick snapshots (5.3).
    this.pollHandle = setInterval(() => {
      if (!this.realtime.connected()) this.refresh();
    }, POLL_INTERVAL_MS);

    // Reconcile from a fresh /me/ snapshot after every reconnect.
    effect(() => {
      const count = this.realtime.connections();
      if (count > this.seenConnections && this.seenConnections > 0) {
        this.refresh();
      }
      this.seenConnections = Math.max(this.seenConnections, count);
    });

    // 5.3 — a server economy tick pushes a role/energy snapshot; pull our
    // own authoritative /me/ view (trend + report-staleness are computed
    // there per player, not carried in the session-wide broadcast).
    this.realtime
      .eventsOfType(REALTIME_EVENTS.dementorTick)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.refresh());

    // BLE detection is foreground-only: keep the screen awake while the
    // Dementors screen is open (best-effort; unsupported platforms just
    // fall back to the "phone out" prompt).
    void this.keepAwake.keepAwake();
    void this.initBle();
    this.destroyRef.onDestroy(() => {
      if (this.pollHandle) clearInterval(this.pollHandle);
      void this.keepAwake.allowSleep();
      void this.teardownBle();
      this.realtime.disconnect();
    });
  }

  private connectRealtime(): void {
    this.gameApi.currentSession().subscribe({
      next: (session) => this.realtime.connect(session.id, session.realtime_enabled),
      error: () => {},
    });
  }

  /**
   * mode-dementors-ble 2.10: when the native BLE bridge reports capable,
   * drive the real advertise/scan loop instead of the manual simulator —
   * the simulator panel stays available underneath either way. Reports
   * are deduped by token (strongest RSSI wins) and flushed on the
   * server's `report_interval_seconds` cadence; advertising rotates
   * whenever the identity does (`rotates_at`).
   */
  private async initBle(): Promise<void> {
    let capable = false;
    try {
      capable = await this.ble.capable();
    } catch {
      capable = false;
    }
    this.bleCapable = capable;
    this.api.capability(capable).subscribe({ error: () => {} });
    if (!capable) return;

    await this.acquireIdentityAndAdvertise(false);
    await this.ble.startScan((token, rssi) => {
      const existing = this.bleObservations.get(token);
      if (!existing || rssi > existing.rssi) {
        this.bleObservations.set(token, { rssi, seenAt: Date.now() });
      }
    });
  }

  private async acquireIdentityAndAdvertise(rotate: boolean): Promise<void> {
    const id = await firstValueFrom(this.api.identity(rotate));
    this.identity.set(id);

    if (this.bleAdvertisingToken) {
      await this.ble.stopAdvertising();
    }
    this.bleAdvertisingToken = id.token;
    await this.ble.startAdvertising(id.token);

    if (this.bleReportHandle) clearInterval(this.bleReportHandle);
    this.bleReportHandle = setInterval(
      () => this.flushBleObservations(),
      id.report_interval_seconds * 1000,
    );

    if (this.bleRotationHandle) clearTimeout(this.bleRotationHandle);
    if (id.rotates_at) {
      const delay = Math.max(0, new Date(id.rotates_at).getTime() - Date.now());
      this.bleRotationHandle = setTimeout(() => {
        void this.acquireIdentityAndAdvertise(true);
      }, delay);
    }
  }

  private flushBleObservations(): void {
    if (this.bleObservations.size === 0) return;
    const observations: ProximityObservation[] = Array.from(
      this.bleObservations,
      ([token, seen]) => ({ token, rssi: seen.rssi }),
    );
    this.bleObservations.clear();
    this.api.report(observations).subscribe({
      next: (result) => this.lastReport.set(result),
      error: () => {},
    });
  }

  private async teardownBle(): Promise<void> {
    if (this.bleReportHandle) clearInterval(this.bleReportHandle);
    if (this.bleRotationHandle) clearTimeout(this.bleRotationHandle);
    if (!this.bleCapable) return;
    await this.ble.stopScan().catch(() => {});
    await this.ble.stopAdvertising().catch(() => {});
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
    this.observations.update((list) => [...list, { token, rssi: Number(this.observedRssi) }]);
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
