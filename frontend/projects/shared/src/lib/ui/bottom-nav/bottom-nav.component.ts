import { toSignal } from '@angular/core/rxjs-interop';
import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { NavigationEnd, Router, RouterLink } from '@angular/router';
import { filter, map } from 'rxjs';

import { UiIconComponent } from '../icon/icon.component';
import { UiIconName } from '../icons/icon-paths';

export interface UiNavItem {
  label: string;
  icon: UiIconName;
  route: string;
  /** Force exact-match activation even for a non-root route. */
  exact?: boolean;
}

/**
 * `ui-bottom-nav` — four-tab primary navigation (docs/design-system.md §5).
 * A tab is active when the current URL equals its `route` (always true for
 * `/`, or when `exact` is set) or otherwise starts with it.
 */
@Component({
  selector: 'ui-bottom-nav',
  standalone: true,
  imports: [RouterLink, UiIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'ui-bottom-nav tr-safe-bottom', role: 'navigation' },
  template: `
    @for (item of items(); track item.route) {
      <a
        class="ui-bottom-nav__item"
        [class.ui-bottom-nav__item--active]="isActive(item)"
        [attr.aria-current]="isActive(item) ? 'page' : null"
        [routerLink]="item.route"
      >
        <ui-icon [name]="item.icon" [size]="24" />
        <span class="ui-bottom-nav__label tr-meta-tiny">{{ item.label }}</span>
      </a>
    }
  `,
  styles: `
    :host {
      position: fixed;
      right: 0;
      bottom: 0;
      left: 0;
      z-index: 30;
      box-sizing: border-box;
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      padding: var(--spacing-sm) var(--spacing-xs) 0;
      background: var(--color-bg-raised);
      border-top: 1px solid var(--color-border-subtle);
    }
    .ui-bottom-nav__item {
      display: flex;
      flex: 1;
      flex-direction: column;
      align-items: center;
      justify-content: flex-start;
      gap: 6px;
      min-height: var(--tap-min);
      padding-block: var(--spacing-xs);
      color: var(--color-text-muted);
      text-decoration: none;
    }
    .ui-bottom-nav__item--active {
      color: var(--color-brand-onSurface);
    }
    .ui-bottom-nav__label {
      color: inherit;
    }
  `,
})
export class UiBottomNavComponent {
  readonly items = input.required<UiNavItem[]>();

  private readonly router = inject(Router);
  private readonly currentUrl = toSignal(
    this.router.events.pipe(
      filter((event): event is NavigationEnd => event instanceof NavigationEnd),
      map((event) => event.urlAfterRedirects),
    ),
    { initialValue: this.router.url },
  );

  isActive(item: UiNavItem): boolean {
    const url = this.currentUrl().split(/[?#]/)[0];
    if (item.exact || item.route === '/') {
      return url === item.route;
    }
    return url === item.route || url.startsWith(`${item.route}/`);
  }
}
