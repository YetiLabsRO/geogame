import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';

import {
  AuthService,
  GameApiService,
  REALTIME_EVENTS,
  RealtimeService,
  ScoreboardUpdatedPayload,
  TeamSummary,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

const POLL_INTERVAL_MS = 30_000;
/** How long an overtake highlight stays on a row. */
const HIGHLIGHT_MS = 4_000;

interface GroupBucket {
  slug: string;
  name: string;
  teams: TeamSummary[];
}

const UNGROUPED_SLUG = '__ungrouped__';

@Component({
  selector: 'app-scoreboard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="d-flex justify-content-between align-items-center mb-3">
      <div>
        <h1 class="h3 mb-0">Live scoreboard</h1>
        <div class="small text-body-secondary">
          @if (realtime.connected()) {
            <span class="text-success"><i class="bi bi-broadcast"></i> Live</span>
            · updates in real time
          } @else {
            Refreshes every 30s
          }
          · last updated
          @if (lastUpdated(); as t) {
            {{ t }}
          } @else {
            —
          }
        </div>
      </div>
      <button
        type="button"
        class="btn btn-sm btn-outline-secondary"
        [disabled]="loading()"
        (click)="refresh()"
      >
        @if (loading()) {
          <span class="spinner-border spinner-border-sm me-1"></span>
        }
        Refresh now
      </button>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (buckets().length === 0 && !loading()) {
      <div class="alert alert-info">No teams yet.</div>
    } @else {
      <ul class="nav nav-pills mb-3">
        @for (b of buckets(); track b.slug) {
          <li class="nav-item">
            <button
              type="button"
              class="nav-link"
              [class.active]="activeSlug() === b.slug"
              (click)="setActive(b.slug)"
            >
              {{ b.name }}
              <span class="badge text-bg-light ms-1">{{ b.teams.length }}</span>
            </button>
          </li>
        }
      </ul>

      @if (activeBucket(); as bucket) {
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
              @for (t of bucket.teams; track t.id; let i = $index) {
                <tr [class.table-success]="movedUp().has(t.id)">
                  <td class="fw-semibold">
                    {{ i + 1 }}
                    @if (movedUp().has(t.id)) {
                      <i class="bi bi-arrow-up-short text-success"></i>
                    }
                  </td>
                  <td>
                    <span
                      class="d-inline-block me-2"
                      style="width: 0.9rem; height: 0.9rem; border-radius: 50%; vertical-align: middle"
                      [style.background-color]="t.color"
                    ></span>
                    <span class="fw-semibold">{{ t.name }}</span>
                  </td>
                  <td class="text-end fw-semibold">{{ t.current_score }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      }
    }
  `,
})
export class ScoreboardComponent {
  private readonly api = inject(GameApiService);
  private readonly auth = inject(AuthService);
  private readonly destroyRef = inject(DestroyRef);
  protected readonly realtime = inject(RealtimeService);

  protected readonly teams = signal<TeamSummary[]>([]);
  protected readonly activeSlug = signal<string | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly lastUpdated = signal<string | null>(null);
  /** Team ids that just moved up a rank (overtake highlight). */
  protected readonly movedUp = signal<ReadonlySet<number>>(new Set());

  protected readonly buckets = computed<GroupBucket[]>(() => {
    const byKey = new Map<string, GroupBucket>();
    for (const t of this.teams()) {
      const slug = t.group_slug ?? UNGROUPED_SLUG;
      const name = t.group_name ?? 'Ungrouped';
      let bucket = byKey.get(slug);
      if (!bucket) {
        bucket = { slug, name, teams: [] };
        byKey.set(slug, bucket);
      }
      bucket.teams.push(t);
    }
    const buckets = Array.from(byKey.values());
    for (const b of buckets) {
      b.teams.sort((a, b) => b.current_score - a.current_score || a.name.localeCompare(b.name));
    }
    buckets.sort((a, b) => a.name.localeCompare(b.name));
    return buckets;
  });

  protected readonly activeBucket = computed(() => {
    const slug = this.activeSlug();
    const list = this.buckets();
    return list.find((b) => b.slug === slug) ?? list[0] ?? null;
  });

  private pollHandle: ReturnType<typeof setInterval> | null = null;
  private highlightHandle: ReturnType<typeof setTimeout> | null = null;
  private seenConnections = 0;

  constructor() {
    this.refresh();
    this.connectRealtime();

    // Polling stays as the fallback: skip the periodic refresh while
    // the realtime socket is delivering updates (4.5).
    this.pollHandle = setInterval(() => {
      if (!this.realtime.connected()) {
        this.refresh();
      }
    }, POLL_INTERVAL_MS);

    // Reconcile with a fresh snapshot after every reconnect (4.2).
    effect(() => {
      const count = this.realtime.connections();
      if (count > this.seenConnections && this.seenConnections > 0) {
        this.refresh();
      }
      this.seenConnections = Math.max(this.seenConnections, count);
    });

    // Live totals (4.4).
    this.realtime
      .eventsOfType<ScoreboardUpdatedPayload>(REALTIME_EVENTS.scoreboardUpdated)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((envelope) => this.applyScoreboard(envelope.payload));

    this.destroyRef.onDestroy(() => {
      if (this.pollHandle) clearInterval(this.pollHandle);
      if (this.highlightHandle) clearTimeout(this.highlightHandle);
      this.realtime.disconnect();
    });
  }

  private connectRealtime(): void {
    const sessionId = this.auth.profile()?.current_session;
    if (sessionId) {
      this.realtime.connect(sessionId);
      return;
    }
    this.auth.fetchProfile().subscribe({
      next: (profile) => {
        if (profile.current_session) {
          this.realtime.connect(profile.current_session);
        }
      },
      error: () => {},
    });
  }

  private applyScoreboard(payload: ScoreboardUpdatedPayload): void {
    const current = this.teams();
    const known = new Set(current.map((t) => t.id));
    if (payload.entries.some((e) => !known.has(e.team_id))) {
      // A team we have never seen (roster changed) — full snapshot.
      this.refresh();
      return;
    }
    const previousRanks = this.rankByGroup(current);
    const scores = new Map(payload.entries.map((e) => [e.team_id, e.current_score]));
    const updated = current.map((t) =>
      scores.has(t.id) ? { ...t, current_score: scores.get(t.id)! } : t,
    );
    const newRanks = this.rankByGroup(updated);
    const moved = new Set<number>();
    for (const [id, rank] of newRanks) {
      const before = previousRanks.get(id);
      if (before !== undefined && rank < before) {
        moved.add(id);
      }
    }
    this.teams.set(updated);
    this.lastUpdated.set(new Date().toLocaleTimeString());
    if (moved.size > 0) {
      this.movedUp.set(moved);
      if (this.highlightHandle) clearTimeout(this.highlightHandle);
      this.highlightHandle = setTimeout(() => this.movedUp.set(new Set()), HIGHLIGHT_MS);
    }
  }

  /** Rank (0-based) of each team inside its group bucket. */
  private rankByGroup(teams: TeamSummary[]): Map<number, number> {
    const byGroup = new Map<string, TeamSummary[]>();
    for (const t of teams) {
      const slug = t.group_slug ?? UNGROUPED_SLUG;
      const list = byGroup.get(slug) ?? [];
      list.push(t);
      byGroup.set(slug, list);
    }
    const ranks = new Map<number, number>();
    for (const list of byGroup.values()) {
      const sorted = [...list].sort(
        (a, b) => b.current_score - a.current_score || a.name.localeCompare(b.name),
      );
      sorted.forEach((t, index) => ranks.set(t.id, index));
    }
    return ranks;
  }

  protected setActive(slug: string): void {
    this.activeSlug.set(slug);
  }

  protected refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.teams().subscribe({
      next: (list) => {
        this.teams.set(list);
        this.lastUpdated.set(new Date().toLocaleTimeString());
        this.loading.set(false);
        if (this.activeSlug() === null) {
          this.activeSlug.set(this.buckets()[0]?.slug ?? null);
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }
}
