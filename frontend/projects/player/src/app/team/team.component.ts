import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';

import { GameApiService, MyTeam } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-team',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-8">
        <h1 class="h3 mb-3">My team</h1>

        @if (loadError(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }

        @if (loading()) {
          <div class="d-flex align-items-center text-body-secondary">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading…
          </div>
        } @else if (noTeam()) {
          <div class="alert alert-info">
            You are not a member of any team yet. Ask an organizer for an
            invite link.
          </div>
        } @else if (team(); as t) {
          <div class="card">
            <div class="card-body">
              <h2 class="h5 mb-1">
                <span
                  class="d-inline-block me-2"
                  style="width: 1rem; height: 1rem; border-radius: 50%; vertical-align: middle"
                  [style.background-color]="t.color"
                ></span>
                {{ t.name }}
                @if (t.is_ready) {
                  <span class="badge text-bg-success ms-2">ready</span>
                } @else {
                  <span class="badge text-bg-warning ms-2">not ready</span>
                }
              </h2>
              <div class="text-body-secondary small mb-3">
                Score: {{ t.current_score }} ·
                {{ t.active_member_count }} member{{
                  t.active_member_count === 1 ? '' : 's'
                }}
              </div>

              @if (!t.is_ready && t.members_needed > 0) {
                <div class="alert alert-warning py-2">
                  Your team needs {{ t.members_needed }} more
                  member{{ t.members_needed === 1 ? '' : 's' }} before the
                  session can start.
                </div>
              } @else if (!t.is_ready) {
                <div class="alert alert-warning py-2">
                  Your team has more members than this session allows.
                </div>
              }

              <h3 class="h6">Members</h3>
              <ul class="list-group list-group-flush">
                @for (m of t.members; track m.user_id) {
                  <li class="list-group-item px-0">
                    <span class="fw-semibold">{{ m.username }}</span>
                    @if (m.first_name || m.last_name) {
                      <span class="text-body-secondary small ms-2">
                        {{ m.first_name }} {{ m.last_name }}
                      </span>
                    }
                  </li>
                }
              </ul>
            </div>
          </div>
        }
      </div>
    </div>
  `,
})
export class TeamComponent {
  private readonly api = inject(GameApiService);

  protected readonly team = signal<MyTeam | null>(null);
  protected readonly noTeam = signal(false);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  constructor() {
    this.loading.set(true);
    this.api.myTeam().subscribe({
      next: (t) => {
        this.team.set(t);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        if (err instanceof HttpErrorResponse && err.status === 404) {
          this.noTeam.set(true);
        } else {
          this.loadError.set(extractErrorMessage(err));
        }
      },
    });
  }
}
