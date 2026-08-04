import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * Page/section header: title + optional subtitle + a projected `actions`
 * slot for buttons. Responsive — actions wrap below the title on narrow
 * screens. Pass `topoBg` to wash the header in the faint topographic
 * contour-line pattern (good for hero/empty-state headers).
 *
 * Usage:
 * ```html
 * <app-page-header title="Towers" subtitle="12 active" [topoBg]="true">
 *   <button actions class="btn btn-primary">New tower</button>
 * </app-page-header>
 * ```
 */
@Component({
  selector: 'app-page-header',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="app-page-header" [class.topo-bg]="topoBg()">
      <div class="app-page-header__text">
        <h1 class="app-page-header__title">{{ title() }}</h1>
        @if (subtitle()) {
          <p class="app-page-header__subtitle">{{ subtitle() }}</p>
        }
      </div>
      <div class="app-page-header__actions">
        <ng-content select="[actions]"></ng-content>
      </div>
    </header>
  `,
  styles: `
    .app-page-header {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-4);
      padding: var(--space-5) var(--space-5);
      border-radius: var(--radius-lg);
      background-color: var(--panel);
      border: 1px solid var(--border);
      margin-bottom: var(--space-5);
    }

    .app-page-header__title {
      margin: 0;
      font-size: var(--text-2xl);
    }

    .app-page-header__subtitle {
      margin: var(--space-1) 0 0;
      color: var(--ink-muted);
      font-size: var(--text-md);
    }

    .app-page-header__actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--space-2);
    }

    .app-page-header__actions:empty {
      display: none;
    }
  `,
})
export class PageHeaderComponent {
  readonly title = input.required<string>();
  readonly subtitle = input<string | undefined>(undefined);
  readonly topoBg = input(false);
}
