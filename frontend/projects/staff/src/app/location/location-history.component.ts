import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { LocationHistory, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/**
 * Minimal after-game location replay (live-location capability).
 *
 * Lists the Session's `LocationPing` series from the staff
 * location-history feed, filterable by user / team / time window.
 * A richer scrubber/timeline UI can layer on later — this is the
 * wireframe backed by the replay API.
 */
@Component({
  selector: 'app-location-history',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FormsModule, RouterLink],
  template: `
    <a [routerLink]="['/sessions', sessionId]" class="small text-body-secondary">
      &larr; Back to session
    </a>
    <h1 class="h3 mt-2 mb-1">Location history</h1>
    @if (history(); as h) {
      <p class="text-body-secondary small">
        {{ h.pings.length }} ping(s) · kept for {{ h.retention_days }} days
        after recording, then purged.
      </p>
    }

    <div class="card mb-3">
      <div class="card-body">
        <div class="row g-2 align-items-end">
          <div class="col-auto">
            <label class="form-label small mb-0" for="f-user">User id</label>
            <input
              id="f-user"
              class="form-control form-control-sm"
              type="number"
              [ngModel]="filterUser()"
              (ngModelChange)="filterUser.set($event)"
            />
          </div>
          <div class="col-auto">
            <label class="form-label small mb-0" for="f-team">Team id</label>
            <input
              id="f-team"
              class="form-control form-control-sm"
              type="number"
              [ngModel]="filterTeam()"
              (ngModelChange)="filterTeam.set($event)"
            />
          </div>
          <div class="col-auto">
            <label class="form-label small mb-0" for="f-from">From</label>
            <input
              id="f-from"
              class="form-control form-control-sm"
              type="datetime-local"
              [ngModel]="filterFrom()"
              (ngModelChange)="filterFrom.set($event)"
            />
          </div>
          <div class="col-auto">
            <label class="form-label small mb-0" for="f-to">To</label>
            <input
              id="f-to"
              class="form-control form-control-sm"
              type="datetime-local"
              [ngModel]="filterTo()"
              (ngModelChange)="filterTo.set($event)"
            />
          </div>
          <div class="col-auto">
            <button
              type="button"
              class="btn btn-sm btn-primary"
              [disabled]="loading()"
              (click)="refresh()"
            >
              @if (loading()) {
                <span class="spinner-border spinner-border-sm me-1"></span>
              }
              Apply
            </button>
          </div>
        </div>
      </div>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (history(); as h) {
      @if (h.pings.length === 0) {
        <div class="alert alert-info">
          No location pings recorded for this selection.
        </div>
      } @else {
        <div class="table-responsive">
          <table class="table table-sm align-middle">
            <thead>
              <tr>
                <th>Player</th>
                <th>Team</th>
                <th>Position</th>
                <th class="text-end">Accuracy (m)</th>
                <th>Recorded</th>
                <th>Received</th>
              </tr>
            </thead>
            <tbody>
              @for (p of h.pings; track $index) {
                <tr>
                  <td>{{ p.username }}</td>
                  <td>
                    @if (p.team_name; as team) {
                      <span
                        class="badge"
                        [style.background-color]="p.team_color || '#6c757d'"
                      >
                        {{ team }}
                      </span>
                    } @else {
                      <span class="text-body-secondary">—</span>
                    }
                  </td>
                  <td class="small font-monospace">
                    {{ p.lat.toFixed(6) }}, {{ p.lng.toFixed(6) }}
                  </td>
                  <td class="text-end small">
                    {{ p.accuracy !== null ? p.accuracy : '—' }}
                  </td>
                  <td class="small">{{ p.recorded_at | date: 'medium' }}</td>
                  <td class="small text-body-secondary">
                    {{ p.received_at | date: 'shortTime' }}
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    } @else if (loading()) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    }
  `,
})
export class LocationHistoryComponent {
  private readonly api = inject(StaffApiService);
  private readonly route = inject(ActivatedRoute);

  protected readonly sessionId = Number(this.route.snapshot.paramMap.get('id'));
  protected readonly history = signal<LocationHistory | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly filterUser = signal<number | null>(null);
  protected readonly filterTeam = signal<number | null>(null);
  protected readonly filterFrom = signal<string>('');
  protected readonly filterTo = signal<string>('');

  constructor() {
    if (this.sessionId) {
      this.refresh();
    } else {
      this.loadError.set('Invalid session.');
    }
  }

  protected refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api
      .sessionLocationHistory(this.sessionId, {
        user: this.filterUser() ?? undefined,
        team: this.filterTeam() ?? undefined,
        from: this.filterFrom() ? new Date(this.filterFrom()).toISOString() : undefined,
        to: this.filterTo() ? new Date(this.filterTo()).toISOString() : undefined,
      })
      .subscribe({
        next: (h) => {
          this.history.set(h);
          this.loading.set(false);
        },
        error: (err) => {
          this.loading.set(false);
          this.loadError.set(extractErrorMessage(err));
        },
      });
  }
}
