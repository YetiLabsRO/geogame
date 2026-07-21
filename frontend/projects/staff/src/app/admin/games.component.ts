import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators, FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';

import {
  AdminCollection,
  AdminGame,
  AdminGamePayload,
  FailCounterReset,
  StaffApiService,
  TeamJoinConfirmation,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';
import { GameRolesPanelComponent } from './game-roles-panel.component';
import { ScoreMultipliersPanelComponent } from './score-multipliers-panel.component';

type PauseKnob =
  | 'pause_freezes_floating_score'
  | 'pause_restores_ownerships_on_resume'
  | 'pause_rejects_submissions';

type TeamRuleKnob =
  | 'min_teams'
  | 'max_teams'
  | 'min_members_per_team'
  | 'max_members_per_team';

interface Row {
  game: AdminGame;
  draft: AdminGame;
  dirty: boolean;
  saving: boolean;
  error: string | null;
  pauseMsg: string | null;
}

@Component({
  selector: 'app-admin-games',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    ReactiveFormsModule,
    FormsModule,
    RouterLink,
    GameRolesPanelComponent,
    ScoreMultipliersPanelComponent,
  ],
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
                  <div class="mt-1">
                    @if (row.game.created_by_username; as creator) {
                      <span class="badge text-bg-light border me-1">
                        by {{ creator }}
                      </span>
                    }
                    @if (row.game.cloned_from !== null) {
                      <span class="badge text-bg-info">
                        clone of #{{ row.game.cloned_from }}
                      </span>
                    }
                  </div>
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
                  <div class="d-flex gap-2 justify-content-end">
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      (click)="toggleRules(row.game.id)"
                    >
                      Rules
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      (click)="toggleRoles(row.game.id)"
                    >
                      Roles
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      (click)="toggleMultipliers(row.game.id)"
                    >
                      Multipliers
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      (click)="clone(row)"
                    >
                      Clone game
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-warning"
                      (click)="pauseAll(row)"
                    >
                      Pause all sessions
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
                  @if (row.pauseMsg; as msg) {
                    <div class="small text-body-secondary mt-1">{{ msg }}</div>
                  }
                </td>
              </tr>
              @if (rolesExpanded().has(row.game.id)) {
                <tr class="table-light">
                  <td colspan="7">
                    <app-game-roles-panel [gameId]="row.game.id" />
                  </td>
                </tr>
              }
              @if (multipliersExpanded().has(row.game.id)) {
                <tr class="table-light">
                  <td colspan="7">
                    <app-score-multipliers-panel [gameId]="row.game.id" />
                  </td>
                </tr>
              }
              @if (expanded().has(row.game.id)) {
                <tr class="table-light">
                  <td colspan="7">
                    <div class="row g-3 py-2">
                      <div class="col-12">
                        <div class="fw-semibold small mb-2">Map collections</div>
                        @if (allCollections().length === 0) {
                          <div class="text-body-secondary small">
                            No collections in the repository yet — create one on
                            the Collections page.
                          </div>
                        }
                        @for (c of allCollections(); track c.id) {
                          <div class="form-check form-check-inline">
                            <input
                              type="checkbox"
                              class="form-check-input"
                              [id]="'col-' + c.id + '-' + row.game.id"
                              [checked]="row.draft.collections.includes(c.id)"
                              (change)="toggleCollection(row, c.id)"
                            />
                            <label
                              class="form-check-label small"
                              [for]="'col-' + c.id + '-' + row.game.id"
                            >
                              {{ c.name }}
                            </label>
                          </div>
                        }
                      </div>
                      <div class="col-md-6">
                        <div class="fw-semibold small mb-2">Day pausing</div>
                        @for (k of pauseKnobs; track k.field) {
                          <div class="form-check form-switch">
                            <input
                              type="checkbox"
                              class="form-check-input"
                              role="switch"
                              [id]="k.field + '-' + row.game.id"
                              [ngModel]="row.draft[k.field]"
                              (ngModelChange)="update(row, k.field, $event)"
                            />
                            <label class="form-check-label small" [for]="k.field + '-' + row.game.id">
                              {{ k.label }}
                            </label>
                          </div>
                        }
                      </div>
                      <div class="col-md-6">
                        <div class="fw-semibold small mb-2">Failure consequences</div>
                        <div class="row g-2">
                          <div class="col-6">
                            <label class="form-label small mb-0">Point penalty</label>
                            <input
                              class="form-control form-control-sm"
                              type="number"
                              min="0"
                              [ngModel]="row.draft.fail_point_penalty"
                              (ngModelChange)="update(row, 'fail_point_penalty', $event)"
                            />
                          </div>
                          <div class="col-6">
                            <label class="form-label small mb-0">Cooloff scaling (≥1)</label>
                            <input
                              class="form-control form-control-sm"
                              type="number"
                              min="1"
                              step="0.1"
                              [ngModel]="row.draft.fail_cooloff_scaling"
                              (ngModelChange)="update(row, 'fail_cooloff_scaling', $event)"
                            />
                          </div>
                          <div class="col-6">
                            <label class="form-label small mb-0">Tower lockout (min)</label>
                            <input
                              class="form-control form-control-sm"
                              type="number"
                              min="0"
                              [ngModel]="row.draft.fail_tower_lockout_minutes"
                              (ngModelChange)="update(row, 'fail_tower_lockout_minutes', $event)"
                            />
                          </div>
                          <div class="col-6 d-flex align-items-end">
                            <div class="form-check form-switch">
                              <input
                                type="checkbox"
                                class="form-check-input"
                                role="switch"
                                [id]="'rollback-' + row.game.id"
                                [ngModel]="row.draft.fail_difficulty_rollback"
                                (ngModelChange)="update(row, 'fail_difficulty_rollback', $event)"
                              />
                              <label class="form-check-label small" [for]="'rollback-' + row.game.id">
                                Difficulty rollback
                              </label>
                            </div>
                          </div>
                          <div class="col-12">
                            <label class="form-label small mb-0">Counter reset</label>
                            <select
                              class="form-select form-select-sm"
                              [ngModel]="row.draft.fail_counter_reset"
                              (ngModelChange)="update(row, 'fail_counter_reset', $event)"
                            >
                              @for (o of resetOptions; track o.value) {
                                <option [ngValue]="o.value">{{ o.label }}</option>
                              }
                            </select>
                          </div>
                        </div>
                      </div>
                      <div class="col-12">
                        <div class="fw-semibold small mb-2">Team rules</div>
                        <div class="row g-2">
                          @for (t of teamRuleKnobs; track t.field) {
                            <div class="col-6 col-lg-3">
                              <label class="form-label small mb-0">{{ t.label }}</label>
                              <input
                                class="form-control form-control-sm"
                                type="number"
                                [min]="t.min"
                                [ngModel]="row.draft[t.field]"
                                (ngModelChange)="update(row, t.field, $event)"
                              />
                            </div>
                          }
                          <div class="col-12 text-body-secondary small">
                            Maxima use 0 for &laquo;no cap&raquo;. A Session may only start
                            once enough teams meet the member minimum.
                          </div>
                        </div>
                      </div>
                      <div class="col-md-6">
                        <div class="fw-semibold small mb-2">Team formation</div>
                        <div class="form-check form-switch">
                          <input
                            type="checkbox"
                            class="form-check-input"
                            role="switch"
                            [id]="'ptc-' + row.game.id"
                            [ngModel]="row.draft.allow_player_team_creation"
                            (ngModelChange)="update(row, 'allow_player_team_creation', $event)"
                          />
                          <label class="form-check-label small" [for]="'ptc-' + row.game.id">
                            Players may create their own teams
                          </label>
                        </div>
                        <div class="mt-2">
                          <label class="form-label small mb-0">Join confirmation</label>
                          <select
                            class="form-select form-select-sm"
                            [ngModel]="row.draft.team_join_confirmation"
                            (ngModelChange)="update(row, 'team_join_confirmation', $event)"
                          >
                            @for (o of confirmationOptions; track o.value) {
                              <option [ngValue]="o.value">{{ o.label }}</option>
                            }
                          </select>
                          <div class="form-text">
                            Default for new joins; each team can override it.
                          </div>
                        </div>
                      </div>
                    </div>
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
export class GamesComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly api = inject(StaffApiService);

  protected readonly rows = signal<Row[]>([]);
  protected readonly allCollections = signal<AdminCollection[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);

  protected readonly expanded = signal<Set<number>>(new Set<number>());
  protected readonly rolesExpanded = signal<Set<number>>(new Set<number>());
  protected readonly multipliersExpanded = signal<Set<number>>(new Set<number>());

  protected readonly pauseKnobs: { field: PauseKnob; label: string }[] = [
    { field: 'pause_freezes_floating_score', label: 'Freeze floating score while paused' },
    { field: 'pause_restores_ownerships_on_resume', label: 'Restore ownerships on resume' },
    { field: 'pause_rejects_submissions', label: 'Reject submissions while paused' },
  ];

  protected readonly confirmationOptions: { value: TeamJoinConfirmation; label: string }[] = [
    { value: 'AUTO_APPROVE', label: 'Auto-approve joins' },
    { value: 'CAPTAIN', label: 'Captain approves joins' },
    { value: 'STAFF', label: 'Staff approve joins' },
  ];

  protected readonly resetOptions: { value: FailCounterReset; label: string }[] = [
    { value: 'TOWER_SUCCESS_ONLY', label: 'Reset only on success at the same tower' },
    { value: 'ANY_SUCCESS_ELSEWHERE', label: 'Reset on any confirmed submission' },
    { value: 'ANY_ATTEMPT_ELSEWHERE', label: 'Reset on any submission anywhere' },
  ];

  protected readonly teamRuleKnobs: { field: TeamRuleKnob; label: string; min: number }[] = [
    { field: 'min_teams', label: 'Min teams (≥1)', min: 1 },
    { field: 'max_teams', label: 'Max teams (0 = no cap)', min: 0 },
    { field: 'min_members_per_team', label: 'Min members/team (≥1)', min: 1 },
    { field: 'max_members_per_team', label: 'Max members/team (0 = no cap)', min: 0 },
  ];

  protected readonly createForm = this.fb.group({
    slug: ['', [Validators.required]],
    name: ['', [Validators.required]],
    base_lat: [null as number | null],
    base_lng: [null as number | null],
  });

  constructor() {
    this.refresh();
    this.api.listCollections().subscribe({
      next: (list) => this.allCollections.set(list),
      error: () => {},
    });
  }

  protected toggleCollection(row: Row, collectionId: number): void {
    const has = row.draft.collections.includes(collectionId);
    const next = has
      ? row.draft.collections.filter((id) => id !== collectionId)
      : [...row.draft.collections, collectionId];
    this.update(row, 'collections', next);
  }

  protected clone(row: Row): void {
    this.patch(row, { pauseMsg: 'Cloning…' });
    this.api.cloneGame(row.game.id).subscribe({
      next: (created) => {
        // Append the clone locally so the status message survives.
        this.rows.update((rows) => [
          ...rows,
          {
            game: created,
            draft: { ...created },
            dirty: false,
            saving: false,
            error: null,
            pauseMsg: null,
          },
        ]);
        this.patch(row, {
          pauseMsg: `Cloned as "${created.name}" (${created.slug}).`,
        });
      },
      error: (err) => this.patch(row, { pauseMsg: extractErrorMessage(err) }),
    });
  }

  protected toggleRules(id: number): void {
    this.expanded.update((set) => {
      const next = new Set(set);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  protected toggleRoles(id: number): void {
    this.rolesExpanded.update((set) => {
      const next = new Set(set);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  protected toggleMultipliers(id: number): void {
    this.multipliersExpanded.update((set) => {
      const next = new Set(set);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  protected pauseAll(row: Row): void {
    this.patch(row, { pauseMsg: 'Pausing…' });
    this.api.pauseAllSessions(row.game.id).subscribe({
      next: (res) => {
        const n = res.paused_sessions.length;
        this.patch(row, {
          pauseMsg: n
            ? `Paused ${n} active session${n === 1 ? '' : 's'}.`
            : 'No active sessions to pause.',
        });
      },
      error: (err) => this.patch(row, { pauseMsg: extractErrorMessage(err) }),
    });
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
            pauseMsg: null,
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
        collections: row.draft.collections,
        proximity_meters: row.draft.proximity_meters,
        cooloff_minutes: row.draft.cooloff_minutes,
        initial_bonus_default: row.draft.initial_bonus_default,
        pause_freezes_floating_score: row.draft.pause_freezes_floating_score,
        pause_restores_ownerships_on_resume: row.draft.pause_restores_ownerships_on_resume,
        pause_rejects_submissions: row.draft.pause_rejects_submissions,
        fail_point_penalty: row.draft.fail_point_penalty,
        fail_cooloff_scaling: row.draft.fail_cooloff_scaling,
        fail_tower_lockout_minutes: row.draft.fail_tower_lockout_minutes,
        fail_difficulty_rollback: row.draft.fail_difficulty_rollback,
        fail_counter_reset: row.draft.fail_counter_reset,
        min_teams: row.draft.min_teams,
        max_teams: row.draft.max_teams,
        min_members_per_team: row.draft.min_members_per_team,
        max_members_per_team: row.draft.max_members_per_team,
        allow_player_team_creation: row.draft.allow_player_team_creation,
        team_join_confirmation: row.draft.team_join_confirmation,
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
                    pauseMsg: null,
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
