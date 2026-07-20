import {
  ChangeDetectionStrategy,
  Component,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AdminGameRole, BuiltinPower, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface RoleRow {
  role: AdminGameRole;
  draft: AdminGameRole;
  dirty: boolean;
  saving: boolean;
  error: string | null;
}

/**
 * Wireframe role manager for one Game (team-roles capability).
 * Embedded in an expanded row on the Games page.
 */
@Component({
  selector: 'app-game-roles-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="fw-semibold small mb-2">In-game roles</div>
    <p class="small text-body-secondary mb-2">
      Roles are part of this Game's rule set: assign them to team members and
      require them on challenges. The INVITER power lets a holder invite
      players into their own team.
    </p>

    @if (loadError(); as msg) {
      <div class="alert alert-danger py-2">{{ msg }}</div>
    }

    @if (rows().length > 0) {
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead>
            <tr>
              <th>Name</th>
              <th>Slug</th>
              <th>Description</th>
              <th>Built-in power</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.role.id) {
              <tr>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="row.draft.name"
                    (ngModelChange)="update(row, 'name', $event)"
                  />
                </td>
                <td><code>{{ row.role.slug }}</code></td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="row.draft.description"
                    (ngModelChange)="update(row, 'description', $event)"
                  />
                </td>
                <td style="min-width: 9rem">
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="row.draft.builtin_power"
                    (ngModelChange)="update(row, 'builtin_power', $event)"
                  >
                    @for (p of powers; track p.value) {
                      <option [ngValue]="p.value">{{ p.label }}</option>
                    }
                  </select>
                </td>
                <td class="text-end">
                  <div class="d-flex gap-2 justify-content-end">
                    <button
                      type="button"
                      class="btn btn-sm btn-primary"
                      [disabled]="!row.dirty || row.saving"
                      (click)="save(row)"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-danger"
                      [disabled]="row.saving"
                      (click)="remove(row)"
                    >
                      Delete
                    </button>
                  </div>
                  @if (row.error; as msg) {
                    <div class="small text-danger mt-1">{{ msg }}</div>
                  }
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>
    } @else if (!loadError()) {
      <div class="small text-body-secondary mb-2">No roles defined yet.</div>
    }

    <form class="row g-2 align-items-end" (ngSubmit)="create()">
      <div class="col-md-3">
        <label class="form-label small mb-0" [for]="'role-name-' + gameId()">Name</label>
        <input
          [id]="'role-name-' + gameId()"
          class="form-control form-control-sm"
          type="text"
          [(ngModel)]="newName"
          name="name"
          required
        />
      </div>
      <div class="col-md-3">
        <label class="form-label small mb-0" [for]="'role-slug-' + gameId()">Slug</label>
        <input
          [id]="'role-slug-' + gameId()"
          class="form-control form-control-sm"
          type="text"
          [(ngModel)]="newSlug"
          name="slug"
          placeholder="url-safe"
          required
        />
      </div>
      <div class="col-md-3">
        <label class="form-label small mb-0" [for]="'role-power-' + gameId()">
          Built-in power
        </label>
        <select
          [id]="'role-power-' + gameId()"
          class="form-select form-select-sm"
          [(ngModel)]="newPower"
          name="builtin_power"
        >
          @for (p of powers; track p.value) {
            <option [ngValue]="p.value">{{ p.label }}</option>
          }
        </select>
      </div>
      <div class="col-md-3">
        <button
          type="submit"
          class="btn btn-sm btn-primary"
          [disabled]="creating() || !newName || !newSlug"
        >
          @if (creating()) {
            <span class="spinner-border spinner-border-sm me-1"></span>
          }
          Add role
        </button>
      </div>
      @if (createError(); as msg) {
        <div class="col-12"><div class="small text-danger">{{ msg }}</div></div>
      }
    </form>
  `,
})
export class GameRolesPanelComponent {
  private readonly api = inject(StaffApiService);

  readonly gameId = input.required<number>();

  protected readonly rows = signal<RoleRow[]>([]);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);

  protected newName = '';
  protected newSlug = '';
  protected newPower: BuiltinPower = 'NONE';

  protected readonly powers: { value: BuiltinPower; label: string }[] = [
    { value: 'NONE', label: 'None' },
    { value: 'INVITER', label: 'Inviter' },
  ];

  constructor() {
    effect(() => {
      this.gameId();
      this.refresh();
    });
  }

  private refresh(): void {
    this.loadError.set(null);
    this.api.listGameRoles(this.gameId()).subscribe({
      next: (list) =>
        this.rows.set(
          list.map((role) => ({
            role,
            draft: { ...role },
            dirty: false,
            saving: false,
            error: null,
          })),
        ),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected create(): void {
    if (this.creating() || !this.newName || !this.newSlug) return;
    this.creating.set(true);
    this.createError.set(null);
    this.api
      .createGameRole({
        game: this.gameId(),
        name: this.newName,
        slug: this.newSlug,
        builtin_power: this.newPower,
      })
      .subscribe({
        next: () => {
          this.creating.set(false);
          this.newName = '';
          this.newSlug = '';
          this.newPower = 'NONE';
          this.refresh();
        },
        error: (err) => {
          this.creating.set(false);
          this.createError.set(extractErrorMessage(err));
        },
      });
  }

  protected update<K extends keyof AdminGameRole>(
    row: RoleRow,
    field: K,
    value: AdminGameRole[K],
  ): void {
    const draft = { ...row.draft, [field]: value };
    const dirty = (Object.keys(draft) as (keyof AdminGameRole)[]).some(
      (k) => draft[k] !== row.role[k],
    );
    this.patch(row, { draft, dirty });
  }

  protected save(row: RoleRow): void {
    if (!row.dirty || row.saving) return;
    this.patch(row, { saving: true, error: null });
    this.api
      .updateGameRole(row.role.id, {
        name: row.draft.name,
        description: row.draft.description,
        builtin_power: row.draft.builtin_power,
      })
      .subscribe({
        next: (updated) =>
          this.rows.update((rows) =>
            rows.map((r) =>
              r.role.id === row.role.id
                ? { role: updated, draft: { ...updated }, dirty: false, saving: false, error: null }
                : r,
            ),
          ),
        error: (err) => this.patch(row, { saving: false, error: extractErrorMessage(err) }),
      });
  }

  protected remove(row: RoleRow): void {
    if (row.saving) return;
    if (!confirm(`Delete role "${row.role.name}"?`)) return;
    this.patch(row, { saving: true, error: null });
    this.api.deleteGameRole(row.role.id).subscribe({
      next: () => this.rows.update((rows) => rows.filter((r) => r.role.id !== row.role.id)),
      error: (err) => this.patch(row, { saving: false, error: extractErrorMessage(err) }),
    });
  }

  private patch(row: RoleRow, patch: Partial<RoleRow>): void {
    this.rows.update((rows) =>
      rows.map((r) => (r.role.id === row.role.id ? { ...r, ...patch } : r)),
    );
  }
}
