import {
  ChangeDetectionStrategy,
  Component,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { RouterLink } from '@angular/router';

import { AuthService, GameApiService, Invite, InvitesService, MyTeam } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/**
 * Wireframe "My team" page (team-roles capability): the roster with each
 * member's in-game roles, the caller's own roles, and an invite
 * affordance for holders of a role with the INVITER built-in power.
 */
@Component({
  selector: 'app-my-team',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-md-8 col-lg-6">
        <a routerLink="/" class="small text-body-secondary">&larr; Back to map</a>

        @if (loadError(); as msg) {
          <div class="alert alert-danger mt-3">{{ msg }}</div>
        } @else if (team(); as t) {
          <h1 class="h3 mt-2 mb-1 d-flex align-items-center gap-2">
            <span
              class="d-inline-block rounded-circle"
              style="width: 0.9rem; height: 0.9rem"
              [style.background-color]="t.color"
            ></span>
            {{ t.name }}
          </h1>
          <div class="text-body-secondary small mb-3">
            Score: {{ t.current_score }}
          </div>

          @if (myRoles().length > 0) {
            <div class="mb-3">
              <span class="small text-body-secondary me-1">Your roles:</span>
              @for (role of myRoles(); track role.id) {
                <span class="badge text-bg-primary me-1">{{ role.name }}</span>
              }
            </div>
          } @else {
            <div class="mb-3 small text-body-secondary">
              You hold no in-game roles yet.
            </div>
          }

          <div class="card mb-3">
            <div class="card-header py-2 small fw-semibold">Members</div>
            <ul class="list-group list-group-flush">
              @for (member of t.members; track member.user_id) {
                <li class="list-group-item d-flex justify-content-between align-items-center">
                  <span>
                    {{ member.username }}
                    @if (member.user_id === myUserId()) {
                      <span class="text-body-secondary small">(you)</span>
                    }
                  </span>
                  <span>
                    @for (role of member.roles; track role.id) {
                      <span class="badge text-bg-secondary ms-1">{{ role.name }}</span>
                    } @empty {
                      <span class="text-body-secondary small">no roles</span>
                    }
                  </span>
                </li>
              }
            </ul>
          </div>

          @if (t.can_invite) {
            <div class="card mb-3">
              <div class="card-body">
                <div class="fw-semibold mb-1">
                  <i class="bi bi-person-plus"></i> Invite a player
                </div>
                <p class="small text-body-secondary mb-2">
                  You hold an inviter role — you can bring new players into
                  your team.
                </p>
                @if (inviteError(); as msg) {
                  <div class="alert alert-danger py-2">{{ msg }}</div>
                }
                @if (inviteLink(); as link) {
                  <div class="input-group input-group-sm mb-2">
                    <input class="form-control" type="text" readonly [value]="link" />
                    <button
                      type="button"
                      class="btn btn-outline-secondary"
                      (click)="copyLink(link)"
                    >
                      {{ copied() ? 'Copied!' : 'Copy' }}
                    </button>
                  </div>
                }
                <button
                  type="button"
                  class="btn btn-sm btn-primary"
                  [disabled]="creatingInvite()"
                  (click)="createInvite()"
                >
                  @if (creatingInvite()) {
                    <span class="spinner-border spinner-border-sm me-1"></span>
                  }
                  Create invite link
                </button>
              </div>
            </div>
          }
        } @else {
          <div class="d-flex align-items-center text-body-secondary mt-4">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading team…
          </div>
        }
      </div>
    </div>
  `,
})
export class MyTeamComponent implements OnInit {
  private readonly api = inject(GameApiService);
  private readonly invites = inject(InvitesService);
  private readonly auth = inject(AuthService);

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
    navigator.clipboard?.writeText(link).then(() => this.copied.set(true));
  }
}
