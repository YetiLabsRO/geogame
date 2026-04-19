import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';

import {
  AdminSession,
  AuthService,
  CurrentSession,
  GameApiService,
  StaffApiService,
} from 'shared';

interface GameBucket {
  game_name: string;
  game_slug: string;
  sessions: AdminSession[];
}

@Component({
  selector: 'app-session-switcher',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="dropdown">
      <button
        type="button"
        class="btn btn-sm btn-outline-secondary dropdown-toggle"
        data-bs-toggle="dropdown"
        aria-expanded="false"
        (click)="loadSessions()"
      >
        @if (current(); as c) {
          <span class="small text-body-secondary me-1">{{ c.game.name }}</span>
          <span>{{ c.name }}</span>
        } @else {
          Pick a session
        }
      </button>
      <ul class="dropdown-menu dropdown-menu-end" style="min-width: 22rem">
        @if (loadError(); as msg) {
          <li><span class="dropdown-item-text text-danger small">{{ msg }}</span></li>
        } @else if (loading()) {
          <li>
            <span class="dropdown-item-text small text-body-secondary">
              Loading…
            </span>
          </li>
        } @else if (buckets().length === 0) {
          <li>
            <span class="dropdown-item-text small text-body-secondary">
              No sessions available.
            </span>
          </li>
        } @else {
          @for (bucket of buckets(); track bucket.game_slug) {
            <li>
              <h6 class="dropdown-header">{{ bucket.game_name }}</h6>
            </li>
            @for (s of bucket.sessions; track s.id) {
              <li>
                <button
                  type="button"
                  class="dropdown-item d-flex justify-content-between align-items-center"
                  [disabled]="switchingId() === s.id"
                  (click)="pick(s)"
                >
                  <span>
                    {{ s.name }}
                    <code class="small text-body-secondary ms-1">{{ s.slug }}</code>
                  </span>
                  @if (currentId() === s.id) {
                    <span class="badge text-bg-primary ms-2">current</span>
                  } @else if (switchingId() === s.id) {
                    <span class="spinner-border spinner-border-sm"></span>
                  }
                </button>
              </li>
            }
          }
        }
      </ul>
    </div>
  `,
})
export class SessionSwitcherComponent {
  private readonly staffApi = inject(StaffApiService);
  private readonly gameApi = inject(GameApiService);
  private readonly auth = inject(AuthService);

  protected readonly current = signal<CurrentSession | null>(null);
  protected readonly sessions = signal<AdminSession[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly switchingId = signal<number | null>(null);

  protected readonly currentId = computed(() => this.current()?.id ?? null);

  protected readonly buckets = computed<GameBucket[]>(() => {
    const byGame = new Map<string, GameBucket>();
    for (const s of this.sessions()) {
      let b = byGame.get(s.game_slug);
      if (!b) {
        b = {
          game_slug: s.game_slug,
          game_name: s.game_name,
          sessions: [],
        };
        byGame.set(s.game_slug, b);
      }
      b.sessions.push(s);
    }
    return Array.from(byGame.values())
      .sort((a, b) => a.game_name.localeCompare(b.game_name))
      .map((b) => ({
        ...b,
        sessions: b.sessions.slice().sort((a, b) =>
          a.name.localeCompare(b.name),
        ),
      }));
  });

  constructor() {
    this.refreshCurrent();
  }

  private refreshCurrent(): void {
    this.gameApi.currentSession().subscribe({
      next: (c) => this.current.set(c),
      error: () => this.current.set(null),
    });
  }

  protected loadSessions(): void {
    if (this.loading()) return;
    this.loading.set(true);
    this.loadError.set(null);
    this.staffApi.listSessions().subscribe({
      next: (list) => {
        this.sessions.set(list);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set('Could not load sessions.');
      },
    });
  }

  protected pick(session: AdminSession): void {
    if (this.switchingId() !== null) return;
    if (this.currentId() === session.id) return;
    this.switchingId.set(session.id);
    this.gameApi.setCurrentSession(session.id).subscribe({
      next: (c) => {
        this.current.set(c);
        this.switchingId.set(null);
        // Pull the profile again so downstream views re-scope correctly.
        this.auth.fetchProfile().subscribe({ error: () => {} });
      },
      error: () => {
        this.switchingId.set(null);
      },
    });
  }
}
