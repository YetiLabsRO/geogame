import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { TeamFormationService, TeamJoinRequest } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-join-requests',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-8">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h1 class="h3 mb-0">Join requests</h1>
          <a class="btn btn-sm btn-outline-secondary" [routerLink]="['/team', teamId, 'share']">
            <i class="bi bi-qr-code"></i> Share team
          </a>
        </div>

        @if (error(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }

        @if (loading()) {
          <div class="d-flex align-items-center text-body-secondary">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading…
          </div>
        } @else {
          @if (pending().length === 0) {
            <div class="alert alert-info">No pending requests.</div>
          } @else {
            <ul class="list-group mb-4">
              @for (r of pending(); track r.id) {
                <li class="list-group-item d-flex justify-content-between align-items-center">
                  <div>
                    <span class="fw-semibold">{{ r.first_name || r.username }}</span>
                    <span class="text-body-secondary small ms-1">
                      &#64;{{ r.username }} · via {{ r.source }} ·
                      {{ r.requested_at | date: 'short' }}
                    </span>
                    @if (r.note) {
                      <div class="small text-body-secondary">“{{ r.note }}”</div>
                    }
                  </div>
                  <div class="btn-group btn-group-sm">
                    <button
                      type="button"
                      class="btn btn-outline-success"
                      [disabled]="busy() === r.id"
                      (click)="approve(r)"
                    >
                      <i class="bi bi-check-lg"></i> Approve
                    </button>
                    <button
                      type="button"
                      class="btn btn-outline-danger"
                      [disabled]="busy() === r.id"
                      (click)="reject(r)"
                    >
                      <i class="bi bi-x-lg"></i> Reject
                    </button>
                  </div>
                </li>
              }
            </ul>
          }

          @if (decided().length > 0) {
            <h2 class="h6 text-body-secondary">Decided</h2>
            <ul class="list-group">
              @for (r of decided(); track r.id) {
                <li class="list-group-item d-flex justify-content-between align-items-center">
                  <span>
                    {{ r.username }}
                    <span class="text-body-secondary small">· via {{ r.source }}</span>
                  </span>
                  <span
                    class="badge"
                    [class]="r.status === 'APPROVED' ? 'text-bg-success' : 'text-bg-danger'"
                  >
                    {{ r.status }}
                  </span>
                </li>
              }
            </ul>
          }
        }
      </div>
    </div>
  `,
})
export class JoinRequestsComponent {
  private readonly teamFormation = inject(TeamFormationService);
  private readonly route = inject(ActivatedRoute);

  protected readonly teamId = Number(this.route.snapshot.paramMap.get('id'));

  protected readonly requests = signal<TeamJoinRequest[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal<number | null>(null);

  protected readonly pending = computed(() =>
    this.requests().filter((r) => r.team === this.teamId && r.status === 'PENDING'),
  );
  protected readonly decided = computed(() =>
    this.requests().filter((r) => r.team === this.teamId && r.status !== 'PENDING'),
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
