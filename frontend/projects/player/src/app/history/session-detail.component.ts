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
  ActiveMultiplier,
  GameApiService,
  REALTIME_EVENTS,
  RealtimeService,
  ScoreboardUpdatedPayload,
  SessionScoreboard,
  SessionTimeline,
  UiAlertComponent,
  UiCardComponent,
  UiChipComponent,
  UiIconComponent,
  UiSpinnerComponent,
  UiStatTileComponent,
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
  imports: [
    DatePipe,
    RouterLink,
    UiAlertComponent,
    UiCardComponent,
    UiChipComponent,
    UiIconComponent,
    UiSpinnerComponent,
    UiStatTileComponent,
  ],
  template: `
    <div class="session-detail">
      <a routerLink="/history" class="tr-button-label session-detail__back">&larr; Back to Chronicle</a>

      @if (loadError(); as msg) {
        <ui-alert tone="danger">{{ msg }}</ui-alert>
      } @else if (scoreboard(); as sb) {
        <span class="tr-eyebrow session-detail__eyebrow">{{ sb.session.game.name }}</span>
        <h1 class="tr-h1 session-detail__title">{{ sb.session.name }}</h1>
        <div class="session-detail__meta">
          <span class="tr-meta-tiny session-detail__dates">
            {{ sb.session.start_time | date: 'medium' }} – {{ sb.session.end_time | date: 'medium' }}
          </span>
          <ui-chip [tone]="sb.session.is_active ? 'brand' : 'neutral'">
            {{ sb.session.is_active ? 'Active' : 'Past' }}
          </ui-chip>
          @if (sb.session.is_active && realtime.connected()) {
            <ui-chip tone="solid" icon="sparkle">Live</ui-chip>
          }
        </div>

        <div class="session-detail__stats">
          <ui-stat-tile icon="users" label="Teams" [value]="sb.entries.length" />
          <ui-stat-tile
            icon="star"
            label="Top score"
            [value]="sb.entries.length > 0 ? sb.entries[0].current_score : 0"
          />
          <ui-stat-tile icon="target" label="Captures" [value]="timeline() ? timeline()!.events.length : 0" />
        </div>

        @if (sb.active_multipliers.length > 0) {
          <div class="session-detail__boosts">
            @for (b of sb.active_multipliers; track b.id) {
              <ui-chip tone="brand" icon="sparkle">×{{ b.factor }} {{ boostTarget(b) }}</ui-chip>
            }
          </div>
        }

        <h2 class="tr-h3 session-detail__section">Standings</h2>
        <div class="session-detail__standings">
          @for (e of sb.entries; track e.team_id; let i = $index) {
            <div class="standings-row" [class.standings-row--highlight]="movedUp().has(e.team_id)">
              <ui-card class="standings-row__card">
                <div class="standings-row__content">
                  <span class="standings-row__rank tr-h3">{{ i + 1 }}</span>
                  <div class="standings-row__info">
                    <div class="standings-row__name-line">
                      <span class="standings-row__dot" [style.background]="e.team_color"></span>
                      <span class="tr-h3 standings-row__name">{{ e.team_name }}</span>
                      @if (movedUp().has(e.team_id)) {
                        <ui-icon name="arrow-right" [size]="16" class="standings-row__up" />
                      }
                    </div>
                    @if (e.group_name) {
                      <ui-chip tone="slate">{{ e.group_name }}</ui-chip>
                    }
                  </div>
                  <div class="standings-row__score">
                    <span class="tr-h3">{{ e.current_score }}</span>
                    <span class="tr-eyebrow">points</span>
                  </div>
                </div>
              </ui-card>
            </div>
          }
        </div>

        <ui-card eyebrow="Ownership" title="Latest log" class="session-detail__log">
          @if (timeline(); as tl) {
            @if (tl.events.length === 0) {
              <p class="tr-body">No tower captures recorded.</p>
            } @else {
              <div class="timeline-list">
                @for (ev of tl.events; track ev.id) {
                  <div class="timeline-list__item">
                    <span class="timeline-list__dot" [style.background]="ev.team_color"></span>
                    <div class="timeline-list__body">
                      <span class="tr-meta-tiny timeline-list__time">
                        {{ ev.timestamp_start | date: 'short' }}
                      </span>
                      <p class="tr-body-italic timeline-list__text">
                        {{ ev.team_name }} captured {{ ev.tower_name }}
                        @if (ev.timestamp_end; as ended) {
                          — released {{ ended | date: 'short' }}
                        } @else {
                          — still held
                        }
                      </p>
                    </div>
                  </div>
                }
              </div>
            }
          }
        </ui-card>
      } @else {
        <div class="session-detail__loading">
          <ui-spinner [size]="20" />
          <span class="tr-body">Loading session…</span>
        </div>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .session-detail {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
      padding: var(--spacing-xl) var(--spacing-xl) var(--spacing-2xl);
      max-width: 640px;
      margin: 0 auto;
    }
    .session-detail__back {
      align-self: flex-start;
      color: var(--color-brand-onSurface);
      text-decoration: none;
      margin-bottom: var(--spacing-xs);
    }
    .session-detail__eyebrow {
      color: var(--color-brand-onSurface);
    }
    .session-detail__title {
      color: var(--color-text-primary);
    }
    .session-detail__meta {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--spacing-xs);
      margin-bottom: var(--spacing-xs);
    }
    .session-detail__dates {
      color: var(--color-text-muted);
    }
    .session-detail__stats {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
      gap: var(--spacing-sm);
      margin-top: var(--spacing-xs);
    }
    .session-detail__boosts {
      display: flex;
      flex-wrap: wrap;
      gap: var(--spacing-xs);
    }
    .session-detail__section {
      margin-top: var(--spacing-sm);
      color: var(--color-text-primary);
    }
    .session-detail__standings {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .standings-row {
      border-radius: var(--radius-lg);
      transition: box-shadow 0.3s ease;
    }
    .standings-row--highlight {
      box-shadow: 0 0 0 2px var(--color-success);
    }
    .standings-row__content {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
    }
    .standings-row__rank {
      display: flex;
      flex-shrink: 0;
      align-items: center;
      justify-content: center;
      width: 40px;
      height: 40px;
      border-radius: var(--radius-md);
      background: var(--color-bg-inset);
      color: var(--color-text-primary);
    }
    .standings-row__info {
      display: flex;
      min-width: 0;
      flex: 1;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .standings-row__name-line {
      display: flex;
      align-items: center;
      gap: var(--spacing-2xs);
    }
    .standings-row__dot {
      flex-shrink: 0;
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }
    .standings-row__name {
      overflow: hidden;
      color: var(--color-text-primary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .standings-row__up {
      flex-shrink: 0;
      color: var(--color-success);
      transform: rotate(-90deg);
    }
    .standings-row__score {
      display: flex;
      flex-shrink: 0;
      flex-direction: column;
      align-items: flex-end;
      gap: 2px;
      color: var(--color-text-primary);
    }
    .session-detail__log {
      margin-top: var(--spacing-xs);
    }
    .timeline-list {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .timeline-list__item {
      display: flex;
      gap: var(--spacing-sm);
    }
    .timeline-list__dot {
      flex-shrink: 0;
      width: 8px;
      height: 8px;
      margin-top: 6px;
      border-radius: 50%;
    }
    .timeline-list__body {
      display: flex;
      min-width: 0;
      flex-direction: column;
      gap: 2px;
    }
    .timeline-list__time {
      color: var(--color-text-muted);
    }
    .timeline-list__text {
      color: var(--color-text-secondary);
    }
    .session-detail__loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      margin-top: var(--spacing-xl);
      color: var(--color-text-secondary);
    }
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

  protected boostTarget(b: ActiveMultiplier): string {
    if (b.label) return `— ${b.label}`;
    if (b.scope === 'TOWER') return `at ${b.tower_name}`;
    if (b.scope === 'ZONE') return `in ${b.zone_name}`;
    return 'everywhere';
  }

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
