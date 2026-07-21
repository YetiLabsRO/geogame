import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  inject,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { forkJoin } from 'rxjs';

import {
  GameApiService,
  REALTIME_EVENTS,
  RealtimeService,
  ScoreboardUpdatedPayload,
  SessionScoreboard,
  SessionTimeline,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/** How long an overtake highlight stays on a row. */
const HIGHLIGHT_MS = 4_000;
/** Poll interval used only while the realtime socket is down. */
const FALLBACK_POLL_MS = 30_000;

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
              @if (realtime.connected()) {
                <span class="text-success ms-2">
                  <i class="bi bi-broadcast"></i> Live
                </span>
              }
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
                  <tr [class.table-success]="movedUp().has(e.team_id)">
                    <td class="fw-semibold">
                      {{ i + 1 }}
                      @if (movedUp().has(e.team_id)) {
                        <i class="bi bi-arrow-up-short text-success"></i>
                      }
                    </td>
                    <td>
                      <span
                        class="d-inline-block me-2"
                        style="width: 0.9rem; height: 0.9rem; border-radius: 50%; vertical-align: middle"
                        [style.background-color]="e.team_color"
                      ></span>
                      <span class="fw-semibold">{{ e.team_name }}</span>
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
  private readonly destroyRef = inject(DestroyRef);
  protected readonly realtime = inject(RealtimeService);

  protected readonly scoreboard = signal<SessionScoreboard | null>(null);
  protected readonly timeline = signal<SessionTimeline | null>(null);
  protected readonly loadError = signal<string | null>(null);
  /** Team ids that just moved up a rank (overtake highlight). */
  protected readonly movedUp = signal<ReadonlySet<number>>(new Set());

  private readonly sessionId: number;
  private highlightHandle: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    this.sessionId = Number(this.route.snapshot.paramMap.get('id'));
    if (!this.sessionId) {
      this.loadError.set('Invalid session.');
      return;
    }
    this.load(true);

    // 4.4 — live scoreboard for the viewed session; the RealtimeService
    // ignores the call when realtime is disabled and the consumer only
    // admits members of the session, so this is safe to attempt.
    this.realtime
      .eventsOfType<ScoreboardUpdatedPayload>(REALTIME_EVENTS.scoreboardUpdated)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((envelope) => {
        if (envelope.session === this.sessionId) {
          this.applyScoreboard(envelope.payload);
        }
      });

    // 4.5 — polling fallback while the socket is down, active games only.
    const pollHandle = setInterval(() => {
      if (!this.realtime.connected() && this.scoreboard()?.session?.is_active) {
        this.load(false);
      }
    }, FALLBACK_POLL_MS);

    this.destroyRef.onDestroy(() => {
      clearInterval(pollHandle);
      if (this.highlightHandle) clearTimeout(this.highlightHandle);
      this.realtime.disconnect();
    });
  }

  private load(connectSocket: boolean): void {
    forkJoin({
      scoreboard: this.api.sessionScoreboard(this.sessionId),
      timeline: this.api.sessionTimeline(this.sessionId),
    }).subscribe({
      next: ({ scoreboard, timeline }) => {
        this.scoreboard.set(scoreboard);
        this.timeline.set(timeline);
        if (connectSocket && scoreboard.session.is_active) {
          this.realtime.connect(
            this.sessionId, scoreboard.session.realtime_enabled,
          );
        }
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  private applyScoreboard(payload: ScoreboardUpdatedPayload): void {
    const current = this.scoreboard();
    if (!current) return;
    const previous = new Map(
      current.entries.map((entry, index) => [entry.team_id, index]),
    );
    const moved = new Set<number>();
    payload.entries.forEach((entry, index) => {
      const before = previous.get(entry.team_id);
      if (before !== undefined && index < before) {
        moved.add(entry.team_id);
      }
    });
    this.scoreboard.set({ ...current, entries: payload.entries });
    if (moved.size > 0) {
      this.movedUp.set(moved);
      if (this.highlightHandle) clearTimeout(this.highlightHandle);
      this.highlightHandle = setTimeout(() => this.movedUp.set(new Set()), HIGHLIGHT_MS);
    }
  }
}
