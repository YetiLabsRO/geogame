import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AdminGameRole, AdminMembership, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/**
 * Wireframe roster panel for one team (team-roles capability): active
 * members with their role badges plus assign/unassign controls. The
 * role picker only offers the team's Game's roles.
 */
@Component({
  selector: 'app-team-roster-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="fw-semibold small mb-2">Roster &amp; roles</div>

    @if (error(); as msg) {
      <div class="alert alert-danger py-2">{{ msg }}</div>
    }

    @if (members().length === 0 && !error()) {
      <div class="small text-body-secondary">No active members.</div>
    } @else {
      <table class="table table-sm align-middle mb-2">
        <thead>
          <tr>
            <th>Member</th>
            <th>Roles</th>
            <th style="min-width: 16rem">Assign</th>
          </tr>
        </thead>
        <tbody>
          @for (m of members(); track m.id) {
            <tr>
              <td>
                {{ m.username }}
                @if (m.first_name || m.last_name) {
                  <span class="text-body-secondary small">
                    ({{ m.first_name }} {{ m.last_name }})
                  </span>
                }
              </td>
              <td>
                @for (role of m.roles; track role.id) {
                  <span class="badge text-bg-secondary me-1">
                    {{ role.name }}
                    @if (role.builtin_power !== 'NONE') {
                      <i class="bi bi-lightning-charge-fill"></i>
                    }
                    <button
                      type="button"
                      class="btn-close btn-close-white ms-1"
                      style="font-size: 0.55em"
                      title="Unassign"
                      (click)="unassign(m, role.id)"
                    ></button>
                  </span>
                } @empty {
                  <span class="text-body-secondary small">—</span>
                }
              </td>
              <td>
                <div class="d-flex gap-2">
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="picks()[m.id] ?? null"
                    (ngModelChange)="pick(m.id, $event)"
                  >
                    <option [ngValue]="null">Pick a role…</option>
                    @for (role of roles(); track role.id) {
                      <option [ngValue]="role.id">{{ role.name }}</option>
                    }
                  </select>
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-primary"
                    [disabled]="!picks()[m.id]"
                    (click)="assign(m)"
                  >
                    Assign
                  </button>
                </div>
              </td>
            </tr>
          }
        </tbody>
      </table>
    }
    @if (roles().length === 0) {
      <div class="small text-body-secondary">
        This Game defines no roles yet — add some on the Games page.
      </div>
    }
  `,
})
export class TeamRosterPanelComponent {
  private readonly api = inject(StaffApiService);

  readonly teamId = input.required<number>();
  readonly gameId = input.required<number>();

  protected readonly members = signal<AdminMembership[]>([]);
  protected readonly roles = signal<AdminGameRole[]>([]);
  protected readonly picks = signal<Record<number, number | null>>({});
  protected readonly error = signal<string | null>(null);

  constructor() {
    effect(() => {
      this.teamId();
      this.refreshMembers();
    });
    effect(() => {
      const gameId = this.gameId();
      this.api.listGameRoles(gameId).subscribe({
        next: (list) => this.roles.set(list),
        error: (err) => this.error.set(extractErrorMessage(err)),
      });
    });
  }

  private refreshMembers(): void {
    this.api.listMemberships(this.teamId()).subscribe({
      next: (list) => this.members.set(list.filter((m) => m.is_active)),
      error: (err) => this.error.set(extractErrorMessage(err)),
    });
  }

  protected pick(membershipId: number, roleId: number | null): void {
    this.picks.update((p) => ({ ...p, [membershipId]: roleId }));
  }

  protected assign(member: AdminMembership): void {
    const roleId = this.picks()[member.id];
    if (!roleId) return;
    this.error.set(null);
    this.api.assignRole(member.id, roleId).subscribe({
      next: (updated) => {
        this.replace(updated);
        this.pick(member.id, null);
      },
      error: (err) => this.error.set(extractErrorMessage(err)),
    });
  }

  protected unassign(member: AdminMembership, roleId: number): void {
    this.error.set(null);
    this.api.unassignRole(member.id, roleId).subscribe({
      next: (updated) => this.replace(updated),
      error: (err) => this.error.set(extractErrorMessage(err)),
    });
  }

  private replace(updated: AdminMembership): void {
    this.members.update((list) =>
      list.map((m) => (m.id === updated.id ? updated : m)),
    );
  }
}
