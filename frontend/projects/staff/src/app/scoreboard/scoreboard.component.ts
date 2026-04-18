import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  inject,
  signal,
} from '@angular/core';

import { GameApiService, TeamSummary } from 'shared';

import { extractErrorMessage } from '../auth/form-error';

const POLL_INTERVAL_MS = 30_000;

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
          Refreshes every 30s · last updated
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
                <tr>
                  <td class="fw-semibold">{{ i + 1 }}</td>
                  <td>
                    <span
                      class="d-inline-block me-2"
                      style="width: 0.9rem; height: 0.9rem; border-radius: 50%; vertical-align: middle"
                      [style.background-color]="t.color"
                    ></span>
                    <span class="fw-semibold">{{ t.name }}</span>
                    <span class="text-body-secondary small ms-2">{{ t.code }}</span>
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
  private readonly destroyRef = inject(DestroyRef);

  protected readonly teams = signal<TeamSummary[]>([]);
  protected readonly activeSlug = signal<string | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly lastUpdated = signal<string | null>(null);

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

  constructor() {
    this.refresh();
    this.pollHandle = setInterval(() => this.refresh(), POLL_INTERVAL_MS);
    this.destroyRef.onDestroy(() => {
      if (this.pollHandle) clearInterval(this.pollHandle);
    });
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
