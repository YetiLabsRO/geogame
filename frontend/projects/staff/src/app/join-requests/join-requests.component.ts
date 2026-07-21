import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';

import { JoinRequestStatus, TeamFormationService, TeamJoinRequest } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

type TabKey = JoinRequestStatus | 'ALL';

@Component({
  selector: 'app-staff-join-requests',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe],
  template: `
    <h1 class="h3 mb-3">Join requests</h1>
    <p class="text-body-secondary small">
      Requests from players asking to join a team in the current session —
      from browsing the team list, an untied team QR, or an invite link on a
      team that requires confirmation.
    </p>

    <ul class="nav nav-tabs mb-3">
      @for (tab of tabs; track tab.key) {
        <li class="nav-item">
          <button
            type="button"
            class="nav-link"
            [class.active]="activeTab() === tab.key"
            (click)="activeTab.set(tab.key)"
          >
            {{ tab.label }}
            @if (tab.key === 'PENDING' && pendingCount() > 0) {
              <span class="badge text-bg-warning ms-1">{{ pendingCount() }}</span>
            }
          </button>
        </li>
      }
    </ul>

    @if (error(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading()) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (filtered().length === 0) {
      <div class="alert alert-info">No join requests.</div>
    } @else {
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Player</th>
              <th>Team</th>
              <th>Source</th>
              <th>Requested</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (r of filtered(); track r.id) {
              <tr>
                <td>
                  <span class="fw-semibold">{{ r.username }}</span>
                  @if (r.first_name || r.last_name) {
                    <span class="text-body-secondary small ms-1">
                      {{ r.first_name }} {{ r.last_name }}
                    </span>
                  }
                </td>
                <td>{{ r.team_name }}</td>
                <td><span class="badge text-bg-secondary">{{ r.source }}</span></td>
                <td class="small text-body-secondary">
                  {{ r.requested_at | date: 'short' }}
                </td>
                <td>
                  @switch (r.status) {
                    @case ('PENDING') {
                      <span class="badge text-bg-warning">Pending</span>
                    }
                    @case ('APPROVED') {
                      <span class="badge text-bg-success">Approved</span>
                      @if (r.decided_by_username) {
                        <span class="text-body-secondary small ms-1">
                          by {{ r.decided_by_username }}
                        </span>
                      }
                    }
                    @case ('REJECTED') {
                      <span class="badge text-bg-danger">Rejected</span>
                      @if (r.decided_by_username) {
                        <span class="text-body-secondary small ms-1">
                          by {{ r.decided_by_username }}
                        </span>
                      }
                    }
                  }
                </td>
                <td class="text-end">
                  @if (r.status === 'PENDING') {
                    <div class="btn-group btn-group-sm">
                      <button
                        type="button"
                        class="btn btn-outline-success"
                        [disabled]="busy() === r.id"
                        (click)="approve(r)"
                      >
                        Approve
                      </button>
                      <button
                        type="button"
                        class="btn btn-outline-danger"
                        [disabled]="busy() === r.id"
                        (click)="reject(r)"
                      >
                        Reject
                      </button>
                    </div>
                  }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    }
  `,
})
export class StaffJoinRequestsComponent {
  private readonly teamFormation = inject(TeamFormationService);

  protected readonly tabs: { key: TabKey; label: string }[] = [
    { key: 'PENDING', label: 'Pending' },
    { key: 'APPROVED', label: 'Approved' },
    { key: 'REJECTED', label: 'Rejected' },
    { key: 'ALL', label: 'All' },
  ];

  protected readonly activeTab = signal<TabKey>('PENDING');
  protected readonly requests = signal<TeamJoinRequest[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal<number | null>(null);

  protected readonly filtered = computed(() => {
    const tab = this.activeTab();
    const list = this.requests();
    return tab === 'ALL' ? list : list.filter((r) => r.status === tab);
  });

  protected readonly pendingCount = computed(
    () => this.requests().filter((r) => r.status === 'PENDING').length,
  );

  constructor() {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.teamFormation.joinRequests().subscribe({
      next: (list) => {
        this.requests.set(list);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(extractErrorMessage(err));
      },
    });
  }

  protected approve(r: TeamJoinRequest): void {
    this.busy.set(r.id);
    this.error.set(null);
    this.teamFormation.approveJoinRequest(r.id).subscribe({
      next: () => {
        this.busy.set(null);
        this.load();
      },
      error: (err) => {
        this.busy.set(null);
        this.error.set(extractErrorMessage(err));
      },
    });
  }

  protected reject(r: TeamJoinRequest): void {
    this.busy.set(r.id);
    this.error.set(null);
    this.teamFormation.rejectJoinRequest(r.id).subscribe({
      next: () => {
        this.busy.set(null);
        this.load();
      },
      error: (err) => {
        this.busy.set(null);
        this.error.set(extractErrorMessage(err));
      },
    });
  }
}
