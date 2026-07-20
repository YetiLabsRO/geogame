import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { AdminTeam, AdminTeamGroup, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';
import { TeamRosterPanelComponent } from './team-roster-panel.component';

interface Row {
  team: AdminTeam;
  draft: AdminTeam;
  dirty: boolean;
  saving: boolean;
  error: string | null;
}

@Component({
  selector: 'app-admin-teams',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, TeamRosterPanelComponent],
  template: `
    <h1 class="h3 mb-3">Teams</h1>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading() && rows().length === 0) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (rows().length === 0) {
      <div class="alert alert-info">No teams yet.</div>
    } @else {
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Name</th>
              <th>Group</th>
              <th>Color</th>
              <th>Description</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.team.id) {
              <tr>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="row.draft.name"
                    (ngModelChange)="update(row, 'name', $event)"
                  />
                </td>
                <td style="min-width: 10rem">
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="row.draft.group"
                    (ngModelChange)="update(row, 'group', $event)"
                  >
                    <option [ngValue]="null">—</option>
                    @for (g of groups(); track g.id) {
                      <option [ngValue]="g.id">{{ g.name }}</option>
                    }
                  </select>
                </td>
                <td style="max-width: 6rem">
                  <input
                    class="form-control form-control-color form-control-sm"
                    type="color"
                    [ngModel]="row.draft.color"
                    (ngModelChange)="update(row, 'color', $event)"
                  />
                </td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="row.draft.description"
                    (ngModelChange)="update(row, 'description', $event)"
                  />
                </td>
                <td class="text-end">
                  <div class="d-flex gap-2 justify-content-end">
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      (click)="toggleRoster(row.team.id)"
                    >
                      Roster
                    </button>
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
                  </div>
                  @if (row.error; as msg) {
                    <div class="small text-danger mt-1">{{ msg }}</div>
                  }
                </td>
              </tr>
              @if (rosterExpanded().has(row.team.id)) {
                <tr class="table-light">
                  <td colspan="5">
                    <app-team-roster-panel
                      [teamId]="row.team.id"
                      [gameId]="row.team.game"
                    />
                  </td>
                </tr>
              }
            }
          </tbody>
        </table>
      </div>
    }
  `,
})
export class TeamsComponent {
  private readonly api = inject(StaffApiService);

  protected readonly rows = signal<Row[]>([]);
  protected readonly groups = signal<AdminTeamGroup[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly rosterExpanded = signal<Set<number>>(new Set<number>());

  protected toggleRoster(id: number): void {
    this.rosterExpanded.update((set) => {
      const next = new Set(set);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  constructor() {
    this.refresh();
    this.api.listTeamGroups().subscribe({
      next: (list) => this.groups.set(list),
      error: () => {},
    });
  }

  private refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listTeams().subscribe({
      next: (list) => {
        this.rows.set(
          list.map((team) => ({
            team,
            draft: { ...team },
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

  protected update<K extends keyof AdminTeam>(row: Row, field: K, value: AdminTeam[K]): void {
    const draft = { ...row.draft, [field]: value };
    const dirty = isDirty(draft, row.team);
    this.rows.update((rows) =>
      rows.map((r) => (r.team.id === row.team.id ? { ...r, draft, dirty } : r)),
    );
  }

  protected save(row: Row): void {
    if (!row.dirty || row.saving) return;
    this.patch(row, { saving: true, error: null });
    this.api.updateTeam(row.team.id, row.draft).subscribe({
      next: (updated) => {
        this.rows.update((rows) =>
          rows.map((r) =>
            r.team.id === row.team.id
              ? {
                  team: updated,
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
      rows.map((r) => (r.team.id === row.team.id ? { ...r, ...patch } : r)),
    );
  }
}

function isDirty<T extends object>(a: T, b: T): boolean {
  return (Object.keys(a) as (keyof T)[]).some((k) => a[k] !== b[k]);
}
