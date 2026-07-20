import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AdminTower, AdminZone, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface Row {
  tower: AdminTower;
  draft: AdminTower;
  dirty: boolean;
  saving: boolean;
  error: string | null;
}

@Component({
  selector: 'app-admin-towers',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h1 class="h3 mb-0">Towers</h1>
      <button
        type="button"
        class="btn btn-sm btn-outline-danger"
        [disabled]="unassigningAll()"
        (click)="unassignAll()"
      >
        @if (unassigningAll()) {
          <span class="spinner-border spinner-border-sm me-1"></span>
        }
        Unassign all (end game)
      </button>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }
    @if (actionNotice(); as msg) {
      <div class="alert alert-success py-2">{{ msg }}</div>
    }

    @if (loading() && rows().length === 0) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (rows().length === 0) {
      <div class="alert alert-info">No towers yet.</div>
    } @else {
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Name</th>
              <th>Zone</th>
              <th>Category</th>
              <th>Initial bonus</th>
              <th>RFID code</th>
              <th>Used by</th>
              <th>Active</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.tower.id) {
              <tr>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="row.draft.name"
                    (ngModelChange)="update(row, 'name', $event)"
                  />
                </td>
                <td style="min-width: 12rem">
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="row.draft.zone"
                    (ngModelChange)="update(row, 'zone', $event)"
                  >
                    <option [ngValue]="null">—</option>
                    @for (z of zones(); track z.id) {
                      <option [ngValue]="z.id">{{ z.name }}</option>
                    }
                  </select>
                </td>
                <td>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="row.draft.category"
                    (ngModelChange)="update(row, 'category', $event)"
                  >
                    <option [ngValue]="1">Normal</option>
                    <option [ngValue]="2">RFID</option>
                  </select>
                </td>
                <td style="max-width: 8rem">
                  <input
                    class="form-control form-control-sm"
                    type="number"
                    [ngModel]="row.draft.initial_bonus"
                    (ngModelChange)="update(row, 'initial_bonus', $event)"
                  />
                </td>
                <td style="max-width: 10rem">
                  <input
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="row.draft.rfid_code"
                    (ngModelChange)="update(row, 'rfid_code', $event)"
                  />
                </td>
                <td>
                  <!-- Usage guard: which collections + games share this
                       repository tower — edit with awareness. -->
                  @for (c of row.tower.collections; track c.id) {
                    <span class="badge text-bg-light border me-1">{{ c.name }}</span>
                  }
                  @for (g of row.tower.games; track g.id) {
                    <span class="badge text-bg-secondary me-1">{{ g.name }}</span>
                  }
                  @if (row.tower.collections.length === 0) {
                    <span class="text-body-secondary small">orphan</span>
                  }
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
                      (click)="unassign(row)"
                    >
                      Unassign
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
export class TowersComponent {
  private readonly api = inject(StaffApiService);

  protected readonly rows = signal<Row[]>([]);
  protected readonly zones = signal<AdminZone[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly unassigningAll = signal(false);
  protected readonly actionNotice = signal<string | null>(null);

  constructor() {
    this.refresh();
    this.api.listZones().subscribe({
      next: (list) => this.zones.set(list),
      error: () => {},
    });
  }

  private refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listTowers().subscribe({
      next: (list) => {
        this.rows.set(
          list.map((tower) => ({
            tower,
            draft: { ...tower },
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

  protected update<K extends keyof AdminTower>(row: Row, field: K, value: AdminTower[K]): void {
    const draft = { ...row.draft, [field]: value };
    const dirty = isDirty(draft, row.tower);
    this.rows.update((rows) =>
      rows.map((r) => (r.tower.id === row.tower.id ? { ...r, draft, dirty } : r)),
    );
  }

  protected save(row: Row): void {
    if (!row.dirty || row.saving) return;
    this.patchRow(row, { saving: true, error: null });
    this.api.updateTower(row.tower.id, row.draft).subscribe({
      next: (updated) => {
        this.rows.update((rows) =>
          rows.map((r) =>
            r.tower.id === row.tower.id
              ? {
                  tower: updated,
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
        this.patchRow(row, { saving: false, error: extractErrorMessage(err) });
      },
    });
  }

  protected unassign(row: Row): void {
    if (row.saving) return;
    this.patchRow(row, { saving: true, error: null });
    this.api.unassignTower(row.tower.id).subscribe({
      next: () => {
        this.patchRow(row, { saving: false });
        this.actionNotice.set(`${row.tower.name} unassigned.`);
      },
      error: (err) => {
        this.patchRow(row, { saving: false, error: extractErrorMessage(err) });
      },
    });
  }

  protected unassignAll(): void {
    if (this.unassigningAll()) return;
    if (!confirm('Close ALL active tower ownerships? This ends the game round.')) {
      return;
    }
    this.unassigningAll.set(true);
    this.api.unassignAllTowers().subscribe({
      next: (res) => {
        this.unassigningAll.set(false);
        this.actionNotice.set(
          `Unassigned ${res.unassigned.length} tower(s).`,
        );
      },
      error: (err) => {
        this.unassigningAll.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  private patchRow(row: Row, patch: Partial<Row>): void {
    this.rows.update((rows) =>
      rows.map((r) => (r.tower.id === row.tower.id ? { ...r, ...patch } : r)),
    );
  }
}

function isDirty<T extends object>(a: T, b: T): boolean {
  return (Object.keys(a) as (keyof T)[]).some((k) => a[k] !== b[k]);
}
