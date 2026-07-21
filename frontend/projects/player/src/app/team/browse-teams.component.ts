import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService, JoinableTeam, TeamFormationService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-browse-teams',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-8">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h1 class="h3 mb-0">Teams forming</h1>
          <a class="btn btn-sm btn-primary" routerLink="/team/create">
            <i class="bi bi-plus-lg"></i> Create a team
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
        } @else if (teams().length === 0 && !error()) {
          <div class="alert alert-info">
            No teams to join yet — be the first to create one!
          </div>
        } @else {
          <ul class="list-group">
            @for (t of teams(); track t.id) {
              <li class="list-group-item d-flex justify-content-between align-items-center">
                <div>
                  <span
                    class="badge me-2"
                    [style.background-color]="t.color"
                  >&nbsp;</span>
                  <span class="fw-semibold">{{ t.name }}</span>
                  @if (t.group_name) {
                    <span class="text-body-secondary small ms-1">· {{ t.group_name }}</span>
                  }
                  <span class="text-body-secondary small ms-2">
                    <i class="bi bi-people"></i> {{ t.member_count }}
                  </span>
                </div>
                <div>
                  @switch (t.my_request_status) {
                    @case ('PENDING') {
                      <span class="badge text-bg-warning">Requested — pending</span>
                    }
                    @case ('REJECTED') {
                      <span class="badge text-bg-danger me-2">Rejected</span>
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-primary"
                        [disabled]="busyTeam() === t.id"
                        (click)="request(t)"
                      >
                        Ask again
                      </button>
                    }
                    @case ('APPROVED') {
                      <span class="badge text-bg-success">Joined</span>
                    }
                    @default {
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-primary"
                        [disabled]="busyTeam() === t.id"
                        (click)="request(t)"
                      >
                        {{ t.join_confirmation === 'AUTO_APPROVE' ? 'Join' : 'Request to join' }}
                      </button>
                    }
                  }
                </div>
              </li>
            }
          </ul>
          <p class="form-text mt-2">
            Teams needing confirmation put your request in a queue until the
            captain or the staff approve it.
          </p>
        }
      </div>
    </div>
  `,
})
export class BrowseTeamsComponent {
  private readonly teamFormation = inject(TeamFormationService);
  private readonly auth = inject(AuthService);

  protected readonly teams = signal<JoinableTeam[]>([]);
  protected readonly loading = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly busyTeam = signal<number | null>(null);

  constructor() {
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.teamFormation.joinableTeams().subscribe({
      next: (list) => {
        this.teams.set(list);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.error.set(extractErrorMessage(err));
      },
    });
  }

  protected request(team: JoinableTeam): void {
    this.busyTeam.set(team.id);
    this.error.set(null);
    this.teamFormation.requestJoin({ team: team.id }).subscribe({
      next: () => {
        this.busyTeam.set(null);
        // Refresh the profile so the navbar picks up a new membership.
        this.auth.fetchProfile().subscribe({ error: () => {} });
        this.load();
      },
      error: (err) => {
        this.busyTeam.set(null);
        this.error.set(extractErrorMessage(err));
      },
    });
  }
}
