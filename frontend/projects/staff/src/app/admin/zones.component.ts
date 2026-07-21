import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AdminZone, ConquestRule, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface Row {
  zone: AdminZone;
  draft: AdminZone;
  dirty: boolean;
  saving: boolean;
  error: string | null;
}

@Component({
  selector: 'app-admin-zones',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <h1 class="h3 mb-3">Zones</h1>
    <p class="text-body-secondary small">
      Shape / geometry editing stays in the Django admin for now. Here you can rename a zone,
      change its color, or switch scoring.
    </p>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading() && rows().length === 0) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (rows().length === 0) {
      <div class="alert alert-info">No zones yet.</div>
    } @else {
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Name</th>
              <th>Color</th>
              <th>Scoring type</th>
              <th>Conquest rule</th>
              <th>Member towers</th>
              <th>Used by</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.zone.id) {
              <tr>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="row.draft.name"
                    (ngModelChange)="update(row, 'name', $event)"
                  />
                </td>
                <td style="max-width: 8rem">
                  <input
                    class="form-control form-control-color form-control-sm"
                    type="color"
                    [ngModel]="row.draft.color"
                    (ngModelChange)="update(row, 'color', $event)"
                  />
                </td>
                <td style="min-width: 18rem">
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="row.draft.scoring_type"
                    (ngModelChange)="update(row, 'scoring_type', $event)"
                  >
                    <option [ngValue]="1">Logarithmic (more early)</option>
                    <option [ngValue]="2">Exponential (more over time)</option>
                    <option [ngValue]="3">Linear (proportional)</option>
                    <option [ngValue]="4">Bonus (capped 200)</option>
                  </select>
                </td>
                <td style="min-width: 11rem">
                  <!-- Per-zone override; blank inherits the Session
                       override or the Game default. -->
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="row.draft.conquest_rule"
                    (ngModelChange)="update(row, 'conquest_rule', $event)"
                  >
                    <option [ngValue]="null">Inherit</option>
                    @for (o of conquestRuleOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </td>
                <td>
                  <!-- Member towers via the many-to-many
                       (tower-zone-topology); membership is edited from
                       the Towers page. -->
                  @for (t of row.zone.towers; track t.id) {
                    <span class="badge text-bg-light border me-1">{{ t.name }}</span>
                  }
                  @if (row.zone.towers.length === 0) {
                    <span class="badge text-bg-danger">no towers (invalid)</span>
                  }
                </td>
                <td>
                  <!-- Usage guard: which collections + games share this
                       repository zone — edit with awareness. -->
                  @for (c of row.zone.collections; track c.id) {
                    <span class="badge text-bg-light border me-1">{{ c.name }}</span>
                  }
                  @for (g of row.zone.games; track g.id) {
                    <span class="badge text-bg-secondary me-1">{{ g.name }}</span>
                  }
                  @if (row.zone.collections.length === 0) {
                    <span class="text-body-secondary small">orphan</span>
                  }
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
export class ZonesComponent {
  private readonly api = inject(StaffApiService);

  protected readonly rows = signal<Row[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);

  protected readonly conquestRuleOptions: { value: ConquestRule; label: string }[] = [
    { value: 'MAJORITY', label: 'Majority of towers' },
    { value: 'ALL', label: 'All towers' },
    { value: 'ANY', label: 'Any tower' },
  ];

  constructor() {
    this.refresh();
  }

  private refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listZones().subscribe({
      next: (list) => {
        this.rows.set(
          list.map((zone) => ({
            zone,
            draft: { ...zone },
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

  protected update<K extends keyof AdminZone>(row: Row, field: K, value: AdminZone[K]): void {
    const draft = { ...row.draft, [field]: value };
    const dirty = isDirty(draft, row.zone);
    this.rows.update((rows) =>
      rows.map((r) => (r.zone.id === row.zone.id ? { ...r, draft, dirty } : r)),
    );
  }

  protected save(row: Row): void {
    if (!row.dirty || row.saving) return;
    this.patch(row, { saving: true, error: null });
    this.api.updateZone(row.zone.id, row.draft).subscribe({
      next: (updated) => {
        this.rows.update((rows) =>
          rows.map((r) =>
            r.zone.id === row.zone.id
              ? {
                  zone: updated,
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
      rows.map((r) => (r.zone.id === row.zone.id ? { ...r, ...patch } : r)),
    );
  }
}

function isDirty<T extends object>(a: T, b: T): boolean {
  return (Object.keys(a) as (keyof T)[]).some((k) => a[k] !== b[k]);
}
