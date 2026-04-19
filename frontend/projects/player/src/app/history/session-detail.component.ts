import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import {
  GameApiService,
  SessionScoreboard,
  SessionTimeline,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-session-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-9">
        <a routerLink="/history" class="small text-body-secondary">
          &larr; Back to my sessions
        </a>

        @if (loadError(); as msg) {
          <div class="alert alert-danger mt-3">{{ msg }}</div>
        } @else if (scoreboard(); as sb) {
          <h1 class="h3 mt-2 mb-1">{{ sb.session.name }}</h1>
          <div class="text-body-secondary small mb-3">
            {{ sb.session.game.name }} · <code>{{ sb.session.slug }}</code>
            @if (!sb.session.is_active) {
              <span class="badge text-bg-secondary ms-2">Past</span>
            } @else {
              <span class="badge text-bg-success ms-2">Active</span>
            }
          </div>

          <h2 class="h5 mt-4 mb-2">Scoreboard</h2>
          <div class="table-responsive">
            <table class="table">
              <thead>
                <tr>
                  <th style="width: 3rem">#</th>
                  <th>Team</th>
                  <th class="text-end">Score</th>
                </tr>
              </thead>
              <tbody>
                @for (e of sb.entries; track e.team_id; let i = $index) {
                  <tr>
                    <td class="fw-semibold">{{ i + 1 }}</td>
                    <td>
                      <span
                        class="d-inline-block me-2"
                        style="width: 0.9rem; height: 0.9rem; border-radius: 50%; vertical-align: middle"
                        [style.background-color]="e.team_color"
                      ></span>
                      <span class="fw-semibold">{{ e.team_name }}</span>
                      <span class="text-body-secondary small ms-2">
                        {{ e.team_code }}
                      </span>
                    </td>
                    <td class="text-end fw-semibold">{{ e.current_score }}</td>
                  </tr>
                }
              </tbody>
            </table>
          </div>

          <h2 class="h5 mt-4 mb-2">Ownership timeline</h2>
          @if (timeline(); as tl) {
            @if (tl.events.length === 0) {
              <div class="alert alert-info">No tower captures recorded.</div>
            } @else {
              <div class="table-responsive">
                <table class="table">
                  <thead>
                    <tr>
                      <th>Team</th>
                      <th>Tower</th>
                      <th>Captured</th>
                      <th>Released</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (ev of tl.events; track ev.id) {
                      <tr>
                        <td>
                          <span
                            class="d-inline-block me-2"
                            style="width: 0.8rem; height: 0.8rem; border-radius: 50%; vertical-align: middle"
                            [style.background-color]="ev.team_color"
                          ></span>
                          {{ ev.team_name }}
                        </td>
                        <td>{{ ev.tower_name }}</td>
                        <td class="small text-body-secondary">
                          {{ ev.timestamp_start | date: 'medium' }}
                        </td>
                        <td class="small text-body-secondary">
                          @if (ev.timestamp_end; as ended) {
                            {{ ended | date: 'medium' }}
                          } @else {
                            <em>still held</em>
                          }
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
          }
        } @else {
          <div class="d-flex align-items-center text-body-secondary mt-4">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading session…
          </div>
        }
      </div>
    </div>
  `,
})
export class SessionDetailComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(GameApiService);

  protected readonly scoreboard = signal<SessionScoreboard | null>(null);
  protected readonly timeline = signal<SessionTimeline | null>(null);
  protected readonly loadError = signal<string | null>(null);

  constructor() {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    if (!id) {
      this.loadError.set('Invalid session.');
      return;
    }
    forkJoin({
      scoreboard: this.api.sessionScoreboard(id),
      timeline: this.api.sessionTimeline(id),
    }).subscribe({
      next: ({ scoreboard, timeline }) => {
        this.scoreboard.set(scoreboard);
        this.timeline.set(timeline);
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }
}
