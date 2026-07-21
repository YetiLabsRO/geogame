import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { FormsModule } from '@angular/forms';

import {
  AdminChallenge,
  AdminGameRole,
  AdminPresenceRequirement,
  AdminTower,
  PresenceMethod,
  StaffApiService,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface Row {
  challenge: AdminChallenge;
  draft: AdminChallenge;
  dirty: boolean;
  saving: boolean;
  error: string | null;
}

@Component({
  selector: 'app-admin-challenges',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, FormsModule],
  template: `
    <h1 class="h3 mb-3">Challenges</h1>

    <div class="card mb-4">
      <div class="card-body">
        <h2 class="h6">Add challenge</h2>
        <p class="small text-body-secondary mb-3">
          Leave Tower empty for a generic challenge that can appear on any tower.
        </p>
        <form [formGroup]="createForm" (ngSubmit)="create()" novalidate>
          <div class="row g-2">
            <div class="col-md-5">
              <textarea
                class="form-control"
                rows="2"
                placeholder="Challenge text"
                formControlName="text"
              ></textarea>
            </div>
            <div class="col-md-3">
              <select class="form-select" formControlName="tower">
                <option [ngValue]="null">Generic (any tower)</option>
                @for (t of towers(); track t.id) {
                  <option [ngValue]="t.id">{{ t.name }}</option>
                }
              </select>
            </div>
            <div class="col-md-2">
              <input
                type="number"
                class="form-control"
                placeholder="Difficulty"
                min="1"
                formControlName="difficulty"
              />
            </div>
            <div class="col-md-2 d-grid">
              <button
                type="submit"
                class="btn btn-primary"
                [disabled]="createForm.invalid || creating()"
              >
                @if (creating()) {
                  <span class="spinner-border spinner-border-sm me-1"></span>
                }
                Add
              </button>
            </div>
          </div>
          @if (createError(); as msg) {
            <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
          }
        </form>
      </div>
    </div>

    <div class="card mb-4">
      <div class="card-body">
        <h2 class="h6">
          Presence requirements
          <span class="text-body-secondary small fw-normal">
            — reusable "≥N people together" rules challenges can reference
            (presence-rules)
          </span>
        </h2>
        @if (requirements().length === 0) {
          <p class="small text-body-secondary mb-2">
            None yet. A challenge without a requirement imposes no presence
            constraint beyond the submitter.
          </p>
        } @else {
          <div class="table-responsive mb-2">
            <table class="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th>Name</th>
                  <th class="text-end">Min members</th>
                  <th>Method</th>
                  <th class="text-end">Radius (m)</th>
                  <th class="text-end">Window (s)</th>
                  <th class="text-end">Used by</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                @for (req of requirements(); track req.id) {
                  <tr>
                    <td>{{ req.name }}</td>
                    <td class="text-end">{{ req.min_members_present }}</td>
                    <td><code>{{ req.method }}</code></td>
                    <td class="text-end">
                      {{ req.geofence_radius_meters ?? 'tower prox.' }}
                    </td>
                    <td class="text-end">{{ req.window_seconds ?? 'session' }}</td>
                    <td class="text-end">{{ req.challenge_count }}</td>
                    <td class="text-end">
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-danger"
                        (click)="removeRequirement(req)"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
        <form [formGroup]="requirementForm" (ngSubmit)="createRequirement()" novalidate>
          <div class="row g-2 align-items-end">
            <div class="col-md-3">
              <label class="form-label small mb-0">Name</label>
              <input class="form-control form-control-sm" formControlName="name" />
            </div>
            <div class="col-md-2">
              <label class="form-label small mb-0">Min members</label>
              <input
                class="form-control form-control-sm"
                type="number"
                min="1"
                formControlName="min_members_present"
              />
            </div>
            <div class="col-md-3">
              <label class="form-label small mb-0">Method</label>
              <select class="form-select form-select-sm" formControlName="method">
                <option [ngValue]="'GEOFENCE'">Geofence</option>
                <option [ngValue]="'PHOTO'">Photo (staff-reviewed)</option>
                <option [ngValue]="'GEOFENCE_OR_PHOTO'">Geofence or photo</option>
              </select>
            </div>
            <div class="col-md-1">
              <label class="form-label small mb-0">Radius</label>
              <input
                class="form-control form-control-sm"
                type="number"
                min="0"
                placeholder="prox."
                formControlName="geofence_radius_meters"
              />
            </div>
            <div class="col-md-1">
              <label class="form-label small mb-0">Window</label>
              <input
                class="form-control form-control-sm"
                type="number"
                min="0"
                placeholder="sess."
                formControlName="window_seconds"
              />
            </div>
            <div class="col-md-2 d-grid">
              <button
                type="submit"
                class="btn btn-sm btn-outline-primary"
                [disabled]="requirementForm.invalid || requirementBusy()"
              >
                Add requirement
              </button>
            </div>
          </div>
          @if (requirementError(); as msg) {
            <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
          }
        </form>
      </div>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading() && rows().length === 0) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (rows().length === 0) {
      <div class="alert alert-info">No challenges yet.</div>
    } @else {
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Text</th>
              <th style="min-width: 12rem">Tower</th>
              <th style="max-width: 6rem">Difficulty</th>
              <th style="min-width: 14rem">Role requirement</th>
              <th style="min-width: 12rem">Presence</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.challenge.id) {
              <tr>
                <td>
                  <textarea
                    class="form-control form-control-sm"
                    rows="2"
                    [ngModel]="row.draft.text"
                    (ngModelChange)="update(row, 'text', $event)"
                  ></textarea>
                </td>
                <td>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="row.draft.tower"
                    (ngModelChange)="update(row, 'tower', $event)"
                  >
                    <option [ngValue]="null">Generic</option>
                    @for (t of towers(); track t.id) {
                      <option [ngValue]="t.id">{{ t.name }}</option>
                    }
                  </select>
                </td>
                <td>
                  <input
                    type="number"
                    class="form-control form-control-sm"
                    min="1"
                    [ngModel]="row.draft.difficulty"
                    (ngModelChange)="update(row, 'difficulty', $event)"
                  />
                </td>
                <td>
                  <select
                    class="form-select form-select-sm mb-1"
                    [ngModel]="row.draft.role_requirement_mode"
                    (ngModelChange)="update(row, 'role_requirement_mode', $event)"
                  >
                    <option [ngValue]="'NONE'">No role requirement</option>
                    <option [ngValue]="'ANY'">Any of the roles…</option>
                    <option [ngValue]="'ALL'">One of each role…</option>
                  </select>
                  @if (row.draft.role_requirement_mode !== 'NONE') {
                    @for (role of roles(); track role.id) {
                      <div class="form-check">
                        <input
                          type="checkbox"
                          class="form-check-input"
                          [id]="'req-' + row.challenge.id + '-' + role.id"
                          [checked]="row.draft.required_roles.includes(role.id)"
                          (change)="toggleRequiredRole(row, role.id)"
                        />
                        <label
                          class="form-check-label small"
                          [for]="'req-' + row.challenge.id + '-' + role.id"
                        >
                          {{ role.name }}
                        </label>
                      </div>
                    } @empty {
                      <div class="small text-warning">
                        No roles defined for this game yet.
                      </div>
                    }
                    <div class="form-check">
                      <input
                        type="checkbox"
                        class="form-check-input"
                        [id]="'holders-' + row.challenge.id"
                        [checked]="row.draft.require_holders_present"
                        (change)="
                          update(
                            row,
                            'require_holders_present',
                            !row.draft.require_holders_present
                          )
                        "
                      />
                      <label
                        class="form-check-label small"
                        [for]="'holders-' + row.challenge.id"
                      >
                        Holders must be present (presence rules)
                      </label>
                    </div>
                  }
                </td>
                <td>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="row.draft.presence_requirement"
                    (ngModelChange)="update(row, 'presence_requirement', $event)"
                  >
                    <option [ngValue]="null">No presence requirement</option>
                    @for (req of requirements(); track req.id) {
                      <option [ngValue]="req.id">
                        {{ req.name }} (≥{{ req.min_members_present }},
                        {{ req.method }})
                      </option>
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
                      @if (row.saving) {
                        <span class="spinner-border spinner-border-sm me-1"></span>
                      }
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
    }
  `,
})
export class ChallengesComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly api = inject(StaffApiService);

  protected readonly rows = signal<Row[]>([]);
  protected readonly towers = signal<AdminTower[]>([]);
  protected readonly roles = signal<AdminGameRole[]>([]);
  protected readonly requirements = signal<AdminPresenceRequirement[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);
  protected readonly requirementBusy = signal(false);
  protected readonly requirementError = signal<string | null>(null);

  protected readonly createForm = this.fb.group({
    text: ['', [Validators.required]],
    tower: [null as number | null],
    difficulty: [1, [Validators.required, Validators.min(1)]],
  });

  protected readonly requirementForm = this.fb.group({
    name: ['', [Validators.required]],
    min_members_present: [2, [Validators.required, Validators.min(1)]],
    method: ['GEOFENCE' as PresenceMethod, [Validators.required]],
    geofence_radius_meters: [null as number | null],
    window_seconds: [null as number | null],
  });

  constructor() {
    this.refresh();
    this.api.listTowers().subscribe({
      next: (list) => this.towers.set(list),
      error: () => {},
    });
    // Roles of the current session's Game (server-side fallback scope).
    this.api.listGameRoles().subscribe({
      next: (list) => this.roles.set(list),
      error: () => {},
    });
    this.refreshRequirements();
  }

  private refreshRequirements(): void {
    this.api.listPresenceRequirements().subscribe({
      next: (list) => this.requirements.set(list),
      error: () => {},
    });
  }

  protected createRequirement(): void {
    if (this.requirementForm.invalid || this.requirementBusy()) return;
    this.requirementBusy.set(true);
    this.requirementError.set(null);
    const raw = this.requirementForm.getRawValue();
    this.api
      .createPresenceRequirement({
        name: raw.name,
        min_members_present: raw.min_members_present,
        method: raw.method,
        geofence_radius_meters: raw.geofence_radius_meters,
        window_seconds: raw.window_seconds,
      })
      .subscribe({
        next: () => {
          this.requirementBusy.set(false);
          this.requirementForm.reset({
            name: '',
            min_members_present: 2,
            method: 'GEOFENCE',
            geofence_radius_meters: null,
            window_seconds: null,
          });
          this.refreshRequirements();
        },
        error: (err) => {
          this.requirementBusy.set(false);
          this.requirementError.set(extractErrorMessage(err));
        },
      });
  }

  protected removeRequirement(req: AdminPresenceRequirement): void {
    const suffix =
      req.challenge_count > 0
        ? ` It is referenced by ${req.challenge_count} challenge(s); they will ` +
          'simply lose the requirement.'
        : '';
    if (!confirm(`Delete presence requirement "${req.name}"?${suffix}`)) return;
    this.api.deletePresenceRequirement(req.id).subscribe({
      next: () => {
        this.refreshRequirements();
        // Detached challenges now have presence_requirement = null.
        this.refresh();
      },
      error: (err) => this.requirementError.set(extractErrorMessage(err)),
    });
  }

  protected toggleRequiredRole(row: Row, roleId: number): void {
    const current = row.draft.required_roles;
    const next = current.includes(roleId)
      ? current.filter((id) => id !== roleId)
      : [...current, roleId];
    this.update(row, 'required_roles', next);
  }

  private refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listChallenges().subscribe({
      next: (list) => {
        this.rows.set(
          list.map((challenge) => ({
            challenge,
            draft: { ...challenge },
            dirty: false,
            saving: false,
            error: null,
          })),
        );
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected create(): void {
    if (this.createForm.invalid || this.creating()) return;
    this.creating.set(true);
    this.createError.set(null);
    const raw = this.createForm.getRawValue();
    this.api
      .createChallenge({
        text: raw.text,
        tower: raw.tower,
        difficulty: raw.difficulty,
        // game is derived server-side once T3.5 scoping lands; in the
        // meantime the backfill migration covers existing rows.
        game: null,
        // Role requirement defaults to "none"; edit it on the row after
        // creation (team-roles capability).
        role_requirement_mode: 'NONE',
        required_roles: [],
        require_holders_present: false,
        // Presence requirement defaults to none (presence-rules).
        presence_requirement: null,
      })
      .subscribe({
        next: () => {
          this.creating.set(false);
          this.createForm.reset({ text: '', tower: null, difficulty: 1 });
          this.refresh();
        },
        error: (err) => {
          this.creating.set(false);
          this.createError.set(extractErrorMessage(err));
        },
      });
  }

  protected update<K extends keyof AdminChallenge>(
    row: Row,
    field: K,
    value: AdminChallenge[K],
  ): void {
    const draft = { ...row.draft, [field]: value };
    const dirty = isDirty(draft, row.challenge);
    this.rows.update((rows) =>
      rows.map((r) =>
        r.challenge.id === row.challenge.id ? { ...r, draft, dirty } : r,
      ),
    );
  }

  protected save(row: Row): void {
    if (!row.dirty || row.saving) return;
    this.patch(row, { saving: true, error: null });
    this.api.updateChallenge(row.challenge.id, row.draft).subscribe({
      next: (updated) => {
        this.rows.update((rows) =>
          rows.map((r) =>
            r.challenge.id === row.challenge.id
              ? {
                  challenge: updated,
                  draft: { ...updated },
                  dirty: false,
                  saving: false,
                  error: null,
                }
              : r,
          ),
        );
      },
      error: (err) => {
        this.patch(row, { saving: false, error: extractErrorMessage(err) });
      },
    });
  }

  protected remove(row: Row): void {
    if (row.saving) return;
    if (!confirm(`Delete this challenge? This can't be undone.`)) return;
    this.patch(row, { saving: true, error: null });
    this.api.deleteChallenge(row.challenge.id).subscribe({
      next: () => {
        this.rows.update((rows) =>
          rows.filter((r) => r.challenge.id !== row.challenge.id),
        );
      },
      error: (err) => {
        this.patch(row, { saving: false, error: extractErrorMessage(err) });
      },
    });
  }

  private patch(row: Row, patch: Partial<Row>): void {
    this.rows.update((rows) =>
      rows.map((r) =>
        r.challenge.id === row.challenge.id ? { ...r, ...patch } : r,
      ),
    );
  }
}

function isDirty<T extends object>(a: T, b: T): boolean {
  return (Object.keys(a) as (keyof T)[]).some((k) => a[k] !== b[k]);
}
