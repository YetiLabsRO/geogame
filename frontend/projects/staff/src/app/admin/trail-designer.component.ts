import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

interface TrailRow {
  id: number;
  game: number;
  structure: string;
  starting_knowledge: string;
  participation: string;
  step_count: number;
  issues: { code: string; message: string }[];
}

interface StepRow {
  id: number;
  trail: number;
  tower: number;
  tower_name: string;
  order: number;
  is_start: boolean;
  is_finish: boolean;
  gate_challenge: number | null;
  clue_text: string;
  start_hint: string;
}

interface EdgeRow {
  id: number;
  trail: number;
  from_step: number;
  to_step: number;
  clue: string;
}

interface RouteRow {
  id: number;
  team: number | null;
  player: number | null;
  party: string;
  start_step: number;
  step_ids: number[];
  finished_at: string | null;
}

interface RankRow {
  rank: number;
  party: string;
  steps_unlocked: number;
  finished: boolean;
  finished_at: string | null;
}

/**
 * mode-trail-discovery: staff trail designer (table-based wireframe).
 *
 * Trail list + config, step table, edge table, per-session route
 * assignment with auto-generate, and the session trail leaderboard.
 * No graph canvas — tables only, per the wireframe scope.
 */
@Component({
  selector: 'app-trail-designer',
  standalone: true,
  imports: [CommonModule, FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="container-fluid py-3">
      <h1 class="h4 mb-3"><i class="bi bi-signpost-split me-2"></i>Trail designer</h1>

      <div class="row g-3">
        <div class="col-lg-4">
          <div class="card mb-3">
            <div class="card-header py-2">Trails</div>
            <ul class="list-group list-group-flush">
              @for (trail of trails(); track trail.id) {
                <li
                  class="list-group-item d-flex justify-content-between align-items-center"
                  [class.active]="trail.id === selected()?.id"
                  role="button"
                  (click)="select(trail)"
                >
                  <span>
                    #{{ trail.id }} · game {{ trail.game }} · {{ trail.structure }}
                    <span class="badge text-bg-light border ms-1">{{ trail.step_count }} steps</span>
                  </span>
                  @if (trail.issues.length > 0) {
                    <span class="badge text-bg-warning">{{ trail.issues.length }} issues</span>
                  }
                </li>
              } @empty {
                <li class="list-group-item text-muted small">No trails yet.</li>
              }
            </ul>
            <div class="card-body border-top">
              <div class="row g-2 align-items-end">
                <div class="col-4">
                  <label class="form-label small mb-0">Game id</label>
                  <input class="form-control form-control-sm" type="number" [(ngModel)]="newGameId" />
                </div>
                <div class="col-5">
                  <label class="form-label small mb-0">Structure</label>
                  <select class="form-select form-select-sm" [(ngModel)]="newStructure">
                    <option value="FIXED_ORDER">FIXED_ORDER</option>
                    <option value="GRAPH">GRAPH</option>
                    <option value="CIRCUIT">CIRCUIT</option>
                  </select>
                </div>
                <div class="col-3">
                  <button class="btn btn-sm btn-primary w-100" (click)="createTrail()">Add</button>
                </div>
              </div>
            </div>
          </div>

          @if (selected(); as trail) {
            <div class="card mb-3">
              <div class="card-header py-2">Trail #{{ trail.id }} config</div>
              <div class="card-body">
                <div class="mb-2">
                  <label class="form-label small mb-0">Starting knowledge</label>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="trail.starting_knowledge"
                    (ngModelChange)="patchTrail(trail, { starting_knowledge: $event })"
                  >
                    <option value="ALL_KNOWN">ALL_KNOWN</option>
                    <option value="ONE_KNOWN">ONE_KNOWN</option>
                    <option value="NONE_KNOWN">NONE_KNOWN</option>
                  </select>
                </div>
                <div class="mb-2">
                  <label class="form-label small mb-0">Participation</label>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="trail.participation"
                    (ngModelChange)="patchTrail(trail, { participation: $event })"
                  >
                    <option value="TEAM">TEAM</option>
                    <option value="SOLO">SOLO</option>
                  </select>
                </div>
                @for (issue of trail.issues; track issue.message) {
                  <div class="alert alert-warning py-1 px-2 small mb-1">{{ issue.message }}</div>
                }
              </div>
            </div>
          }
        </div>

        <div class="col-lg-8">
          @if (selected(); as trail) {
            <div class="card mb-3">
              <div class="card-header py-2">Steps</div>
              <div class="table-responsive">
                <table class="table table-sm align-middle mb-0">
                  <thead>
                    <tr>
                      <th>#</th><th>Order</th><th>Tower</th><th>Start</th><th>Finish</th>
                      <th>Gate challenge</th><th>Clue</th><th></th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (step of steps(); track step.id) {
                      <tr>
                        <td>{{ step.id }}</td>
                        <td>{{ step.order }}</td>
                        <td>{{ step.tower_name }}</td>
                        <td>@if (step.is_start) { <i class="bi bi-check-lg text-success"></i> }</td>
                        <td>@if (step.is_finish) { <i class="bi bi-check-lg text-success"></i> }</td>
                        <td>{{ step.gate_challenge ?? '— read-only —' }}</td>
                        <td class="small">{{ step.clue_text }}</td>
                        <td>
                          <button class="btn btn-sm btn-outline-danger" (click)="deleteStep(step)">
                            <i class="bi bi-trash"></i>
                          </button>
                        </td>
                      </tr>
                    } @empty {
                      <tr><td colspan="8" class="text-muted small">No steps yet.</td></tr>
                    }
                    <tr class="table-light">
                      <td>new</td>
                      <td><input class="form-control form-control-sm" style="width:4rem" type="number" [(ngModel)]="newStep.order" /></td>
                      <td><input class="form-control form-control-sm" style="width:6rem" type="number" placeholder="tower id" [(ngModel)]="newStep.tower" /></td>
                      <td><input class="form-check-input" type="checkbox" [(ngModel)]="newStep.is_start" /></td>
                      <td><input class="form-check-input" type="checkbox" [(ngModel)]="newStep.is_finish" /></td>
                      <td><input class="form-control form-control-sm" style="width:6rem" type="number" placeholder="opt." [(ngModel)]="newStep.gate_challenge" /></td>
                      <td><input class="form-control form-control-sm" [(ngModel)]="newStep.clue_text" placeholder="clue text" /></td>
                      <td><button class="btn btn-sm btn-primary" (click)="addStep()">Add</button></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div class="card mb-3">
              <div class="card-header py-2">Edges (GRAPH branches)</div>
              <div class="table-responsive">
                <table class="table table-sm align-middle mb-0">
                  <thead>
                    <tr><th>#</th><th>From step</th><th>To step</th><th>Clue</th><th></th></tr>
                  </thead>
                  <tbody>
                    @for (edge of edges(); track edge.id) {
                      <tr>
                        <td>{{ edge.id }}</td>
                        <td>{{ edge.from_step }}</td>
                        <td>{{ edge.to_step }}</td>
                        <td class="small">{{ edge.clue }}</td>
                        <td>
                          <button class="btn btn-sm btn-outline-danger" (click)="deleteEdge(edge)">
                            <i class="bi bi-trash"></i>
                          </button>
                        </td>
                      </tr>
                    } @empty {
                      <tr><td colspan="5" class="text-muted small">No edges (linear structures derive order).</td></tr>
                    }
                    <tr class="table-light">
                      <td>new</td>
                      <td><input class="form-control form-control-sm" style="width:6rem" type="number" [(ngModel)]="newEdge.from_step" /></td>
                      <td><input class="form-control form-control-sm" style="width:6rem" type="number" [(ngModel)]="newEdge.to_step" /></td>
                      <td><input class="form-control form-control-sm" [(ngModel)]="newEdge.clue" placeholder="branch clue" /></td>
                      <td><button class="btn btn-sm btn-primary" (click)="addEdge()">Add</button></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>

            <div class="card mb-3">
              <div class="card-header py-2 d-flex justify-content-between align-items-center">
                <span>Per-team routes</span>
                <span class="d-flex gap-2 align-items-center">
                  <input
                    class="form-control form-control-sm"
                    style="width: 8rem"
                    type="number"
                    placeholder="session id"
                    [(ngModel)]="sessionId"
                  />
                  <button class="btn btn-sm btn-outline-secondary" (click)="loadRoutes()">Load</button>
                  <button class="btn btn-sm btn-primary" (click)="autoGenerate()">Auto-generate</button>
                </span>
              </div>
              <div class="table-responsive">
                <table class="table table-sm align-middle mb-0">
                  <thead>
                    <tr><th>Party</th><th>Start step</th><th>Sequence</th><th>Finished</th><th></th></tr>
                  </thead>
                  <tbody>
                    @for (route of routes(); track route.id) {
                      <tr>
                        <td>{{ route.party }}</td>
                        <td>{{ route.start_step }}</td>
                        <td class="small">{{ route.step_ids.length ? route.step_ids.join(' → ') : 'derived from structure' }}</td>
                        <td>{{ route.finished_at ? (route.finished_at | date: 'HH:mm:ss') : '—' }}</td>
                        <td>
                          @if (route.team !== null) {
                            <button class="btn btn-sm btn-outline-secondary" (click)="revealStart(route)">
                              Reveal start
                            </button>
                          }
                        </td>
                      </tr>
                    } @empty {
                      <tr><td colspan="5" class="text-muted small">No routes loaded.</td></tr>
                    }
                  </tbody>
                </table>
              </div>
            </div>

            <div class="card">
              <div class="card-header py-2">Trail leaderboard</div>
              <div class="table-responsive">
                <table class="table table-sm mb-0">
                  <thead>
                    <tr><th>#</th><th>Party</th><th>Steps unlocked</th><th>Finished at</th></tr>
                  </thead>
                  <tbody>
                    @for (row of ranking(); track row.rank) {
                      <tr>
                        <td>{{ row.rank }}</td>
                        <td>{{ row.party }}</td>
                        <td>{{ row.steps_unlocked }}</td>
                        <td>{{ row.finished ? (row.finished_at | date: 'HH:mm:ss') : 'in progress' }}</td>
                      </tr>
                    } @empty {
                      <tr><td colspan="4" class="text-muted small">Load a session above.</td></tr>
                    }
                  </tbody>
                </table>
              </div>
            </div>
          } @else {
            <div class="alert alert-secondary">Select or create a trail on the left.</div>
          }
        </div>
      </div>
    </div>
  `,
})
export class TrailDesignerComponent implements OnInit {
  private readonly http = inject(HttpClient);

  readonly trails = signal<TrailRow[]>([]);
  readonly selected = signal<TrailRow | null>(null);
  readonly steps = signal<StepRow[]>([]);
  readonly edges = signal<EdgeRow[]>([]);
  readonly routes = signal<RouteRow[]>([]);
  readonly ranking = signal<RankRow[]>([]);

  newGameId: number | null = null;
  newStructure = 'FIXED_ORDER';
  sessionId: number | null = null;
  newStep: { order: number; tower: number | null; is_start: boolean; is_finish: boolean; gate_challenge: number | null; clue_text: string } =
    { order: 1, tower: null, is_start: false, is_finish: false, gate_challenge: null, clue_text: '' };
  newEdge: { from_step: number | null; to_step: number | null; clue: string } =
    { from_step: null, to_step: null, clue: '' };

  ngOnInit(): void {
    this.loadTrails();
  }

  loadTrails(): void {
    this.http.get<TrailRow[]>('/api/staff/trails/').subscribe((rows) => {
      this.trails.set(rows);
      const current = this.selected();
      if (current) {
        this.selected.set(rows.find((t) => t.id === current.id) ?? null);
      }
    });
  }

  select(trail: TrailRow): void {
    this.selected.set(trail);
    this.http
      .get<StepRow[]>(`/api/staff/trail-steps/?trail=${trail.id}`)
      .subscribe((rows) => this.steps.set(rows));
    this.http
      .get<EdgeRow[]>(`/api/staff/trail-edges/?trail=${trail.id}`)
      .subscribe((rows) => this.edges.set(rows));
  }

  createTrail(): void {
    if (!this.newGameId) return;
    this.http
      .post<TrailRow>('/api/staff/trails/', {
        game: this.newGameId,
        structure: this.newStructure,
        starting_knowledge: 'ONE_KNOWN',
        participation: 'TEAM',
      })
      .subscribe(() => this.loadTrails());
  }

  patchTrail(trail: TrailRow, patch: Partial<TrailRow>): void {
    this.http
      .patch<TrailRow>(`/api/staff/trails/${trail.id}/`, patch)
      .subscribe(() => this.loadTrails());
  }

  addStep(): void {
    const trail = this.selected();
    if (!trail || !this.newStep.tower) return;
    this.http
      .post<StepRow>('/api/staff/trail-steps/', { trail: trail.id, ...this.newStep })
      .subscribe(() => {
        this.newStep = { order: this.newStep.order + 1, tower: null, is_start: false, is_finish: false, gate_challenge: null, clue_text: '' };
        this.select(trail);
        this.loadTrails();
      });
  }

  deleteStep(step: StepRow): void {
    const trail = this.selected();
    this.http.delete(`/api/staff/trail-steps/${step.id}/`).subscribe(() => {
      if (trail) this.select(trail);
      this.loadTrails();
    });
  }

  addEdge(): void {
    const trail = this.selected();
    if (!trail || !this.newEdge.from_step || !this.newEdge.to_step) return;
    this.http
      .post<EdgeRow>('/api/staff/trail-edges/', { trail: trail.id, ...this.newEdge })
      .subscribe(() => {
        this.newEdge = { from_step: null, to_step: null, clue: '' };
        this.select(trail);
      });
  }

  deleteEdge(edge: EdgeRow): void {
    const trail = this.selected();
    this.http.delete(`/api/staff/trail-edges/${edge.id}/`).subscribe(() => {
      if (trail) this.select(trail);
    });
  }

  loadRoutes(): void {
    if (!this.sessionId) return;
    this.http
      .get<{ routes: RouteRow[] }>(`/api/staff/sessions/${this.sessionId}/trail-routes/`)
      .subscribe((data) => this.routes.set(data.routes));
    this.http
      .get<{ ranking: RankRow[] }>(`/api/staff/sessions/${this.sessionId}/trail-leaderboard/`)
      .subscribe((data) => this.ranking.set(data.ranking));
  }

  autoGenerate(): void {
    if (!this.sessionId) return;
    this.http
      .post<{ routes: RouteRow[] }>(`/api/staff/sessions/${this.sessionId}/trail-routes/auto-generate/`, {})
      .subscribe((data) => this.routes.set(data.routes));
  }

  revealStart(route: RouteRow): void {
    if (!this.sessionId) return;
    this.http
      .post(`/api/staff/sessions/${this.sessionId}/trail-reveal-start/`, { team: route.team })
      .subscribe();
  }
}
