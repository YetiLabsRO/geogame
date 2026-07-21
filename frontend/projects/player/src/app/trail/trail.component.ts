import { CommonModule } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { GameApiService, TrailState, TrailStepInfo } from 'shared';

/**
 * mode-trail-discovery: player trail screen (wireframe).
 *
 * Current clue card, branch chooser when the trail forks, progress
 * list over the party's revealed steps, and the finish state. Arrival
 * and gate unlock happen on the tower detail page, which rides the
 * existing submission flow.
 */
@Component({
  selector: 'app-trail',
  standalone: true,
  imports: [CommonModule, RouterLink],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="container py-3" style="max-width: 640px">
      <h1 class="h4 mb-3"><i class="bi bi-signpost-split me-2"></i>Trail</h1>

      @if (notTrail()) {
        <div class="alert alert-secondary">This session is not a trail run.</div>
      } @else if (state(); as s) {
        @if (s.finished) {
          <div class="alert alert-success">
            <i class="bi bi-flag-fill me-2"></i>
            <strong>Finished!</strong> Completed at {{ s.finished_at | date: 'HH:mm:ss' }}.
          </div>
        }

        @if (s.route === null) {
          <div class="alert alert-warning">No route has been assigned to your party yet.</div>
        } @else {
          @if (s.progress) {
            <div class="mb-3">
              <div class="d-flex justify-content-between small text-muted mb-1">
                <span>Progress</span>
                <span>{{ s.progress.unlocked }} / {{ s.progress.total }} points</span>
              </div>
              <div class="progress" style="height: 8px">
                <div
                  class="progress-bar bg-success"
                  [style.width.%]="(100 * s.progress.unlocked) / (s.progress.total || 1)"
                ></div>
              </div>
            </div>
          }

          @if (s.start_hint) {
            <div class="card border-info mb-3">
              <div class="card-body">
                <h2 class="h6 text-info"><i class="bi bi-eye-slash me-1"></i>Find the start</h2>
                <p class="mb-0">{{ s.start_hint }}</p>
              </div>
            </div>
          }

          @if (!s.finished && s.next_steps.length > 0) {
            <div class="card border-primary mb-3">
              <div class="card-body">
                <h2 class="h6 text-primary mb-2">
                  <i class="bi bi-compass me-1"></i>
                  @if (s.next_steps.length > 1) {
                    Choose your next point
                  } @else {
                    Your next clue
                  }
                </h2>
                @for (step of s.next_steps; track step.id) {
                  <div class="border rounded p-2 mb-2">
                    <div class="d-flex justify-content-between align-items-start">
                      <div>
                        <p class="mb-1">{{ step.clue || 'No clue — find the point!' }}</p>
                        <span class="badge text-bg-light border me-1">
                          @if (step.state) {
                            {{ step.state }}
                          } @else {
                            HIDDEN
                          }
                        </span>
                        @if (step.has_gate) {
                          <span class="badge text-bg-secondary">gate at the point</span>
                        } @else {
                          <span class="badge text-bg-info">arrive to unlock</span>
                        }
                      </div>
                      @if (step.state) {
                        <a class="btn btn-sm btn-outline-primary" [routerLink]="['/tower', step.tower.id]">
                          {{ step.tower.name }}
                        </a>
                      }
                    </div>
                  </div>
                }
              </div>
            </div>
          }

          <div class="card">
            <div class="card-header py-2 small text-muted">My revealed points</div>
            <ul class="list-group list-group-flush">
              @for (step of s.steps; track step.id) {
                <li class="list-group-item d-flex justify-content-between align-items-center">
                  <div>
                    <span class="fw-semibold me-2">{{ step.tower.name }}</span>
                    @if (step.is_start) {
                      <span class="badge text-bg-light border">start</span>
                    }
                    @if (step.is_finish) {
                      <span class="badge text-bg-light border">finish</span>
                    }
                    <div class="small text-muted">{{ step.clue }}</div>
                  </div>
                  <span class="badge" [class]="stateBadge(step)">{{ step.state }}</span>
                </li>
              } @empty {
                <li class="list-group-item text-muted small">Nothing revealed yet.</li>
              }
            </ul>
          </div>
        }
      } @else {
        <div class="text-muted">Loading trail…</div>
      }
    </div>
  `,
})
export class TrailComponent implements OnInit {
  private readonly api = inject(GameApiService);

  readonly state = signal<TrailState | null>(null);
  readonly notTrail = signal(false);

  ngOnInit(): void {
    this.api.trailState().subscribe({
      next: (state) => this.state.set(state),
      error: () => this.notTrail.set(true),
    });
  }

  stateBadge(step: TrailStepInfo): string {
    switch (step.state) {
      case 'UNLOCKED':
        return 'badge text-bg-success';
      case 'ARRIVED':
        return 'badge text-bg-warning';
      default:
        return 'badge text-bg-secondary';
    }
  }
}
