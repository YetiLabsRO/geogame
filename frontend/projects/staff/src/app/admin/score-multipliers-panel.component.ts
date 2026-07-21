import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  inject,
  input,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin } from 'rxjs';

import {
  AdminScoreMultiplier,
  AdminTower,
  AdminZone,
  ScoreMultiplierScope,
  StaffApiService,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface MultiplierRow {
  multiplier: AdminScoreMultiplier;
  draft: { factor: number; label: string; is_active: boolean };
  dirty: boolean;
  saving: boolean;
  error: string | null;
}

/**
 * Schedule panel for a Game's template SCHEDULED multipliers
 * (score-multipliers capability, task 5.1). Embedded in an expanded
 * row on the Games page. Windows are Session-relative offsets so the
 * same arc replays on every run; the form warns (non-blocking) when a
 * new window overlaps an existing arc on the same target.
 */
@Component({
  selector: 'app-score-multipliers-panel',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <div class="fw-semibold small mb-2">Scheduled score multipliers</div>
    <p class="small text-body-secondary mb-2">
      Pre-scripted boosts that replay on every Session of this game:
      the window is relative to the Session start (e.g. &laquo;from minute
      60 to minute 120, double all points&raquo;). Factors compose
      multiplicatively with any live boosts dropped from the session
      console.
    </p>

    @if (loadError(); as msg) {
      <div class="alert alert-danger py-2">{{ msg }}</div>
    }

    @if (rows().length > 0) {
      <div class="table-responsive">
        <table class="table table-sm align-middle">
          <thead>
            <tr>
              <th>Scope</th>
              <th>Window (min from start)</th>
              <th style="max-width: 6rem">Factor</th>
              <th>Label</th>
              <th>Enabled</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (row of rows(); track row.multiplier.id) {
              <tr>
                <td class="small">{{ scopeLabel(row.multiplier) }}</td>
                <td class="small">
                  {{ windowLabel(row.multiplier) }}
                </td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="number"
                    min="0.1"
                    step="0.1"
                    [ngModel]="row.draft.factor"
                    (ngModelChange)="update(row, 'factor', $event)"
                  />
                </td>
                <td>
                  <input
                    class="form-control form-control-sm"
                    type="text"
                    placeholder="e.g. Happy hour"
                    [ngModel]="row.draft.label"
                    (ngModelChange)="update(row, 'label', $event)"
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
      <div class="small text-body-secondary mb-2">
        No scheduled multipliers yet — scoring runs at the normal 1&times;.
      </div>
    }

    <form class="row g-2 align-items-end" (ngSubmit)="create()">
      <div class="col-md-2">
        <label class="form-label small mb-0" [for]="'mult-scope-' + gameId()">Scope</label>
        <select
          [id]="'mult-scope-' + gameId()"
          class="form-select form-select-sm"
          [ngModel]="newScope()"
          (ngModelChange)="newScope.set($event)"
          name="scope"
        >
          <option ngValue="GLOBAL">Everywhere</option>
          <option ngValue="TOWER">One tower</option>
          <option ngValue="ZONE">One zone</option>
        </select>
      </div>
      @if (newScope() === 'TOWER') {
        <div class="col-md-2">
          <label class="form-label small mb-0" [for]="'mult-tower-' + gameId()">Tower</label>
          <select
            [id]="'mult-tower-' + gameId()"
            class="form-select form-select-sm"
            [ngModel]="newTower()"
            (ngModelChange)="newTower.set($event)"
            name="tower"
          >
            <option [ngValue]="null">—</option>
            @for (t of gameTowers(); track t.id) {
              <option [ngValue]="t.id">{{ t.name }}</option>
            }
          </select>
        </div>
      }
      @if (newScope() === 'ZONE') {
        <div class="col-md-2">
          <label class="form-label small mb-0" [for]="'mult-zone-' + gameId()">Zone</label>
          <select
            [id]="'mult-zone-' + gameId()"
            class="form-select form-select-sm"
            [ngModel]="newZone()"
            (ngModelChange)="newZone.set($event)"
            name="zone"
          >
            <option [ngValue]="null">—</option>
            @for (z of gameZones(); track z.id) {
              <option [ngValue]="z.id">{{ z.name }}</option>
            }
          </select>
        </div>
      }
      <div class="col-md-2">
        <label class="form-label small mb-0" [for]="'mult-factor-' + gameId()">
          Factor (&gt; 0)
        </label>
        <input
          [id]="'mult-factor-' + gameId()"
          class="form-control form-control-sm"
          type="number"
          min="0.1"
          step="0.1"
          [ngModel]="newFactor()"
          (ngModelChange)="newFactor.set($event)"
          name="factor"
          required
        />
      </div>
      <div class="col-md-2">
        <label class="form-label small mb-0" [for]="'mult-start-' + gameId()">
          From minute
        </label>
        <input
          [id]="'mult-start-' + gameId()"
          class="form-control form-control-sm"
          type="number"
          min="0"
          placeholder="start"
          [ngModel]="newStartMin()"
          (ngModelChange)="newStartMin.set($event)"
          name="start_min"
        />
      </div>
      <div class="col-md-2">
        <label class="form-label small mb-0" [for]="'mult-end-' + gameId()">
          To minute
        </label>
        <input
          [id]="'mult-end-' + gameId()"
          class="form-control form-control-sm"
          type="number"
          min="0"
          placeholder="open"
          [ngModel]="newEndMin()"
          (ngModelChange)="newEndMin.set($event)"
          name="end_min"
        />
      </div>
      <div class="col-md-2">
        <label class="form-label small mb-0" [for]="'mult-label-' + gameId()">Label</label>
        <input
          [id]="'mult-label-' + gameId()"
          class="form-control form-control-sm"
          type="text"
          placeholder="shown to players"
          [ngModel]="newLabel()"
          (ngModelChange)="newLabel.set($event)"
          name="label"
        />
      </div>
      <div class="col-auto">
        <button
          type="submit"
          class="btn btn-sm btn-primary"
          [disabled]="creating() || !canCreate()"
        >
          @if (creating()) {
            <span class="spinner-border spinner-border-sm me-1"></span>
          }
          Add scheduled multiplier
        </button>
      </div>
      @if (overlapWarning(); as msg) {
        <div class="col-12">
          <div class="alert alert-warning py-1 px-2 small mb-0">
            <i class="bi bi-exclamation-triangle me-1"></i>{{ msg }}
          </div>
        </div>
      }
      @if (createError(); as msg) {
        <div class="col-12"><div class="small text-danger">{{ msg }}</div></div>
      }
    </form>
  `,
})
export class ScoreMultipliersPanelComponent {
  private readonly api = inject(StaffApiService);

  readonly gameId = input.required<number>();

  protected readonly rows = signal<MultiplierRow[]>([]);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);

  private readonly towers = signal<AdminTower[]>([]);
  private readonly zones = signal<AdminZone[]>([]);

  protected readonly newScope = signal<ScoreMultiplierScope>('GLOBAL');
  protected readonly newTower = signal<number | null>(null);
  protected readonly newZone = signal<number | null>(null);
  protected readonly newFactor = signal<number | null>(2);
  protected readonly newStartMin = signal<number | null>(null);
  protected readonly newEndMin = signal<number | null>(null);
  protected readonly newLabel = signal('');

  /** Geometry usable by this game (repository assets referenced by it). */
  protected readonly gameTowers = computed(() =>
    this.towers().filter((t) => t.games.some((g) => g.id === this.gameId())),
  );
  protected readonly gameZones = computed(() =>
    this.zones().filter((z) => z.games.some((g) => g.id === this.gameId())),
  );

  protected readonly canCreate = computed(() => {
    const factor = this.newFactor();
    if (factor === null || factor <= 0) return false;
    if (this.newScope() === 'TOWER' && this.newTower() === null) return false;
    if (this.newScope() === 'ZONE' && this.newZone() === null) return false;
    return true;
  });

  /** Non-blocking overlap check against existing enabled arcs (task 5.1). */
  protected readonly overlapWarning = computed<string | null>(() => {
    if (!this.canCreate()) return null;
    const start = this.newStartMin();
    const end = this.newEndMin();
    const scope = this.newScope();
    const clashes = this.rows().filter((row) => {
      const m = row.multiplier;
      if (!m.is_active || m.multiplier_type !== 'SCHEDULED') return false;
      if (!scopesIntersect(scope, this.newTower(), this.newZone(), m)) return false;
      return windowsOverlap(
        start,
        end,
        durationToMinutes(m.window_start_offset),
        durationToMinutes(m.window_end_offset),
      );
    });
    if (clashes.length === 0) return null;
    const names = clashes
      .map((c) => c.multiplier.label || `#${c.multiplier.id}`)
      .join(', ');
    return (
      `Overlaps ${names} — factors stack multiplicatively while both windows ` +
      'are in effect.'
    );
  });

  constructor() {
    effect(() => {
      this.gameId();
      this.refresh();
    });
    forkJoin({
      towers: this.api.listTowers(),
      zones: this.api.listZones(),
    }).subscribe({
      next: ({ towers, zones }) => {
        this.towers.set(towers);
        this.zones.set(zones);
      },
      error: () => {},
    });
  }

  protected scopeLabel(m: AdminScoreMultiplier): string {
    if (m.scope === 'TOWER') return `Tower: ${m.tower_name ?? m.tower}`;
    if (m.scope === 'ZONE') return `Zone: ${m.zone_name ?? m.zone}`;
    return 'Everywhere';
  }

  protected windowLabel(m: AdminScoreMultiplier): string {
    const start = durationToMinutes(m.window_start_offset);
    const end = durationToMinutes(m.window_end_offset);
    if (start === null && end === null) return 'whole session';
    return `${start ?? 'start'} → ${end ?? 'open'}`;
  }

  private refresh(): void {
    this.loadError.set(null);
    this.api.listGameMultipliers(this.gameId()).subscribe({
      next: (list) =>
        this.rows.set(
          list.map((multiplier) => ({
            multiplier,
            draft: pickDraft(multiplier),
            dirty: false,
            saving: false,
            error: null,
          })),
        ),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected create(): void {
    if (this.creating() || !this.canCreate()) return;
    this.creating.set(true);
    this.createError.set(null);
    const scope = this.newScope();
    this.api
      .createGameMultiplier(this.gameId(), {
        scope,
        multiplier_type: 'SCHEDULED',
        factor: this.newFactor() ?? 1,
        tower: scope === 'TOWER' ? this.newTower() : null,
        zone: scope === 'ZONE' ? this.newZone() : null,
        window_start_offset: minutesToDuration(this.newStartMin()),
        window_end_offset: minutesToDuration(this.newEndMin()),
        label: this.newLabel(),
      })
      .subscribe({
        next: () => {
          this.creating.set(false);
          this.newLabel.set('');
          this.newStartMin.set(null);
          this.newEndMin.set(null);
          this.refresh();
        },
        error: (err) => {
          this.creating.set(false);
          this.createError.set(extractErrorMessage(err));
        },
      });
  }

  protected update<K extends keyof MultiplierRow['draft']>(
    row: MultiplierRow,
    field: K,
    value: MultiplierRow['draft'][K],
  ): void {
    const draft = { ...row.draft, [field]: value };
    const base = pickDraft(row.multiplier);
    const dirty = (Object.keys(draft) as (keyof MultiplierRow['draft'])[]).some(
      (k) => draft[k] !== base[k],
    );
    this.patch(row, { draft, dirty });
  }

  protected save(row: MultiplierRow): void {
    if (!row.dirty || row.saving) return;
    this.patch(row, { saving: true, error: null });
    this.api
      .updateGameMultiplier(this.gameId(), row.multiplier.id, {
        factor: row.draft.factor,
        label: row.draft.label,
        is_active: row.draft.is_active,
      })
      .subscribe({
        next: (updated) =>
          this.rows.update((rows) =>
            rows.map((r) =>
              r.multiplier.id === row.multiplier.id
                ? {
                    multiplier: updated,
                    draft: pickDraft(updated),
                    dirty: false,
                    saving: false,
                    error: null,
                  }
                : r,
            ),
          ),
        error: (err) => this.patch(row, { saving: false, error: extractErrorMessage(err) }),
      });
  }

  protected remove(row: MultiplierRow): void {
    if (row.saving) return;
    if (!confirm('Delete this scheduled multiplier?')) return;
    this.patch(row, { saving: true, error: null });
    this.api.deleteGameMultiplier(this.gameId(), row.multiplier.id).subscribe({
      next: () =>
        this.rows.update((rows) =>
          rows.filter((r) => r.multiplier.id !== row.multiplier.id),
        ),
      error: (err) => this.patch(row, { saving: false, error: extractErrorMessage(err) }),
    });
  }

  private patch(row: MultiplierRow, patch: Partial<MultiplierRow>): void {
    this.rows.update((rows) =>
      rows.map((r) => (r.multiplier.id === row.multiplier.id ? { ...r, ...patch } : r)),
    );
  }
}

function pickDraft(m: AdminScoreMultiplier): MultiplierRow['draft'] {
  return { factor: m.factor, label: m.label, is_active: m.is_active };
}

/** "90" minutes → Django duration "01:30:00"; null stays null (open bound). */
export function minutesToDuration(minutes: number | null): string | null {
  if (minutes === null || Number.isNaN(minutes)) return null;
  const total = Math.max(0, Math.round(minutes * 60));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${pad(h)}:${pad(m)}:${pad(s)}`;
}

/** Django duration ("HH:MM:SS" or "D HH:MM:SS") → whole minutes. */
export function durationToMinutes(value: string | null): number | null {
  if (!value) return null;
  const [days, time] = value.includes(' ') ? value.split(' ') : ['0', value];
  const [h, m, s] = time.split(':').map(Number);
  return Number(days) * 1440 + (h || 0) * 60 + (m || 0) + Math.round((s || 0) / 60);
}

function scopesIntersect(
  scope: ScoreMultiplierScope,
  towerId: number | null,
  zoneId: number | null,
  existing: AdminScoreMultiplier,
): boolean {
  if (scope === 'GLOBAL' || existing.scope === 'GLOBAL') return true;
  if (scope !== existing.scope) return false;
  if (scope === 'TOWER') return existing.tower === towerId;
  return existing.zone === zoneId;
}

/** Open bounds (null) extend the window infinitely on that side. */
function windowsOverlap(
  aStart: number | null,
  aEnd: number | null,
  bStart: number | null,
  bEnd: number | null,
): boolean {
  const startsBeforeBEnds = bEnd === null || aStart === null || aStart < bEnd;
  const bStartsBeforeAEnds = aEnd === null || bStart === null || bStart < aEnd;
  return startsBeforeBEnds && bStartsBeforeAEnds;
}
