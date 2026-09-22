import { DatePipe } from '@angular/common';
import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import {
  GameApiService,
  TrailState,
  TrailStepInfo,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiChipTone,
  UiEmptyStateComponent,
  UiIconComponent,
  UiProgressMeterComponent,
  UiSpinnerComponent,
} from 'shared';

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
  imports: [
    DatePipe,
    RouterLink,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiChipComponent,
    UiEmptyStateComponent,
    UiIconComponent,
    UiProgressMeterComponent,
    UiSpinnerComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="trail-screen">
      <header class="trail-header">
        <span class="tr-eyebrow">MODE · TRAIL</span>
        <h1 class="tr-h1">Trail</h1>
      </header>

      @if (notTrail()) {
        <ui-alert tone="info" [withIcon]="true">This session is not a trail run.</ui-alert>
      } @else if (state(); as s) {
        @if (s.finished) {
          <ui-alert tone="success" [withIcon]="true">
            <strong>Finished!</strong> Completed at {{ s.finished_at | date: 'HH:mm:ss' }}.
          </ui-alert>
        }

        @if (s.route === null) {
          <ui-alert tone="warning" [withIcon]="true">
            No route has been assigned to your party yet.
          </ui-alert>
        } @else {
          @if (s.progress; as progress) {
            <ui-progress-meter
              label="Progress"
              [valueLabel]="progress.unlocked + ' / ' + progress.total + ' points'"
              [value]="progress.unlocked"
              [max]="progress.total || 1"
              tone="success"
            />
          }

          @if (s.start_hint) {
            <ui-card eyebrow="Find the start">
              <p class="tr-body">{{ s.start_hint }}</p>
            </ui-card>
          }

          @if (!s.finished && s.next_steps.length > 0) {
            <section class="trail-section">
              <h2 class="tr-h3">
                @if (s.next_steps.length > 1) {
                  Choose your next point
                } @else {
                  Your next clue
                }
              </h2>
              @for (step of s.next_steps; track step.id) {
                <ui-card class="trail-step-panel">
                  <div class="trail-step-panel__row">
                    <span class="trail-step-panel__icon"><ui-icon name="compass" [size]="20" /></span>
                    <div class="trail-step-panel__body">
                      <p class="tr-body">{{ step.clue || 'No clue — find the point!' }}</p>
                      <div class="trail-step-panel__chips">
                        <ui-chip tone="neutral">{{ step.state || 'HIDDEN' }}</ui-chip>
                        @if (step.has_gate) {
                          <ui-chip tone="slate">gate at the point</ui-chip>
                        } @else {
                          <ui-chip tone="brand">arrive to unlock</ui-chip>
                        }
                      </div>
                    </div>
                  </div>
                  @if (step.state) {
                    <ui-button
                      variant="primary"
                      size="sm"
                      icon="arrow-right"
                      [routerLink]="['/tower', step.tower.id]"
                    >
                      {{ step.tower.name }}
                    </ui-button>
                  }
                </ui-card>
              }
            </section>
          }

          <section class="trail-section">
            <h2 class="tr-h3">My revealed points</h2>
            @if (s.steps.length > 0) {
              <div class="trail-list">
                @for (step of s.steps; track step.id) {
                  <div class="trail-list-row">
                    <div class="trail-list-row__main">
                      <div class="trail-list-row__title">
                        <span class="tr-body">{{ step.tower.name }}</span>
                        @if (step.is_start) {
                          <ui-chip tone="slate">start</ui-chip>
                        }
                        @if (step.is_finish) {
                          <ui-chip tone="slate">finish</ui-chip>
                        }
                      </div>
                      <span class="tr-meta-tiny trail-list-row__clue">{{ step.clue }}</span>
                    </div>
                    <ui-chip [tone]="stateTone(step)">{{ step.state }}</ui-chip>
                  </div>
                }
              </div>
            } @else {
              <ui-empty-state
                icon="compass"
                title="Nothing revealed yet"
                description="Keep exploring to reveal your first point."
              />
            }
          </section>
        }
      } @else {
        <div class="trail-loading">
          <ui-spinner />
          <span class="tr-body">Loading trail…</span>
        </div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .trail-screen {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-xl);
    }
    .trail-header {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .trail-header .tr-eyebrow {
      color: var(--color-brand-onSurface);
    }
    .trail-loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      color: var(--color-text-secondary);
    }
    .trail-section {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .trail-step-panel {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .trail-step-panel__row {
      display: flex;
      gap: var(--spacing-sm);
    }
    .trail-step-panel__icon {
      display: flex;
      flex-shrink: 0;
      align-items: center;
      justify-content: center;
      width: 40px;
      height: 40px;
      border-radius: var(--radius-md);
      background: var(--color-brand-tint);
      color: var(--color-brand-onSurface);
    }
    .trail-step-panel__body {
      display: flex;
      min-width: 0;
      flex: 1;
      flex-direction: column;
      gap: var(--spacing-xs);
    }
    .trail-step-panel__chips {
      display: flex;
      flex-wrap: wrap;
      gap: var(--spacing-2xs);
    }
    .trail-list {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-xs);
    }
    .trail-list-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
      padding: var(--spacing-sm) var(--spacing-md);
      border-radius: var(--radius-lg);
      background: var(--color-bg-raised);
      border: 1px solid var(--color-border-subtle);
    }
    .trail-list-row__main {
      display: flex;
      min-width: 0;
      flex-direction: column;
      gap: 2px;
    }
    .trail-list-row__title {
      display: flex;
      align-items: center;
      gap: var(--spacing-2xs);
    }
    .trail-list-row__clue {
      color: var(--color-text-muted);
    }
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

  stateTone(step: TrailStepInfo): UiChipTone {
    switch (step.state) {
      case 'UNLOCKED':
        return 'brand';
      case 'ARRIVED':
        return 'slate';
      default:
        return 'neutral';
    }
  }
}
