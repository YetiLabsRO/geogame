import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';

import {
  AuthService,
  GameApiService,
  Invite,
  InvitesService,
  MyTeam,
  ToastService,
  UiAlertComponent,
  UiAvatarComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiFieldComponent,
  UiIconComponent,
  UiInputDirective,
  UiSpinnerComponent,
  UiStatTileComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/**
 * "My team" page (team-roles capability): the roster with each member's
 * in-game roles, the caller's own roles, and an invite affordance for
 * holders of a role with the INVITER built-in power.
 */
@Component({
  selector: 'app-my-team',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    UiAlertComponent,
    UiAvatarComponent,
    UiButtonComponent,
    UiCardComponent,
    UiChipComponent,
    UiFieldComponent,
    UiIconComponent,
    UiInputDirective,
    UiSpinnerComponent,
    UiStatTileComponent,
  ],
  template: `
    <div class="team-screen">
      <a routerLink="/" class="team-screen__back tr-body">
        <ui-icon name="chevron-left" [size]="18" />
        Back to map
      </a>

      @if (loadError(); as msg) {
        <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
      } @else if (team(); as t) {
        <header class="team-screen__header" [style.--team-color]="t.color">
          <span class="tr-eyebrow" style="color: var(--color-brand-onSurface)">
            Active society
          </span>
          <h1 class="tr-h1">{{ t.name }}</h1>

          @if (myRoles().length > 0) {
            <div class="team-screen__my-roles">
              <span class="tr-meta-tiny" style="color: var(--color-text-muted)">
                Your roles
              </span>
              @for (role of myRoles(); track role.id) {
                <ui-chip tone="brand">{{ role.name }}</ui-chip>
              }
            </div>
          }
        </header>

        <div class="team-screen__stats">
          <ui-stat-tile icon="star" label="Score" [value]="t.current_score" />
          <ui-stat-tile icon="users" label="Members" [value]="t.active_member_count" />
        </div>

        @if (!t.is_ready) {
          <ui-alert tone="warning" [withIcon]="true">
            @if (t.members_needed > 0) {
              Your team needs {{ t.members_needed }} more
              member{{ t.members_needed === 1 ? '' : 's' }} before the session can start.
            } @else {
              Your team has more members than this session allows.
            }
          </ui-alert>
        }

        <div class="team-screen__divider" role="separator">
          <span class="team-screen__hairline"></span>
          <span class="tr-eyebrow" style="color: var(--color-text-muted)">
            Members of the society
          </span>
          <span class="team-screen__hairline"></span>
        </div>

        <div class="team-screen__list">
          @for (m of t.members; track m.user_id) {
            <ui-card padding="sm">
              <div class="team-screen__member-row">
                <ui-avatar [size]="40" [name]="m.username" [teamColor]="t.color" />
                <div class="team-screen__member-info">
                  <span class="tr-h3">{{ m.username }}</span>
                  <div class="team-screen__member-chips">
                    @if (isCaptain() && m.user_id === myUserId()) {
                      <ui-chip tone="brand">Lead</ui-chip>
                    }
                    @for (role of m.roles; track role.id) {
                      <ui-chip tone="slate">{{ role.name }}</ui-chip>
                    }
                    @if (m.user_id === myUserId()) {
                      <ui-chip tone="neutral">You</ui-chip>
                    }
                  </div>
                </div>
              </div>
            </ui-card>
          }
        </div>

        @if (t.can_invite) {
          <ui-card class="team-screen__invite">
            <div class="team-screen__invite-body">
              <ui-icon name="users" [size]="32" />
              <h3 class="tr-h3">Expand the Society</h3>
              <p class="tr-body" style="color: var(--color-text-secondary)">
                You hold an inviter role — bring new players into your team.
              </p>
            </div>

            @if (inviteError(); as msg) {
              <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
            }

            @if (inviteLink(); as link) {
              <ui-field label="Invite link">
                <input uiInput type="text" readonly [value]="link" />
              </ui-field>
              <ui-button variant="secondary" size="sm" [block]="true" (pressed)="copyLink(link)">
                Copy link
              </ui-button>
            } @else {
              <ui-button
                variant="tinted"
                [block]="true"
                [loading]="creatingInvite()"
                (pressed)="createInvite()"
              >
                Share invite
              </ui-button>
            }
          </ui-card>
        }

        @if (isCaptain()) {
          <a [routerLink]="['/team', t.id, 'requests']" class="team-screen__requests-link">
            <ui-card padding="sm" variant="flat">
              <div class="team-screen__requests-row">
                <span class="tr-h3">Join requests</span>
                <ui-icon name="arrow-right" [size]="18" />
              </div>
            </ui-card>
          </a>
        }
      } @else {
        <div class="team-screen__loading">
          <ui-spinner />
          <span class="tr-body">Loading team…</span>
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
    .team-screen__back {
      display: inline-flex;
      align-items: center;
      gap: var(--spacing-2xs);
      color: var(--color-text-secondary);
      text-decoration: none;
    }
    .team-screen__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-xs);
      color: var(--color-text-secondary);
      padding-block: var(--spacing-xl);
    }
    .team-screen__header {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .team-screen__my-roles {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--spacing-2xs);
      margin-top: var(--spacing-xs);
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
    .team-screen__member-chips {
      display: flex;
      flex-wrap: wrap;
      gap: var(--spacing-2xs);
    }
    ui-card.team-screen__invite {
      border-style: dashed;
      border-color: var(--color-border-default);
    }
    .team-screen__invite-body {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--spacing-2xs);
      text-align: center;
    }
    .team-screen__requests-link {
      display: block;
      text-decoration: none;
    }
    .team-screen__requests-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--color-text-primary);
    }
  `,
})
export class MyTeamComponent implements OnInit {
  private readonly api = inject(GameApiService);
  private readonly invites = inject(InvitesService);
  private readonly auth = inject(AuthService);
  private readonly toast = inject(ToastService);

  protected readonly team = signal<MyTeam | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creatingInvite = signal(false);
  protected readonly inviteError = signal<string | null>(null);
  protected readonly invite = signal<Invite | null>(null);
  protected readonly copied = signal(false);

  protected readonly myUserId = computed(() => this.auth.profile()?.id ?? null);

  protected readonly myRoles = computed(() => {
    const t = this.team();
    const me = this.myUserId();
    if (!t || me === null) return [];
    return t.members.find((m) => m.user_id === me)?.roles ?? [];
  });

  /**
   * Derived purely from the already-fetched `UserProfile.captain_of_team_id`
   * (no new API call). `MyTeamMember` has no per-row captain flag, so the
   * "Lead" chip can only be shown on the viewer's own row.
   */
  protected readonly isCaptain = computed(
    () => this.team()?.id === this.auth.profile()?.captain_of_team_id,
  );

  protected readonly inviteLink = computed(() => {
    const inv = this.invite();
    return inv ? `${location.origin}/invite/${inv.token}` : null;
  });

  ngOnInit(): void {
    this.api.myTeam().subscribe({
      next: (t) => this.team.set(t),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
    if (this.auth.profile() === null) {
      this.auth.fetchProfile().subscribe({ error: () => {} });
    }
  }

  protected createInvite(): void {
    const t = this.team();
    if (!t || this.creatingInvite()) return;
    this.creatingInvite.set(true);
    this.inviteError.set(null);
    this.copied.set(false);
    this.invites.create({ team: t.id }).subscribe({
      next: (invite) => {
        this.creatingInvite.set(false);
        this.invite.set(invite);
      },
      error: (err) => {
        this.creatingInvite.set(false);
        this.inviteError.set(extractErrorMessage(err));
      },
    });
  }

  protected copyLink(link: string): void {
    navigator.clipboard?.writeText(link).then(() => {
      this.copied.set(true);
      this.toast.show('Invite link copied', { tone: 'success' });
    });
  }
}
