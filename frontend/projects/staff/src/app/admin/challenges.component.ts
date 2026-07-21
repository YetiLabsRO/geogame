import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { FormsModule } from '@angular/forms';

import { AdminChallenge, AdminGameRole, AdminTower, StaffApiService } from 'shared';

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
            <div class="col-md-4">
              <textarea
                class="form-control"
                rows="2"
                placeholder="Challenge text"
                formControlName="text"
              ></textarea>
            </div>
            <div class="col-md-2">
              <select class="form-select" formControlName="type">
                @for (t of typeOptions; track t.value) {
                  <option [ngValue]="t.value">{{ t.label }}</option>
                }
              </select>
            </div>
            <div class="col-md-3">
              <select class="form-select" formControlName="tower">
                <option [ngValue]="null">Generic (any tower)</option>
                @for (t of towers(); track t.id) {
                  <option [ngValue]="t.id">{{ t.name }}</option>
                }
              </select>
            </div>
            <div class="col-md-1">
              <input
                type="number"
                class="form-control"
                placeholder="Diff."
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
          @if (createForm.value.type === 'NFC_QR') {
            <div class="row g-2 mt-1">
              <div class="col-md-4">
                <input
                  type="text"
                  class="form-control"
                  placeholder="Validation code (handed out at the venue)"
                  formControlName="validation_code"
                />
              </div>
              <div class="col-md-8 form-text">
                The code embedded in the QR/NFC the venue hands out. Required
                unless the challenge is switched to manual review after
                creation.
              </div>
            </div>
          }
          @if (createError(); as msg) {
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
              <th style="min-width: 14rem">Type</th>
              <th style="min-width: 12rem">Tower</th>
              <th style="max-width: 6rem">Difficulty</th>
              <th style="min-width: 14rem">Role requirement</th>
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
                    class="form-select form-select-sm mb-1"
                    [ngModel]="row.draft.type"
                    (ngModelChange)="update(row, 'type', $event)"
                  >
                    @for (t of typeOptions; track t.value) {
                      <option [ngValue]="t.value">{{ t.label }}</option>
                    }
                  </select>
                  @if (row.draft.type === 'NFC_QR') {
                    <input
                      type="text"
                      class="form-control form-control-sm mb-1"
                      placeholder="Validation code"
                      [ngModel]="row.draft.validation_code"
                      (ngModelChange)="update(row, 'validation_code', $event)"
                    />
                    <input
                      type="text"
                      class="form-control form-control-sm mb-1"
                      placeholder="Venue label (e.g. Bar X)"
                      [ngModel]="venueLabel(row)"
                      (ngModelChange)="updateConfig(row, 'venue_label', $event)"
                    />
                    <div class="form-check">
                      <input
                        type="checkbox"
                        class="form-check-input"
                        [id]="'single-use-' + row.challenge.id"
                        [checked]="singleUse(row)"
                        (change)="updateConfig(row, 'single_use', !singleUse(row))"
                      />
                      <label
                        class="form-check-label small"
                        [for]="'single-use-' + row.challenge.id"
                      >
                        Single-use code (consumed on first confirm)
                      </label>
                    </div>
                  } @else if (row.draft.type === 'RFID') {
                    <div class="small text-body-secondary mb-1">
                      Code comes from the tower's RFID tag.
                    </div>
                  }
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="row.draft.review_mode"
                    (ngModelChange)="update(row, 'review_mode', $event)"
                  >
                    <option [ngValue]="null">Review: type default</option>
                    <option [ngValue]="'AUTO'">Review: force auto</option>
                    <option [ngValue]="'MANUAL'">Review: force manual</option>
                  </select>
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
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);

  /** challenge-type-system: authoring options for Challenge.type. */
  protected readonly typeOptions = [
    { value: 'TEXT', label: 'Text question (staff-reviewed)' },
    { value: 'PHOTO', label: 'Photo evidence (staff-reviewed)' },
    { value: 'NFC_QR', label: 'NFC/QR venue code (auto)' },
    { value: 'RFID', label: 'RFID tag scan (auto)' },
  ] as const;

  protected readonly createForm = this.fb.group({
    text: ['', [Validators.required]],
    type: ['TEXT'],
    validation_code: [''],
    tower: [null as number | null],
    difficulty: [1, [Validators.required, Validators.min(1)]],
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
  }

  // --- challenge-type-system: type_config helpers -------------------------

  protected venueLabel(row: Row): string {
    const label = row.draft.type_config?.['venue_label'];
    return typeof label === 'string' ? label : '';
  }

  protected singleUse(row: Row): boolean {
    return row.draft.type_config?.['single_use'] === true;
  }

  protected updateConfig(row: Row, key: string, value: unknown): void {
    const config = { ...(row.draft.type_config ?? {}) };
    if (value === '' || value === false || value == null) {
      delete config[key];
    } else {
      config[key] = value;
    }
    this.update(row, 'type_config', config);
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
        // challenge-type-system: type + per-type config. Venue label /
        // single-use are edited on the row after creation.
        type: raw.type,
        validation_code: raw.validation_code.trim() || null,
        type_config: {},
        review_mode: null,
        // game is derived server-side once T3.5 scoping lands; in the
        // meantime the backfill migration covers existing rows.
        game: null,
        // Role requirement defaults to "none"; edit it on the row after
        // creation (team-roles capability).
        role_requirement_mode: 'NONE',
        required_roles: [],
        require_holders_present: false,
      })
      .subscribe({
        next: () => {
          this.creating.set(false);
          this.createForm.reset({
            text: '',
            type: 'TEXT',
            validation_code: '',
            tower: null,
            difficulty: 1,
          });
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
