import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { ActivatedRoute, RouterLink } from '@angular/router';

import { DiscoveryMatrix, StaffApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/**
 * Team × tower discovery matrix (tower-visibility capability).
 *
 * Shows, for every non-always-visible tower of the session's game,
 * which teams have discovered it and how (proximity / zone entry /
 * zone coverage / staff), and lets staff reveal a tower to a team by
 * hand — e.g. to unblock a stuck team in the field.
 */
@Component({
  selector: 'app-discovery-matrix',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink],
  template: `
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h1 class="h3 mb-0">Discovery matrix</h1>
      <a class="btn btn-sm btn-outline-secondary" [routerLink]="['/sessions', sessionId]">
        &larr; Back to session
      </a>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }
    @if (actionError(); as msg) {
      <div class="alert alert-danger py-2">{{ msg }}</div>
    }

    @if (matrix(); as m) {
      @if (m.towers.length === 0) {
        <div class="alert alert-info">
          Every tower in this game is always visible — nothing to discover.
          Set a tower's discoverability to Hidden or Fog reveal to use
          discovery.
        </div>
      } @else {
        <div class="table-responsive">
          <table class="table table-bordered align-middle">
            <thead>
              <tr>
                <th>Tower</th>
                <th>Discoverability</th>
                @for (team of m.teams; track team.id) {
                  <th class="text-center">
                    <span
                      class="badge"
                      [style.background-color]="team.color"
                    >
                      {{ team.name }}
                    </span>
                  </th>
                }
              </tr>
            </thead>
            <tbody>
              @for (tower of m.towers; track tower.id) {
                <tr>
                  <td class="fw-semibold">{{ tower.name }}</td>
                  <td>
                    <span
                      class="badge"
                      [class.text-bg-dark]="tower.discoverability === 'HIDDEN'"
                      [class.text-bg-secondary]="tower.discoverability === 'FOG_REVEAL'"
                      [class.text-bg-light]="tower.discoverability === 'VISIBLE'"
                    >
                      {{ tower.discoverability }}
                    </span>
                  </td>
                  @for (team of m.teams; track team.id) {
                    <td class="text-center">
                      @if (cell(team.id, tower.id); as c) {
                        <span
                          class="badge text-bg-success"
                          [title]="'Discovered at ' + c.discovered_at"
                        >
                          <i class="bi bi-check-lg"></i>
                          {{ c.method }}
                        </span>
                      } @else {
                        <button
                          type="button"
                          class="btn btn-sm btn-outline-primary"
                          [disabled]="revealing()"
                          (click)="reveal(team.id, tower.id)"
                        >
                          Reveal
                        </button>
                      }
                    </td>
                  }
                </tr>
              }
            </tbody>
          </table>
        </div>
        <div class="text-body-secondary small">
          «Reveal» creates a STAFF discovery: the tower becomes visible to
          that team as if it had been discovered in the field. Discoveries
          are permanent for the run.
        </div>
      }
    } @else if (!loadError()) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    }
  `,
})
export class DiscoveryMatrixComponent {
  private readonly api = inject(StaffApiService);
  private readonly route = inject(ActivatedRoute);

  protected readonly sessionId = Number(this.route.snapshot.paramMap.get('id'));
  protected readonly matrix = signal<DiscoveryMatrix | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);
  protected readonly revealing = signal(false);

  private readonly cellIndex = computed(() => {
    const m = this.matrix();
    const index = new Map<string, DiscoveryMatrix['discoveries'][number]>();
    for (const c of m?.discoveries ?? []) {
      index.set(`${c.team_id}:${c.tower_id}`, c);
    }
    return index;
  });

  constructor() {
    this.refresh();
  }

  protected cell(teamId: number, towerId: number) {
    return this.cellIndex().get(`${teamId}:${towerId}`) ?? null;
  }

  protected reveal(teamId: number, towerId: number): void {
    if (this.revealing()) return;
    this.revealing.set(true);
    this.actionError.set(null);
    this.api.revealTowerToTeam(teamId, towerId).subscribe({
      next: () => {
        this.revealing.set(false);
        this.refresh();
      },
      error: (err) => {
        this.revealing.set(false);
        this.actionError.set(extractErrorMessage(err));
      },
    });
  }

  private refresh(): void {
    this.api.sessionDiscoveryMatrix(this.sessionId).subscribe({
      next: (m) => this.matrix.set(m),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }
}
