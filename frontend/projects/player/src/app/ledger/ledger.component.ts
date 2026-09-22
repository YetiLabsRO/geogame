import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Router, RouterLink } from '@angular/router';

import {
  AuthService,
  CurrentSession,
  DementorMe,
  DementorsService,
  GameApiService,
  MyTeam,
  PlatformService,
  REALTIME_EVENTS,
  RealtimeService,
  ScoreboardUpdatedPayload,
  SessionScoreboardEntry,
  ThemePreference,
  ThemeService,
  ToastService,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiEmptyStateComponent,
  UiFieldComponent,
  UiIconComponent,
  UiIconName,
  UiInputDirective,
  UiSpinnerComponent,
  UiStatTileComponent,
} from 'shared';

import { environment } from '../../environments/environment';
import { extractErrorMessage } from '../auth/form-error';

interface StandingsGroup {
  key: string;
  name: string | null;
  rows: (SessionScoreboardEntry & { rank: number })[];
}

interface LedgerMenuRow {
  label: string;
  route: string;
  icon: UiIconName;
}

const MENU_ROWS: LedgerMenuRow[] = [
  { label: 'Trail', route: '/trail', icon: 'compass' },
  { label: 'Rules', route: '/rules', icon: 'book' },
  { label: 'Notifications', route: '/settings', icon: 'bell' },
  { label: 'Location consent', route: '/location-consent', icon: 'target' },
];

const THEME_PREFERENCES: ThemePreference[] = ['system', 'light', 'dark'];

/**
 * Ledger screen (mobile-app task 4.3, D9): my team's score, the live
 * per-TeamGroup scoreboard, Dementors status, quick links and app
 * preferences (theme, dev-only API origin override), and sign out.
 */
@Component({
  selector: 'app-ledger',
  standalone: true,
  imports: [
    RouterLink,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiChipComponent,
    UiEmptyStateComponent,
    UiFieldComponent,
    UiIconComponent,
    UiInputDirective,
    UiSpinnerComponent,
    UiStatTileComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="tr-ledger-header">
      <span class="tr-eyebrow">PERSONAL LEDGER</span>
      <h1 class="tr-h1">Ledger</h1>
    </header>

    @if (loadError(); as msg) {
      <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
    }

    @if (loading()) {
      <div class="tr-ledger-loading">
        <ui-spinner /> <span class="tr-body">Loading your ledger…</span>
      </div>
    } @else {
      <!-- My team -->
      @if (myTeam(); as team) {
        <ui-card>
          <div class="tr-my-team">
            <div class="tr-my-team__header">
              <span class="tr-h2">{{ team.name }}</span>
              @if (myTeamGroupName(); as groupName) {
                <ui-chip [teamColor]="team.color">{{ groupName }}</ui-chip>
              }
            </div>
            <div class="tr-my-team__stats">
              @if (myTeamEntry(); as entry) {
                <ui-stat-tile icon="star" label="Locked" [value]="entry.locked_score" />
                <ui-stat-tile icon="sparkle" label="Floating" [value]="entry.floating_score" />
              } @else {
                <ui-stat-tile icon="star" label="Score" [value]="team.current_score" />
              }
            </div>
          </div>
        </ui-card>
      } @else {
        <ui-empty-state
          icon="users"
          title="No team yet"
          description="Join or create a team from Society to start playing."
        />
      }

      <!-- Standings -->
      <section class="tr-ledger-section">
        <h2 class="tr-h3">Standings</h2>
        @if (standingsGroups().length > 0) {
          @for (group of standingsGroups(); track group.key) {
            @if (group.name) {
              <div class="tr-standings-group tr-eyebrow">{{ group.name }}</div>
            }
            <div class="tr-standings-list">
              @for (row of group.rows; track row.team_id) {
                <div
                  class="tr-rank-row"
                  [class.tr-rank-row--mine]="row.team_id === myTeam()?.id"
                  [style.--team-color]="row.team_color"
                >
                  <span class="tr-rank-row__rank tr-h3">{{ formatRank(row.rank) }}</span>
                  <div class="tr-rank-row__body">
                    <span class="tr-rank-row__name tr-h3">{{ row.team_name }}</span>
                    @if (row.group_name && !group.name) {
                      <ui-chip tone="slate">{{ row.group_name }}</ui-chip>
                    }
                  </div>
                  <span class="tr-rank-row__points tr-h3">{{ row.current_score }}</span>
                </div>
              }
            </div>
          }
        } @else {
          <ui-empty-state
            icon="id-card"
            title="No standings yet"
            description="Scores will appear once teams start capturing towers."
          />
        }
      </section>

      <!-- Dementors -->
      <a class="tr-menu-row" routerLink="/dementors">
        <span class="tr-menu-row__icon"><ui-icon name="key" [size]="20" /></span>
        <span class="tr-menu-row__label tr-h3">Dementors</span>
        @if (dementorMe(); as me) {
          <ui-chip [tone]="me.role === 'DEMENTOR' ? 'brand' : 'slate'">{{ me.role }}</ui-chip>
        }
        <ui-icon class="tr-menu-row__chevron" name="arrow-right" [size]="18" />
      </a>

      <!-- Quick links -->
      <nav class="tr-ledger-menu">
        @for (row of menuRows; track row.route) {
          <a class="tr-menu-row" [routerLink]="row.route">
            <span class="tr-menu-row__icon"><ui-icon [name]="row.icon" [size]="20" /></span>
            <span class="tr-menu-row__label tr-h3">{{ row.label }}</span>
            <ui-icon class="tr-menu-row__chevron" name="arrow-right" [size]="18" />
          </a>
        }
      </nav>

      <!-- Preferences -->
      <ui-card eyebrow="Preferences" title="App settings">
        <div class="tr-pref-block">
          <span class="tr-field-label-text tr-field-label">THEME</span>
          <div class="tr-theme-row" role="group" aria-label="Theme">
            @for (pref of themePreferences; track pref) {
              <button
                type="button"
                class="tr-theme-toggle"
                [attr.aria-pressed]="theme.preference() === pref"
                (click)="theme.set(pref)"
              >
                <ui-chip [tone]="theme.preference() === pref ? 'solid' : 'neutral'">
                  {{ themeLabel(pref) }}
                </ui-chip>
              </button>
            }
          </div>
        </div>

        @if (!isProduction) {
          <div class="tr-pref-block">
            <ui-field label="API server" help="Debug-only override for this device.">
              <input
                uiInput
                type="text"
                [value]="apiBaseDraft()"
                (input)="onApiBaseInput($event)"
                placeholder="http://10.0.2.2:8200"
                autocomplete="off"
              />
            </ui-field>
            <div class="tr-pref-actions">
              <ui-button variant="secondary" size="sm" (pressed)="saveApiBase()">Save</ui-button>
              <ui-button variant="tinted" size="sm" (pressed)="clearApiBase()">Clear</ui-button>
            </div>
          </div>
        }
      </ui-card>

      <ui-button variant="secondary" [block]="true" (pressed)="signOut()">Sign out</ui-button>

      <p class="tr-footer tr-meta-tiny">
        Tower Rush
        @if (!isProduction) {
          · dev build
        }
      </p>
    }
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-xl);
    }
    .tr-ledger-header {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .tr-eyebrow {
      color: var(--color-brand-onSurface);
    }
    .tr-ledger-loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      color: var(--color-text-secondary);
    }
    .tr-my-team {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
    }
    .tr-my-team__header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--spacing-sm);
    }
    .tr-my-team__stats {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--spacing-sm);
    }
    .tr-ledger-section {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .tr-standings-group {
      color: var(--color-text-muted);
    }
    .tr-standings-list {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-xs);
    }
    .tr-rank-row {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      padding: var(--spacing-sm) var(--spacing-md);
      border-radius: var(--radius-lg);
      background: var(--color-bg-raised);
      border: 1px solid var(--color-border-subtle);
    }
    .tr-rank-row--mine {
      border-left: 3px solid var(--team-color, var(--color-brand-primary));
    }
    .tr-rank-row__rank {
      display: flex;
      flex-shrink: 0;
      align-items: center;
      justify-content: center;
      width: 32px;
      height: 32px;
      border-radius: var(--radius-md);
      background: var(--color-bg-inset);
      color: var(--color-text-secondary);
    }
    .tr-rank-row__body {
      display: flex;
      min-width: 0;
      flex: 1;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--spacing-xs);
    }
    .tr-rank-row__name {
      overflow: hidden;
      color: var(--color-text-primary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .tr-rank-row__points {
      flex-shrink: 0;
      color: var(--color-text-primary);
    }
    .tr-ledger-menu {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-xs);
    }
    .tr-menu-row {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      min-height: var(--tap-min);
      padding: var(--spacing-xs) 0;
      color: inherit;
      text-decoration: none;
    }
    .tr-menu-row__icon {
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
    .tr-menu-row__label {
      flex: 1;
      color: var(--color-text-primary);
    }
    .tr-menu-row__chevron {
      flex-shrink: 0;
      color: var(--color-text-muted);
    }
    .tr-pref-block {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-xs);
    }
    .tr-pref-block + .tr-pref-block {
      margin-top: var(--spacing-md);
    }
    .tr-theme-row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--spacing-xs);
    }
    .tr-theme-toggle {
      display: inline-flex;
      min-height: var(--tap-min);
      align-items: center;
      padding: 0 var(--spacing-2xs);
      border: none;
      background: transparent;
      cursor: pointer;
    }
    .tr-pref-actions {
      display: flex;
      gap: var(--spacing-sm);
    }
    .tr-footer {
      color: var(--color-text-muted);
      text-align: center;
    }
  `,
})
export class LedgerComponent implements OnInit {
  private readonly auth = inject(AuthService);
  private readonly gameApi = inject(GameApiService);
  private readonly dementorsApi = inject(DementorsService);
  private readonly realtime = inject(RealtimeService);
  private readonly router = inject(Router);
  private readonly destroyRef = inject(DestroyRef);
  private readonly toast = inject(ToastService);

  protected readonly platform = inject(PlatformService);
  protected readonly theme = inject(ThemeService);

  protected readonly isProduction = environment.production;
  protected readonly themePreferences = THEME_PREFERENCES;
  protected readonly menuRows = MENU_ROWS;

  protected readonly loading = signal(true);
  protected readonly loadError = signal<string | null>(null);

  private readonly session = signal<CurrentSession | null>(null);
  protected readonly myTeam = signal<MyTeam | null>(null);
  protected readonly scoreboard = signal<SessionScoreboardEntry[]>([]);
  protected readonly dementorMe = signal<DementorMe | null>(null);

  protected readonly apiBaseDraft = signal(this.platform.apiBaseUrl());

  protected readonly myTeamEntry = computed(() => {
    const team = this.myTeam();
    if (!team) return null;
    return this.scoreboard().find((entry) => entry.team_id === team.id) ?? null;
  });
  protected readonly myTeamGroupName = computed(() => this.myTeamEntry()?.group_name ?? null);

  protected readonly standingsGroups = computed<StandingsGroup[]>(() => {
    const byGroup = new Map<string, SessionScoreboardEntry[]>();
    for (const entry of this.scoreboard()) {
      const key = entry.group_slug ?? '__ungrouped__';
      const rows = byGroup.get(key);
      if (rows) {
        rows.push(entry);
      } else {
        byGroup.set(key, [entry]);
      }
    }
    return Array.from(byGroup.entries()).map(([key, rows]) => {
      const sorted = [...rows].sort((a, b) => b.current_score - a.current_score);
      return {
        key,
        // A single ungrouped scoreboard doesn't need its own repeated label.
        name: byGroup.size > 1 ? (sorted[0]?.group_name ?? null) : null,
        rows: sorted.map((row, index) => ({ ...row, rank: index + 1 })),
      };
    });
  });

  ngOnInit(): void {
    this.gameApi.currentSession().subscribe({
      next: (session) => {
        this.session.set(session);
        this.loadScoreboard(session.id);
        if (session.dementors_enabled) {
          this.dementorsApi.me().subscribe({
            next: (me) => this.dementorMe.set(me),
            error: () => {}, // not (yet) a dementors participant — row stays plain
          });
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });

    this.gameApi.myTeam().subscribe({
      next: (team) => this.myTeam.set(team),
      error: () => {}, // no team yet — the empty state covers it
    });

    // Live standings: apply scoreboard.updated events as they arrive; the
    // initial REST fetch above remains the source of truth until then.
    this.realtime
      .eventsOfType<ScoreboardUpdatedPayload>(REALTIME_EVENTS.scoreboardUpdated)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe((envelope) => {
        if (envelope.session === this.session()?.id) {
          this.scoreboard.set(envelope.payload.entries);
        }
      });
  }

  private loadScoreboard(sessionId: number): void {
    this.gameApi.sessionScoreboard(sessionId).subscribe({
      next: (board) => {
        this.scoreboard.set(board.entries);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected formatRank(rank: number): string {
    return String(rank).padStart(2, '0');
  }

  protected themeLabel(pref: ThemePreference): string {
    return pref.charAt(0).toUpperCase() + pref.slice(1);
  }

  protected onApiBaseInput(event: Event): void {
    this.apiBaseDraft.set((event.target as HTMLInputElement).value);
  }

  protected saveApiBase(): void {
    const value = this.apiBaseDraft().trim();
    void this.platform.setApiBaseUrlOverride(value || null).then(() => {
      this.toast.show('API origin updated.', { tone: 'brand' });
    });
  }

  protected clearApiBase(): void {
    this.apiBaseDraft.set('');
    void this.platform.setApiBaseUrlOverride(null).then(() => {
      this.toast.show('API origin override cleared.', { tone: 'neutral' });
    });
  }

  protected signOut(): void {
    this.auth.logout().subscribe({
      next: () => this.router.navigateByUrl('/login'),
      error: () => this.router.navigateByUrl('/login'),
    });
  }
}
