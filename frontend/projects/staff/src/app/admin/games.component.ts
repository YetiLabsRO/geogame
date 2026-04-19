import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators, FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import { AdminGame, AdminGamePayload, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface Row {
  game: AdminGame;
  draft: AdminGame;
  dirty: boolean;
  saving: boolean;
  error: string | null;
}

@Component({
  selector: 'app-admin-games',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, FormsModule, RouterLink],
  template: `
    <h1 class="h3 mb-3">Games</h1>
    <p class="text-body-secondary small">
      A Game is reusable event configuration — map defaults, rules, and the
      challenge bank. Each Game can host one or more Sessions on the
      <a routerLink="/sessions">Sessions</a> page.
    </p>

    <div class="card mb-4">
      <div class="card-body">
        <h2 class="h6 mb-3">Create game</h2>
        <form [formGroup]="createForm" (ngSubmit)="create()" novalidate>
          <div class="row g-2">
            <div class="col-md-4">
              <input
                class="form-control"
                type="text"
                placeholder="Slug (unique, URL-safe)"
                formControlName="slug"
              />
            </div>
            <div class="col-md-4">
              <input
                class="form-control"
                type="text"
                placeholder="Name"
                formControlName="name"
              />
            </div>
            <div class="col-md-2">
              <input
                class="form-control"
                type="number"
                step="any"
                placeholder="Base lat"
                formControlName="base_lat"
              />
            </div>
            <div class="col-md-2">
              <input
                class="form-control"
                type="number"
                step="any"
                placeholder="Base lng"
                formControlName="base_lng"
              />
            </div>
          </div>
          @if (createError(); as msg) {
            <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
          }
          <button
            type="submit"
            class="btn btn-primary mt-3"
            [disabled]="createForm.invalid || creating()"
          >
            @if (creating()) {
              <span class="spinner-border spinner-border-sm me-1"></span>
            }
            Create game
          </button>
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
      <div class="alert alert-info">No games yet.</div>
    } @else {
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Slug</th>
              <th>Name</th>
              <th style="max-width: 8rem">Prox (m)</th>
              <th style="max-width: 8rem">Cooloff (min)</th>
              <th style="max-width: 8rem">Init bonus</th>
              <th>Active</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.game.id) {
              <tr>
                <td><code>{{ row.game.slug }}</code></td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="row.draft.name"
                    (ngModelChange)="update(row, 'name', $event)"
                  />
                </td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="number"
                    min="1"
                    [ngModel]="row.draft.proximity_meters"
                    (ngModelChange)="update(row, 'proximity_meters', $event)"
                  />
                </td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="number"
                    min="0"
                    [ngModel]="row.draft.cooloff_minutes"
                    (ngModelChange)="update(row, 'cooloff_minutes', $event)"
                  />
                </td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="number"
                    min="0"
                    [ngModel]="row.draft.initial_bonus_default"
                    (ngModelChange)="update(row, 'initial_bonus_default', $event)"
                  />
                </td>
                <td class="text-center">
                  <div class="form-check form-switch d-inline-block">
                    <input
                      type="checkbox"
                      class="form-check-input"
                      role="switch"
                      [ngModel]="row.draft.is_active"
                      (ngModelChange)="update(row, 'is_active', $event)"
                    />
                  </div>
                </td>
                <td class="text-end">
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
export class GamesComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly api = inject(StaffApiService);

  protected readonly rows = signal<Row[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);

  protected readonly createForm = this.fb.group({
    slug: ['', [Validators.required]],
    name: ['', [Validators.required]],
    base_lat: [null as number | null],
    base_lng: [null as number | null],
  });

  constructor() {
    this.refresh();
  }

  private refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listGames().subscribe({
      next: (list) => {
        this.rows.set(
          list.map((game) => ({
            game,
            draft: { ...game },
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
    const payload: AdminGamePayload = {
      slug: raw.slug,
      name: raw.name,
      is_active: false,
    };
    if (raw.base_lat !== null && raw.base_lng !== null) {
      payload.base_lat = raw.base_lat;
      payload.base_lng = raw.base_lng;
    }
    this.api.createGame(payload).subscribe({
      next: () => {
        this.creating.set(false);
        this.createForm.reset({
          slug: '',
          name: '',
          base_lat: null,
          base_lng: null,
        });
        this.refresh();
      },
      error: (err) => {
        this.creating.set(false);
        this.createError.set(extractErrorMessage(err));
      },
    });
  }

  protected update<K extends keyof AdminGame>(
    row: Row,
    field: K,
    value: AdminGame[K],
  ): void {
    const draft = { ...row.draft, [field]: value };
    const dirty = isDirty(draft, row.game);
    this.rows.update((rows) =>
      rows.map((r) => (r.game.id === row.game.id ? { ...r, draft, dirty } : r)),
    );
  }

  protected save(row: Row): void {
    if (!row.dirty || row.saving) return;
    this.patch(row, { saving: true, error: null });
    this.api
      .updateGame(row.game.id, {
        name: row.draft.name,
        is_active: row.draft.is_active,
        proximity_meters: row.draft.proximity_meters,
        cooloff_minutes: row.draft.cooloff_minutes,
        initial_bonus_default: row.draft.initial_bonus_default,
      })
      .subscribe({
        next: (updated) => {
          this.rows.update((rows) =>
            rows.map((r) =>
              r.game.id === row.game.id
                ? {
                    game: updated,
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

  private patch(row: Row, patch: Partial<Row>): void {
    this.rows.update((rows) =>
      rows.map((r) => (r.game.id === row.game.id ? { ...r, ...patch } : r)),
    );
  }
}

function isDirty<T extends object>(a: T, b: T): boolean {
  return (Object.keys(a) as (keyof T)[]).some((k) => a[k] !== b[k]);
}
