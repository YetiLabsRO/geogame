import { Location } from '@angular/common';
import { ChangeDetectionStrategy, Component, computed, effect, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { NavigationEnd, Router, RouterLink, RouterOutlet } from '@angular/router';
import { filter, map } from 'rxjs';

import {
  AuthService,
  CurrentSession,
  GameApiService,
  UiAvatarComponent,
  UiBottomNavComponent,
  UiIconComponent,
  UiNavItem,
  UiToastOutletComponent,
  UiTopAppBarComponent,
} from 'shared';

/**
 * Auth / onboarding routes (mobile-app D9): no shell chrome at all, mirroring
 * the login screenshot. Matched by prefix against the path only (no query/hash).
 */
const CHROMELESS_PREFIXES = [
  '/login',
  '/register',
  '/reset',
  '/invite/',
  '/pick-session',
  '/location-consent',
  '/join/',
];

/** Bottom-nav tab roots — the shell back button lands here absent in-app history. */
const TAB_ROOTS = ['/', '/team', '/history', '/ledger'];

@Component({
  selector: 'app-root',
  imports: [
    RouterOutlet,
    RouterLink,
    UiTopAppBarComponent,
    UiBottomNavComponent,
    UiIconComponent,
    UiAvatarComponent,
    UiToastOutletComponent,
  ],
  templateUrl: './app.html',
  styleUrl: './app.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  private readonly auth = inject(AuthService);
  private readonly api = inject(GameApiService);
  private readonly router = inject(Router);
  private readonly location = inject(Location);

  protected readonly isAuthenticated = this.auth.isAuthenticated;
  protected readonly username = computed(() => this.auth.profile()?.username ?? undefined);

  private readonly session = signal<CurrentSession | null>(null);
  private sessionRequested = false;

  /** Session/Game name once known, else the app name (task 4.2). */
  protected readonly sessionTitle = computed(
    () => this.session()?.name || this.session()?.game?.name || 'Tower Rush',
  );

  private readonly currentUrl = toSignal(
    this.router.events.pipe(
      filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects.split(/[?#]/)[0]),
    ),
    { initialValue: this.router.url.split(/[?#]/)[0] },
  );

  /** Count of completed navigations, to tell "no in-app history yet" from "there is". */
  private navigations = 0;

  protected readonly isChromeless = computed(() =>
    CHROMELESS_PREFIXES.some((prefix) => this.currentUrl().startsWith(prefix)),
  );
  protected readonly showNav = computed(() => this.isAuthenticated() && !this.isChromeless());
  protected readonly isTabRoot = computed(() => TAB_ROOTS.includes(this.currentUrl()));
  protected readonly isMapRoute = computed(
    () => this.currentUrl() === '/' || this.currentUrl().startsWith('/map/'),
  );

  protected readonly navItems: UiNavItem[] = [
    { label: 'Journey', icon: 'map', route: '/', exact: true },
    { label: 'Society', icon: 'users', route: '/team' },
    { label: 'Chronicle', icon: 'book', route: '/history' },
    { label: 'Ledger', icon: 'id-card', route: '/ledger' },
  ];

  constructor() {
    if (this.auth.isAuthenticated() && this.auth.profile() === null) {
      this.auth.fetchProfile().subscribe({ error: () => {} });
    }

    this.router.events
      .pipe(filter((event): event is NavigationEnd => event instanceof NavigationEnd))
      .subscribe(() => (this.navigations += 1));

    // Fetch the current Session once we can (and retry after landing back
    // from the session picker) so the app bar can show its name.
    effect(() => {
      const url = this.currentUrl();
      if (url === '/pick-session') {
        this.sessionRequested = false;
        return;
      }
      if (this.isAuthenticated() && !this.isChromeless()) {
        this.loadSession();
      }
    });
  }

  private loadSession(): void {
    if (this.sessionRequested) return;
    this.sessionRequested = true;
    this.api.currentSession().subscribe({
      next: (session) => this.session.set(session),
      error: () => {}, // no session yet — sessionTitle() keeps the 'Tower Rush' fallback
    });
  }

  /** Back button for non-tab-root screens (task 4.2). */
  protected goBack(): void {
    if (this.navigations > 1) {
      this.location.back();
      return;
    }
    this.router.navigateByUrl(this.tabRootForCurrentUrl());
  }

  private tabRootForCurrentUrl(): string {
    const url = this.currentUrl();
    if (url.startsWith('/team')) return '/team';
    if (url.startsWith('/history')) return '/history';
    if (url.startsWith('/ledger')) return '/ledger';
    return '/';
  }
}
