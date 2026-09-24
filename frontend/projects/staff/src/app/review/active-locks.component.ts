import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';

import { DialogService, StaffApiService, StaffTowerLock } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/**
 * Active tower locks with live countdowns (tower-locking capability).
 * Embedded on the review/monitoring view; locks that lapse client-side
 * disappear from the list, mirroring the backend's lazy expiry.
 */
@Component({
  selector: 'app-active-locks',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe],
  template: `
    <div class="d-flex justify-content-between align-items-center mb-2">
      <h2 class="h5 mb-0"><i class="bi bi-lock-fill"></i> Active tower locks</h2>
      <button
        type="button"
        class="btn btn-sm btn-outline-secondary"
        [disabled]="loading()"
        (click)="refresh()"
      >
        <i class="bi bi-arrow-clockwise"></i> Refresh
      </button>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading() && activeLocks().length === 0) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading locks…
      </div>
    } @else if (activeLocks().length === 0) {
      <div class="alert alert-light border small mb-0">
        No tower is currently locked.
      </div>
    } @else {
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead>
            <tr>
              <th>Tower</th>
              <th>Team</th>
              <th>Group</th>
              <th>Started</th>
              <th>Deadline</th>
              <th class="text-end">Remaining</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (lock of activeLocks(); track lock.id) {
              <tr>
                <td class="fw-semibold">{{ lock.tower_name }}</td>
                <td>
                  <span class="badge" [style.background-color]="lock.team_color">
                    {{ lock.team_name }}
                  </span>
                </td>
                <td class="small">{{ lock.group_name ?? '—' }}</td>
                <td class="small">{{ lock.started_at | date: 'shortTime' }}</td>
                <td class="small">{{ lock.expires_at | date: 'shortTime' }}</td>
                <td class="text-end font-monospace">
                  {{ formatCountdown(remaining(lock)) }}
                </td>
                <td class="text-end">
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-danger"
                    [disabled]="cancellingId() !== null"
                    (click)="cancel(lock)"
                  >
                    @if (cancellingId() === lock.id) {
                      <span class="spinner-border spinner-border-sm me-1"></span>
                    }
                    Cancel
                  </button>
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
      @if (cancelError(); as msg) {
        <div class="alert alert-danger py-2">{{ msg }}</div>
      }
    }
  `,
})
export class ActiveLocksComponent {
  private readonly api = inject(StaffApiService);
  private readonly dialogs = inject(DialogService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly locks = signal<StaffTowerLock[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly cancellingId = signal<number | null>(null);
  protected readonly cancelError = signal<string | null>(null);
  protected readonly now = signal<number>(Date.now());

  /** Locks still ticking; lapsed ones drop out without waiting for the sweep. */
  protected readonly activeLocks = computed(() =>
    this.locks().filter((lock) => this.remainingAt(lock, this.now()) > 0),
  );

  constructor() {
    this.refresh();
    const tick = setInterval(() => this.now.set(Date.now()), 1000);
    this.destroyRef.onDestroy(() => clearInterval(tick));
  }

  protected refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listTowerLocks().subscribe({
      next: (list) => {
        this.locks.set(list);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected async cancel(lock: StaffTowerLock): Promise<void> {
    if (this.cancellingId() !== null) return;
    const ok = await this.dialogs.confirm({
      title: 'Cancel this lock?',
      message:
        `${lock.team_name} holds the lock on ${lock.tower_name}. ` +
        'Cancelling releases the tower for anyone to attempt.',
      confirmLabel: 'Cancel lock',
      cancelLabel: 'Leave it',
      danger: true,
    });
    if (!ok) return;
    this.cancellingId.set(lock.id);
    this.cancelError.set(null);
    this.api.cancelTowerLock(lock.id).subscribe({
      next: () => {
        this.cancellingId.set(null);
        this.locks.update((list) => list.filter((l) => l.id !== lock.id));
      },
      error: (err) => {
        this.cancellingId.set(null);
        this.cancelError.set(extractErrorMessage(err));
        this.refresh();
      },
    });
  }

  protected remaining(lock: StaffTowerLock): number {
    return this.remainingAt(lock, this.now());
  }

  protected formatCountdown(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  private remainingAt(lock: StaffTowerLock, nowMs: number): number {
    const ms = new Date(lock.expires_at).getTime() - nowMs;
    return Math.max(0, Math.ceil(ms / 1000));
  }
}
