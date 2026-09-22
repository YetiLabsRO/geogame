import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { RouterLink } from '@angular/router';

import {
  GameApiService,
  MyTeam,
  UiAlertComponent,
  UiAvatarComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiEmptyStateComponent,
  UiSpinnerComponent,
  UiStatTileComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-team',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    UiAlertComponent,
    UiAvatarComponent,
    UiButtonComponent,
    UiCardComponent,
    UiChipComponent,
    UiEmptyStateComponent,
    UiSpinnerComponent,
    UiStatTileComponent,
  ],
  template: `
    <div class="team-screen">
      @if (loadError(); as msg) {
        <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
      }

      @if (loading()) {
        <div class="team-screen__loading">
          <ui-spinner />
          <span class="tr-body">Loading…</span>
        </div>
      } @else if (noTeam()) {
        <ui-empty-state
          icon="users"
          title="No society yet"
          description="You are not a member of any team yet. Ask an organizer for an invite link, or browse open societies."
        >
          <div class="team-screen__empty-actions">
            <ui-button variant="primary" routerLink="/teams">Browse societies</ui-button>
            <ui-button variant="tinted" routerLink="/team/create">Create a society</ui-button>
          </div>
        </ui-empty-state>
      } @else if (team(); as t) {
        <header class="team-screen__header">
          <span class="tr-eyebrow" style="color: var(--color-brand-onSurface)">
            Active society
          </span>
          <div class="team-screen__title-row">
            <h1 class="tr-h1">{{ t.name }}</h1>
            <ui-chip [tone]="t.is_ready ? 'brand' : 'neutral'">
              {{ t.is_ready ? 'Ready' : 'Not ready' }}
            </ui-chip>
          </div>
        </header>

        <div class="team-screen__stats">
          <ui-stat-tile icon="star" label="Score" [value]="t.current_score" />
          <ui-stat-tile icon="users" label="Members" [value]="t.active_member_count" />
        </div>

        @if (!t.is_ready && t.members_needed > 0) {
          <ui-alert tone="warning" [withIcon]="true">
            Your team needs {{ t.members_needed }} more
            member{{ t.members_needed === 1 ? '' : 's' }} before the session can start.
          </ui-alert>
        } @else if (!t.is_ready) {
          <ui-alert tone="warning" [withIcon]="true">
            Your team has more members than this session allows.
          </ui-alert>
        }

        <div class="team-screen__divider" role="separator">
          <span class="team-screen__hairline"></span>
          <span class="tr-eyebrow" style="color: var(--color-text-muted)">Members</span>
          <span class="team-screen__hairline"></span>
        </div>

        <div class="team-screen__list">
          @for (m of t.members; track m.user_id) {
            <ui-card padding="sm">
              <div class="team-screen__member-row">
                <ui-avatar [size]="40" [name]="m.username" [teamColor]="t.color" />
                <div class="team-screen__member-info">
                  <span class="tr-h3">{{ m.username }}</span>
                  @if (m.first_name || m.last_name) {
                    <span class="tr-meta-tiny" style="color: var(--color-text-muted)">
                      {{ m.first_name }} {{ m.last_name }}
                    </span>
                  }
                </div>
              </div>
            </ui-card>
          }
        </div>
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
    .team-screen__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-xs);
      color: var(--color-text-secondary);
      padding-block: var(--spacing-xl);
    }
    .team-screen__empty-actions {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
      width: 100%;
    }
    .team-screen__header {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .team-screen__title-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
    }
    .team-screen__stats {
      display: flex;
      gap: var(--spacing-sm);
    }
    .team-screen__stats > * {
      flex: 1;
      min-width: 0;
    }
    .team-screen__divider {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
    }
    .team-screen__hairline {
      flex: 1;
      height: 1px;
      background: var(--color-border-subtle);
    }
    .team-screen__list {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .team-screen__member-row {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
    }
    .team-screen__member-info {
      display: flex;
      min-width: 0;
      flex-direction: column;
      gap: 4px;
    }
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
