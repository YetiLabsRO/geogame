import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { BadgeRow, BadgesService, GatewayRow } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

const POLL_INTERVAL_MS = 10_000;

/**
 * Badge fleet panel (wearable-badge-hardware) — wireframe.
 *
 * Inventory of physical badges (assignment, battery, firmware,
 * last-seen with stale/low/un-returned flags), hand-out / collect
 * actions, plus a gateway health row. Registration forms for both
 * device kinds. Polls every 10s so battery/last-seen stay current
 * while gateways are relaying.
 */
@Component({
  selector: 'app-admin-badges',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FormsModule],
  template: `
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div>
        <h1 class="h3 mb-0">Badge fleet</h1>
        <div class="small text-body-secondary">
          Wearable ESP32-C3 badges + gateway relays · refreshes every 10s
        </div>
      </div>
      <button
        type="button"
        class="btn btn-sm btn-outline-secondary"
        [disabled]="loading()"
        (click)="refresh()"
      >
        @if (loading()) {
          <span class="spinner-border spinner-border-sm me-1"></span>
        }
        Refresh now
      </button>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }
    @if (actionError(); as msg) {
      <div class="alert alert-warning alert-dismissible">
        {{ msg }}
        <button type="button" class="btn-close" (click)="actionError.set(null)"></button>
      </div>
    }

    <div class="card mb-4">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span><i class="bi bi-smartwatch me-1"></i>Badges</span>
        <form class="d-flex gap-2" (ngSubmit)="registerBadge()">
          <input
            class="form-control form-control-sm"
            type="text"
            placeholder="MAC (optional)"
            name="newBadgeMac"
            [(ngModel)]="newBadgeMac"
          />
          <button type="submit" class="btn btn-sm btn-primary text-nowrap">
            Register badge
          </button>
        </form>
      </div>
      <div class="card-body p-0">
        @if (badges().length === 0) {
          <div class="p-3 text-body-secondary">No badges registered yet.</div>
        } @else {
          <div class="table-responsive">
            <table class="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>Badge id</th>
                  <th>Status</th>
                  <th>Assigned to</th>
                  <th class="text-end">Battery</th>
                  <th>Firmware</th>
                  <th>Last seen</th>
                  <th class="text-end">Actions</th>
                </tr>
              </thead>
              <tbody>
                @for (b of badges(); track b.id) {
                  <tr [class.table-warning]="b.unreturned">
                    <td class="font-monospace">{{ b.badge_id }}</td>
                    <td>
                      @switch (b.status) {
                        @case ('AVAILABLE') {
                          <span class="badge text-bg-success">available</span>
                        }
                        @case ('ASSIGNED') {
                          <span class="badge text-bg-primary">assigned</span>
                        }
                        @case ('LOST') {
                          <span class="badge text-bg-danger">lost</span>
                        }
                        @case ('RETIRED') {
                          <span class="badge text-bg-secondary">retired</span>
                        }
                        @default {
                          <span class="badge text-bg-secondary">{{ b.status }}</span>
                        }
                      }
                      @if (b.unreturned) {
                        <span class="badge text-bg-warning ms-1">un-returned</span>
                      }
                    </td>
                    <td>
                      @if (b.assignment; as a) {
                        <span class="fw-semibold">{{ a.player ?? a.team ?? '—' }}</span>
                        <span class="text-body-secondary small ms-1">
                          {{ a.session }}
                        </span>
                      } @else {
                        <span class="text-body-secondary">—</span>
                      }
                    </td>
                    <td class="text-end">
                      @if (b.battery_pct !== null) {
                        <span [class.text-danger]="b.battery_low">
                          @if (b.battery_low) {
                            <i class="bi bi-battery me-1"></i>
                          }
                          {{ b.battery_pct }}%
                        </span>
                      } @else {
                        <span class="text-body-secondary">—</span>
                      }
                    </td>
                    <td>
                      {{ b.firmware_version || '—' }}
                      @if (b.firmware_stale) {
                        <span class="badge text-bg-warning ms-1">stale fw</span>
                      }
                    </td>
                    <td class="small">
                      @if (b.last_seen_at) {
                        {{ b.last_seen_at | date: 'HH:mm:ss' }}
                      } @else {
                        <span class="text-body-secondary">never</span>
                      }
                      @if (b.stale) {
                        <i
                          class="bi bi-wifi-off text-danger ms-1"
                          title="No report in the last 10 minutes"
                        ></i>
                      }
                    </td>
                    <td class="text-end">
                      @if (b.assignment) {
                        <div class="d-flex gap-1 justify-content-end">
                          <button
                            type="button"
                            class="btn btn-sm btn-outline-primary"
                            (click)="collect(b, false)"
                          >
                            Collect
                          </button>
                          <button
                            type="button"
                            class="btn btn-sm btn-outline-danger"
                            (click)="collect(b, true)"
                          >
                            Lost
                          </button>
                        </div>
                      } @else if (assigningId() === b.id) {
                        <form
                          class="d-flex gap-1 justify-content-end"
                          (ngSubmit)="assign(b)"
                        >
                          <input
                            class="form-control form-control-sm"
                            style="max-width: 7rem"
                            type="number"
                            placeholder="player id"
                            name="assignPlayerId"
                            [(ngModel)]="assignPlayerId"
                          />
                          <input
                            class="form-control form-control-sm"
                            style="max-width: 7rem"
                            type="number"
                            placeholder="team id"
                            name="assignTeamId"
                            [(ngModel)]="assignTeamId"
                          />
                          <button type="submit" class="btn btn-sm btn-primary">
                            Bind
                          </button>
                          <button
                            type="button"
                            class="btn btn-sm btn-outline-secondary"
                            (click)="assigningId.set(null)"
                          >
                            ×
                          </button>
                        </form>
                      } @else {
                        <button
                          type="button"
                          class="btn btn-sm btn-outline-success"
                          [disabled]="b.status === 'LOST' || b.status === 'RETIRED'"
                          (click)="startAssign(b)"
                        >
                          Hand out
                        </button>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </div>
    </div>

    <div class="card">
      <div class="card-header d-flex justify-content-between align-items-center">
        <span><i class="bi bi-router me-1"></i>Gateways</span>
        <form class="d-flex gap-2" (ngSubmit)="registerGateway()">
          <input
            class="form-control form-control-sm"
            type="text"
            placeholder="Name"
            name="newGatewayName"
            [(ngModel)]="newGatewayName"
          />
          <select
            class="form-select form-select-sm"
            name="newGatewayTransport"
            [(ngModel)]="newGatewayTransport"
          >
            <option value="WIFI">WiFi</option>
            <option value="CELLULAR">4G</option>
            <option value="TABLET">Tablet</option>
          </select>
          <button type="submit" class="btn btn-sm btn-primary text-nowrap">
            Register gateway
          </button>
        </form>
      </div>
      <div class="card-body p-0">
        @if (gateways().length === 0) {
          <div class="p-3 text-body-secondary">
            No gateways yet — register a few to cover the play area.
          </div>
        } @else {
          <div class="table-responsive">
            <table class="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Transport</th>
                  <th>Health</th>
                  <th>Last seen</th>
                  <th>Token</th>
                  <th>Coverage</th>
                </tr>
              </thead>
              <tbody>
                @for (g of gateways(); track g.id) {
                  <tr>
                    <td class="fw-semibold">{{ g.name }}</td>
                    <td>{{ g.transport }}</td>
                    <td>
                      @if (!g.active) {
                        <span class="badge text-bg-secondary">disabled</span>
                      } @else if (g.stale) {
                        <span class="badge text-bg-danger">offline</span>
                      } @else {
                        <span class="badge text-bg-success">online</span>
                      }
                    </td>
                    <td class="small">
                      @if (g.last_seen_at) {
                        {{ g.last_seen_at | date: 'HH:mm:ss' }}
                      } @else {
                        <span class="text-body-secondary">never</span>
                      }
                    </td>
                    <td class="font-monospace small text-body-secondary">
                      {{ g.token.slice(0, 8) }}…
                      <button
                        type="button"
                        class="btn btn-sm btn-link p-0 align-baseline"
                        title="Copy full token for provisioning"
                        (click)="copyToken(g)"
                      >
                        copy
                      </button>
                    </td>
                    <td class="small text-body-secondary">
                      {{ g.coverage_note || '—' }}
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </div>
    </div>
  `,
})
export class BadgesComponent {
  private readonly api = inject(BadgesService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly badges = signal<BadgeRow[]>([]);
  protected readonly gateways = signal<GatewayRow[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);
  protected readonly assigningId = signal<number | null>(null);

  protected newBadgeMac = '';
  protected newGatewayName = '';
  protected newGatewayTransport = 'WIFI';
  protected assignPlayerId: number | null = null;
  protected assignTeamId: number | null = null;

  private pollHandle: ReturnType<typeof setInterval> | null = null;

  constructor() {
    this.refresh();
    this.pollHandle = setInterval(() => this.refresh(), POLL_INTERVAL_MS);
    this.destroyRef.onDestroy(() => {
      if (this.pollHandle) clearInterval(this.pollHandle);
    });
  }

  protected refresh(): void {
    this.loading.set(true);
    this.api.badges().subscribe({
      next: (rows) => {
        this.badges.set(rows);
        this.loading.set(false);
        this.loadError.set(null);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
    this.api.gateways().subscribe({
      next: (rows) => this.gateways.set(rows),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected registerBadge(): void {
    const body = this.newBadgeMac ? { hardware_mac: this.newBadgeMac } : {};
    this.api.registerBadge(body).subscribe({
      next: () => {
        this.newBadgeMac = '';
        this.refresh();
      },
      error: (err) => this.actionError.set(extractErrorMessage(err)),
    });
  }

  protected registerGateway(): void {
    if (!this.newGatewayName) {
      this.actionError.set('Gateway name is required.');
      return;
    }
    this.api
      .registerGateway({
        name: this.newGatewayName,
        transport: this.newGatewayTransport,
      })
      .subscribe({
        next: () => {
          this.newGatewayName = '';
          this.actionError.set(null);
          this.refresh();
        },
        error: (err) => this.actionError.set(extractErrorMessage(err)),
      });
  }

  protected startAssign(badge: BadgeRow): void {
    this.assigningId.set(badge.id);
    this.assignPlayerId = null;
    this.assignTeamId = null;
  }

  protected assign(badge: BadgeRow): void {
    const body: { player_id?: number; team_id?: number } = {};
    if (this.assignPlayerId !== null) body.player_id = this.assignPlayerId;
    if (this.assignTeamId !== null) body.team_id = this.assignTeamId;
    this.api.assign(badge.id, body).subscribe({
      next: () => {
        this.assigningId.set(null);
        this.actionError.set(null);
        this.refresh();
      },
      error: (err) => this.actionError.set(extractErrorMessage(err)),
    });
  }

  protected collect(badge: BadgeRow, markLost: boolean): void {
    this.api.collect(badge.id, markLost).subscribe({
      next: () => {
        this.actionError.set(null);
        this.refresh();
      },
      error: (err) => this.actionError.set(extractErrorMessage(err)),
    });
  }

  protected copyToken(gateway: GatewayRow): void {
    void navigator.clipboard?.writeText(gateway.token);
  }
}
