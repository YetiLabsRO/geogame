import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';

import {
  StatusLabelPipe,
  TeamFormationService,
  TeamJoinRequest,
  ToastService,
  UiAlertComponent,
  UiAvatarComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiEmptyStateComponent,
  UiSpinnerComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-join-requests',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, RouterLink, StatusLabelPipe, UiAlertComponent, UiAvatarComponent, UiButtonComponent, UiCardComponent, UiChipComponent, UiEmptyStateComponent, UiSpinnerComponent],
  template: `
    <div class="team-screen">
      <div class="team-screen__title-row">
        <div class="team-screen__title-group">
          <h1 class="tr-h1">Awaiting review</h1>
          @if (pending().length > 0) {
            <ui-chip tone="solid">{{ pending().length }}</ui-chip>
          }
        </div>
        <ui-button variant="secondary" size="sm" icon="key" [routerLink]="['/team', teamId, 'share']">
          Share team
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
      } @else {
        @if (pending().length === 0) {
          <ui-empty-state icon="id-card" title="Nothing to review" description="No pending requests right now." />
        } @else {
          <div class="team-screen__list">
            @for (r of pending(); track r.id) {
              <ui-card padding="sm">
                <div class="team-screen__member-row">
                  <ui-avatar [size]="40" [name]="r.first_name || r.username" />
                  <div class="team-screen__member-info">
                    <span class="tr-h3">{{ r.first_name || r.username }}</span>
                    <span class="tr-meta-tiny" style="color: var(--color-text-muted)">
                      &#64;{{ r.username }} · via {{ r.source }} ·
                      {{ r.requested_at | date: 'short' }}
                    </span>
                  </div>
                </div>
                @if (r.note) {
                  <blockquote class="team-screen__quote tr-body-italic">{{ r.note }}</blockquote>
                }
                <div cardActions class="team-screen__request-actions">
                  <ui-button
                    variant="tinted"
                    size="sm"
                    [loading]="busy() === r.id"
                    (pressed)="approve(r)"
                  >
                    Accept
                  </ui-button>
                  <ui-button
                    variant="secondary"
                    size="sm"
                    [loading]="busy() === r.id"
                    (pressed)="reject(r)"
                  >
                    Decline
                  </ui-button>
                </div>
              </ui-card>
            }
          </div>
        }

        @if (decided().length > 0) {
          <div class="team-screen__divider" role="separator">
            <span class="team-screen__hairline"></span>
            <span class="tr-eyebrow" style="color: var(--color-text-muted)">Decided</span>
            <span class="team-screen__hairline"></span>
          </div>
          <div class="team-screen__list">
            @for (r of decided(); track r.id) {
              <ui-card padding="sm">
                <div class="team-screen__decided-row">
                  <span class="tr-body">{{ r.username }}</span>
                  <ui-chip [tone]="r.status === 'APPROVED' ? 'brand' : 'neutral'">
                    {{ r.status | statusLabel }}
                  </ui-chip>
                </div>
              </ui-card>
            }
          </div>
        }
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
      flex-wrap: wrap;
    }
    .team-screen__title-group {
      display: flex;
      align-items: center;
      gap: var(--spacing-xs);
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
    .team-screen__quote {
      margin: 0;
      padding-left: var(--spacing-sm);
      border-left: 3px solid var(--color-brand-primary);
      color: var(--color-text-secondary);
    }
    .team-screen__request-actions {
      display: flex;
      gap: var(--spacing-sm);
    }
    .team-screen__request-actions > * {
      flex: 1;
    }
    .team-screen__decided-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
    }
    .team-screen__hairline {
      flex: 1;
      height: 1px;
      background: var(--color-border-subtle);
    }
    .team-screen__divider {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
    }
  `,
})
export class JoinRequestsComponent {
  private readonly teamFormation = inject(TeamFormationService);
  private readonly route = inject(ActivatedRoute);
  private readonly toast = inject(ToastService);

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
        this.toast.show(`${r.first_name || r.username} accepted`, { tone: 'success' });
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
        this.toast.show(`${r.first_name || r.username} declined`, { tone: 'neutral' });
        this.load();
      },
      error: (err) => {
        this.busy.set(null);
        this.error.set(extractErrorMessage(err));
      },
    });
  }
}
