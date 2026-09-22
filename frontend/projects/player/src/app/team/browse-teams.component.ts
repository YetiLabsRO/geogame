import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import {
  AuthService,
  JoinableTeam,
  TeamFormationService,
  ToastService,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiEmptyStateComponent,
  UiSpinnerComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-browse-teams',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiChipComponent,
    UiEmptyStateComponent,
    UiSpinnerComponent,
  ],
  template: `
    <div class="team-screen">
      <div class="team-screen__title-row">
        <h1 class="tr-h1">Societies</h1>
        <ui-button variant="tinted" size="sm" icon="users" routerLink="/team/create">
          Create
        </ui-button>
      </div>

      @if (error(); as msg) {
        <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
      }

      @if (loading()) {
        <div class="team-screen__loading">
          <ui-spinner />
          <span class="tr-body">Loading…</span>
        </div>
      } @else if (teams().length === 0 && !error()) {
        <ui-empty-state
          icon="users"
          title="No societies yet"
          description="No teams to join yet — be the first to create one!"
        >
          <ui-button variant="primary" routerLink="/team/create">Create a society</ui-button>
        </ui-empty-state>
      } @else {
        <div class="team-screen__list">
          @for (t of teams(); track t.id) {
            <ui-card padding="sm">
              <div class="team-screen__browse-row">
                <div class="team-screen__browse-info">
                  <span class="tr-h3">{{ t.name }}</span>
                  <div class="team-screen__browse-meta">
                    @if (t.group_name) {
                      <ui-chip [teamColor]="t.color">{{ t.group_name }}</ui-chip>
                    }
                    <span class="tr-meta-tiny" style="color: var(--color-text-muted)">
                      {{ t.member_count }} member{{ t.member_count === 1 ? '' : 's' }}
                    </span>
                  </div>
                </div>
                <div class="team-screen__browse-action">
                  @switch (t.my_request_status) {
                    @case ('PENDING') {
                      <ui-chip tone="neutral">Pending</ui-chip>
                    }
                    @case ('REJECTED') {
                      <div class="team-screen__browse-retry">
                        <span class="tr-meta-tiny" style="color: var(--color-danger)">
                          Rejected
                        </span>
                        <ui-button
                          variant="secondary"
                          size="sm"
                          [loading]="busyTeam() === t.id"
                          (pressed)="request(t)"
                        >
                          Ask again
                        </ui-button>
                      </div>
                    }
                    @case ('APPROVED') {
                      <ui-chip tone="brand">Joined</ui-chip>
                    }
                    @default {
                      <ui-button
                        variant="primary"
                        size="sm"
                        [loading]="busyTeam() === t.id"
                        (pressed)="request(t)"
                      >
                        {{ t.join_confirmation === 'AUTO_APPROVE' ? 'Join' : 'Request to join' }}
                      </ui-button>
                    }
                  }
                </div>
              </div>
            </ui-card>
          }
        </div>
        <p class="tr-meta-tiny team-screen__hint">
          Teams needing confirmation put your request in a queue until the captain or the staff
          approve it.
        </p>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .team-screen {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-lg);
      padding: var(--spacing-sm) var(--spacing-xl) var(--spacing-3xl);
    }
    .team-screen__title-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
    }
    .team-screen__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-xs);
      color: var(--color-text-secondary);
      padding-block: var(--spacing-xl);
    }
    .team-screen__list {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .team-screen__browse-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
    }
    .team-screen__browse-info {
      display: flex;
      min-width: 0;
      flex-direction: column;
      gap: 4px;
    }
    .team-screen__browse-meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--spacing-xs);
    }
    .team-screen__browse-action {
      flex-shrink: 0;
    }
    .team-screen__browse-retry {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 4px;
    }
    .team-screen__hint {
      color: var(--color-text-muted);
      text-align: center;
    }
  `,
})
export class BrowseTeamsComponent {
  private readonly teamFormation = inject(TeamFormationService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);

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
        this.toast.show('Request sent', { tone: 'brand' });
        this.load();
      },
      error: (err) => {
        this.busyTeam.set(null);
        this.error.set(extractErrorMessage(err));
      },
    });
  }
}
