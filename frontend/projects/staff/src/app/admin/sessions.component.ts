import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import {
  FormBuilder,
  FormsModule,
  ReactiveFormsModule,
  Validators,
} from '@angular/forms';
import { RouterLink } from '@angular/router';

import { HttpErrorResponse } from '@angular/common/http';

import {
  AdminGame,
  AdminSession,
  AdminSessionPayload,
  AuthService,
  Blocker,
  DialogService,
  StaffApiService,
  StatusPillComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface Row {
  session: AdminSession;
  draft: AdminSession;
  dirty: boolean;
  saving: boolean;
  error: string | null;
  /**
   * Blockers returned by a refused 409 — the start gate when activating,
   * the deletion gate when deleting. Both send the same shape.
   */
  blockers: string[];
  /** True while this row's delete is in flight. */
  deleting: boolean;
}

interface GameGroup {
  game: AdminGame;
  rows: Row[];
}

@Component({
  selector: 'app-admin-sessions',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, FormsModule, DatePipe, RouterLink, StatusPillComponent],
  template: `
    <div class="d-flex justify-content-between align-items-center flex-wrap gap-2 mb-3">
      <h1 class="h3 mb-0">Sessions</h1>
      <div class="d-flex align-items-center gap-2 flex-wrap">
        <label class="visually-hidden" for="session-game-filter">Filter by game</label>
        <select
          id="session-game-filter"
          class="form-select form-select-sm w-auto"
          [ngModel]="gameFilter()"
          (ngModelChange)="setGameFilter($event)"
        >
          <option [ngValue]="null">All games</option>
          @for (g of games(); track g.id) {
            <option [ngValue]="g.id">{{ g.name }}</option>
          }
        </select>
      <ul class="nav nav-pills">
        @for (f of filters; track f.key) {
          <li class="nav-item">
            <button
              type="button"
              class="nav-link"
              [class.active]="activeFilter() === f.key"
              (click)="setFilter(f.key)"
            >
              {{ f.label }}
            </button>
          </li>
        }
      </ul>
      </div>
    </div>
    <p class="text-body-secondary small">
      A Session is one live run of a Game — its own roster and scoreboard.
      Multiple Sessions on the same Game run independently. New Sessions
      start in DRAFT; drive them through
      DRAFT → OPEN_FOR_PARTICIPANTS → RUNNING ⇄ PAUSED → FINISHED from the
      session page. Finishing closes every open ownership and keeps history.
    </p>

    <div class="card mb-4">
      <div class="card-body">
        <h2 class="h6 mb-3">Create session</h2>
        <form [formGroup]="createForm" (ngSubmit)="create()" novalidate>
          <div class="row g-2">
            <div class="col-md-3">
              <select class="form-select" formControlName="game">
                <option [ngValue]="null" disabled>Game…</option>
                @for (g of games(); track g.id) {
                  <option [ngValue]="g.id">{{ g.name }}</option>
                }
              </select>
            </div>
            <div class="col-md-2">
              <input
                class="form-control"
                type="text"
                placeholder="Slug"
                formControlName="slug"
              />
            </div>
            <div class="col-md-3">
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
                type="datetime-local"
                formControlName="start_time"
              />
            </div>
            <div class="col-md-2">
              <input
                class="form-control"
                type="datetime-local"
                formControlName="end_time"
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
            Create session
          </button>
        </form>
      </div>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading() && groups().length === 0) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (visibleRowCount() === 0) {
      <div class="alert alert-info">{{ emptyMessage() }}</div>
    } @else {
      @for (bucket of groups(); track bucket.game.id) {
        <div class="mb-4">
          <h2 class="h5 mb-2">
            {{ bucket.game.name }}
            <code class="text-body-secondary small ms-2">{{ bucket.game.slug }}</code>
          </h2>
          <div class="table-responsive">
              <table class="table align-middle">
                <thead>
                  <tr>
                    <th>Slug</th>
                    <th>Name</th>
                    <th>Start</th>
                    <th>End</th>
                    <th>State</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  @for (row of bucket.rows; track row.session.id) {
                    <tr>
                      <td><code>{{ row.session.slug }}</code></td>
                      <td>
                        <input
                          class="form-control form-control-sm"
                          type="text"
                          [ngModel]="row.draft.name"
                          (ngModelChange)="update(row, 'name', $event)"
                        />
                      </td>
                      <td class="small text-body-secondary">
                        {{ row.session.start_time | date: 'short' }}
                      </td>
                      <td class="small text-body-secondary">
                        {{ row.session.end_time | date: 'short' }}
                      </td>
                      <td class="text-center">
                        <app-status-pill [status]="row.session.state" />
                      </td>
                      <td class="text-end">
                        <div class="d-flex gap-2 justify-content-end">
                          <a
                            class="btn btn-sm btn-outline-secondary"
                            [routerLink]="['/sessions', row.session.id]"
                          >
                            View
                          </a>
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
                          @if (isSuperuser()) {
                            <button
                              type="button"
                              class="btn btn-sm btn-outline-danger"
                              [disabled]="row.deleting"
                              [attr.aria-label]="'Delete session ' + row.session.name"
                              (click)="remove(row)"
                            >
                              @if (row.deleting) {
                                <span class="spinner-border spinner-border-sm"></span>
                              } @else {
                                <i class="bi bi-trash"></i>
                              }
                            </button>
                          }
                        </div>
                        @if (row.error; as msg) {
                          <div class="small text-danger mt-1">{{ msg }}</div>
                        }
                        @if (row.blockers.length > 0) {
                          <ul class="small text-danger text-start mt-1 mb-0">
                            @for (b of row.blockers; track $index) {
                              <li>{{ b }}</li>
                            }
                          </ul>
                        }
                      </td>
                    </tr>
                  }
                </tbody>
              </table>
          </div>
        </div>
      }
    }
  `,
})
export class SessionsComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly api = inject(StaffApiService);
  private readonly auth = inject(AuthService);
  private readonly dialogs = inject(DialogService);

  /**
   * Deleting a session is superadmin-only. The control is absent for
   * everyone else rather than present-and-disabled — an action they can
   * never take is noise, and the server refuses it regardless.
   */
  protected readonly isSuperuser = this.auth.isSuperuser;

  protected readonly games = signal<AdminGame[]>([]);
  protected readonly sessions = signal<AdminSession[]>([]);
  protected readonly rows = signal<Row[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);

  protected readonly filters: { key: 'all' | 'active' | 'past'; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'active', label: 'Active' },
    { key: 'past', label: 'Past' },
  ];
  protected readonly activeFilter = signal<'all' | 'active' | 'past'>('all');
  /** Narrow to one game; null is every game, and the default. */
  protected readonly gameFilter = signal<number | null>(null);

  protected readonly groups = computed<GameGroup[]>(() => {
    const filter = this.activeFilter();
    const game = this.gameFilter();
    const byGame = new Map<number, Row[]>();
    for (const row of this.rows()) {
      if (filter === 'active' && !row.session.is_active) continue;
      if (filter === 'past' && row.session.is_active) continue;
      if (game !== null && row.session.game !== game) continue;
      const key = row.session.game;
      const bucket = byGame.get(key);
      if (bucket) {
        bucket.push(row);
      } else {
        byGame.set(key, [row]);
      }
    }
    // Only games the filters left something in — a narrowed list should not
    // make you scroll past a heading per game to reach the one you wanted.
    return this.games()
      .filter((g) => (byGame.get(g.id) ?? []).length > 0)
      .map((g) => ({
        game: g,
        rows: (byGame.get(g.id) ?? [])
          .slice()
          .sort((a, b) => a.session.start_time.localeCompare(b.session.start_time)),
      }));
  });

  protected readonly visibleRowCount = computed(() =>
    this.groups().reduce((total, bucket) => total + bucket.rows.length, 0),
  );

  /** Says what is filtered out, so an empty list is never a dead end. */
  protected readonly emptyMessage = computed(() => {
    if (this.rows().length === 0) return 'No sessions yet.';
    const applied: string[] = [];
    const game = this.games().find((g) => g.id === this.gameFilter());
    if (game) applied.push(`game "${game.name}"`);
    if (this.activeFilter() !== 'all') applied.push(`the ${this.activeFilter()} filter`);
    return applied.length === 0
      ? 'No sessions yet.'
      : `No sessions match ${applied.join(' and ')}.`;
  });

  protected readonly createForm = this.fb.group({
    game: [null as number | null, [Validators.required]],
    slug: ['', [Validators.required]],
    name: ['', [Validators.required]],
    start_time: ['', [Validators.required]],
    end_time: ['', [Validators.required]],
  });

  constructor() {
    this.refresh();
  }

  protected setFilter(filter: 'all' | 'active' | 'past'): void {
    this.activeFilter.set(filter);
  }

  protected setGameFilter(gameId: number | null): void {
    this.gameFilter.set(gameId);
  }

  private refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listGames().subscribe({
      next: (games) => this.games.set(games),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
    this.api.listSessions().subscribe({
      next: (sessions) => {
        this.sessions.set(sessions);
        this.rows.set(
          sessions.map((session) => ({
            session,
            draft: { ...session },
            dirty: false,
            saving: false,
            error: null,
            blockers: [],
            deleting: false,
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
    // New Sessions start in DRAFT; lifecycle actions on the session
    // page drive them to OPEN_FOR_PARTICIPANTS / RUNNING.
    const payload: AdminSessionPayload = {
      game: raw.game as number,
      slug: raw.slug,
      name: raw.name,
      start_time: new Date(raw.start_time).toISOString(),
      end_time: new Date(raw.end_time).toISOString(),
    };
    this.api.createSession(payload).subscribe({
      next: () => {
        this.creating.set(false);
        this.createForm.reset({
          game: null,
          slug: '',
          name: '',
          start_time: '',
          end_time: '',
        });
        this.refresh();
      },
      error: (err) => {
        this.creating.set(false);
        this.createError.set(extractErrorMessage(err));
      },
    });
  }

  protected update<K extends keyof AdminSession>(
    row: Row,
    field: K,
    value: AdminSession[K],
  ): void {
    const draft = { ...row.draft, [field]: value };
    const dirty = isDirty(draft, row.session);
    this.rows.update((rows) =>
      rows.map((r) =>
        r.session.id === row.session.id ? { ...r, draft, dirty } : r,
      ),
    );
  }

  protected save(row: Row): void {
    if (!row.dirty || row.saving) return;
    this.patch(row, { saving: true, error: null, blockers: [] });
    this.api
      .updateSession(row.session.id, {
        name: row.draft.name,
      })
      .subscribe({
        next: (updated) => {
          this.rows.update((rows) =>
            rows.map((r) =>
              r.session.id === row.session.id
                ? {
                    session: updated,
                    draft: { ...updated },
                    dirty: false,
                    saving: false,
                    error: null,
                    blockers: [],
                    deleting: false,
                  }
                : r,
            ),
          );
        },
        error: (err) => {
          this.patch(row, {
            saving: false,
            error: extractErrorMessage(err),
            blockers: extractBlockerMessages(err),
          });
        },
      });
  }

  /**
   * Delete this session, once its superadmin has said so in the app's own
   * dialog. The server refuses anything still live with a 409 whose
   * blockers name the action that would settle it; those land on the row
   * beside the control they were asked for, and the row stays put.
   */
  protected async remove(row: Row): Promise<void> {
    if (row.deleting) return;
    const ok = await this.dialogs.confirm({
      title: `Delete "${row.session.name}"?`,
      message:
        'Its teams, their memberships and everything this run recorded — ' +
        'ownerships, submissions, positions — go with it. The game and its ' +
        'map are untouched. This cannot be undone.',
      confirmLabel: 'Delete session',
      danger: true,
    });
    if (!ok) return;

    this.patch(row, { deleting: true, error: null, blockers: [] });
    this.api.deleteSession(row.session.id).subscribe({
      next: () => {
        this.rows.update((rows) => rows.filter((r) => r.session.id !== row.session.id));
        // A switcher pointing at a session that no longer exists is worse
        // than one pointing at nothing.
        if (this.auth.profile()?.current_session === row.session.id) {
          this.auth.fetchProfile().subscribe({ error: () => undefined });
        }
      },
      error: (err) => {
        this.patch(row, {
          deleting: false,
          error: extractErrorMessage(err),
          blockers: extractBlockerMessages(err),
        });
      },
    });
  }

  private patch(row: Row, patch: Partial<Row>): void {
    this.rows.update((rows) =>
      rows.map((r) => (r.session.id === row.session.id ? { ...r, ...patch } : r)),
    );
  }
}


function isDirty<T extends object>(a: T, b: T): boolean {
  return (Object.keys(a) as (keyof T)[]).some((k) => a[k] !== b[k]);
}

/**
 * Pull the `blockers` messages out of a 409 body, if any. Both refusals
 * that carry blockers — the start gate and the deletion gate — send the
 * same shape, so one reader serves both.
 */
function extractBlockerMessages(err: unknown): string[] {
  if (!(err instanceof HttpErrorResponse)) return [];
  const blockers = (err.error as { blockers?: Blocker[] } | null)?.blockers;
  if (!Array.isArray(blockers)) return [];
  return blockers
    .map((b) => b.message)
    .filter((m): m is string => typeof m === 'string');
}
