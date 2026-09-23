import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { filter } from 'rxjs';

import { AuthService } from 'shared';

import { SessionSwitcherComponent } from './session-switcher.component';

/** One destination in the staff sidebar. */
export interface NavItem {
  label: string;
  link: string;
  icon: string;
  /** Only `/` needs exact matching; every other link is a prefix. */
  exact?: boolean;
}

export interface NavSection {
  label: string;
  items: NavItem[];
}

/**
 * The staff sidebar, grouped by *when* a screen is used rather than by
 * what data it edits: staff arrive at this console preparing a game,
 * running one, or looking back at one, and that predicts the screen they
 * want far better than the underlying model does.
 *
 * This array is the single place a destination is declared. The previous
 * shell repeated a near-identical block of markup per link, which is how
 * `/nfc-tags` ended up with a route and a working page that nothing ever
 * linked to.
 */
export const NAV_SECTIONS: NavSection[] = [
  {
    label: 'Run',
    items: [
      { label: 'Review queue', link: '/', icon: 'bi-inbox', exact: true },
      { label: 'Field mode', link: '/field', icon: 'bi-compass' },
      { label: 'Scoreboard', link: '/scoreboard', icon: 'bi-trophy' },
      { label: 'Join requests', link: '/join-requests', icon: 'bi-person-plus' },
      { label: 'Game state', link: '/game-state', icon: 'bi-sliders' },
      { label: 'Dementors', link: '/dementors', icon: 'bi-lightning-charge' },
    ],
  },
  {
    label: 'Build',
    items: [
      { label: 'Map editor', link: '/map-editor', icon: 'bi-pencil-square' },
      { label: 'Towers', link: '/towers', icon: 'bi-geo-alt' },
      { label: 'Zones', link: '/zones', icon: 'bi-bounding-box' },
      { label: 'Collections', link: '/collections', icon: 'bi-collection' },
      { label: 'Challenges', link: '/challenges', icon: 'bi-puzzle' },
      { label: 'Trails', link: '/trails', icon: 'bi-signpost-split' },
      { label: 'NFC tags', link: '/nfc-tags', icon: 'bi-tag' },
      { label: 'Badges', link: '/badges', icon: 'bi-cpu' },
      { label: 'AI review', link: '/authoring', icon: 'bi-robot' },
    ],
  },
  {
    label: 'Organize',
    items: [
      { label: 'Games', link: '/games', icon: 'bi-flag' },
      { label: 'Sessions', link: '/sessions', icon: 'bi-calendar-event' },
      { label: 'Teams', link: '/teams', icon: 'bi-people' },
      { label: 'Invites', link: '/invites', icon: 'bi-envelope' },
    ],
  },
  {
    label: 'Analyze',
    items: [{ label: 'Simulator', link: '/simulator', icon: 'bi-activity' }],
  },
];

@Component({
  selector: 'app-root',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterOutlet, RouterLink, RouterLinkActive, SessionSwitcherComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  protected readonly isAuthenticated = this.auth.isAuthenticated;
  protected readonly isStaff = this.auth.isStaff;
  protected readonly username = computed(() => this.auth.profile()?.username ?? null);
  protected readonly sections = NAV_SECTIONS;

  /** Only meaningful below `lg`, where the sidebar is an overlay. */
  protected readonly sidebarOpen = signal(false);

  constructor() {
    if (this.auth.isAuthenticated() && this.auth.profile() === null) {
      this.auth.fetchProfile().subscribe({ error: () => {} });
    }
    // Choosing a destination dismisses the overlay; on wide screens the
    // sidebar is persistent and this is a no-op.
    this.router.events
      .pipe(
        filter((event) => event instanceof NavigationEnd),
        takeUntilDestroyed(),
      )
      .subscribe(() => this.sidebarOpen.set(false));
  }

  protected toggleSidebar(): void {
    this.sidebarOpen.update((open) => !open);
  }

  protected closeSidebar(): void {
    this.sidebarOpen.set(false);
  }

  protected logout(): void {
    this.auth.logout().subscribe({
      next: () => this.router.navigateByUrl('/login'),
      error: () => this.router.navigateByUrl('/login'),
    });
  }
}
