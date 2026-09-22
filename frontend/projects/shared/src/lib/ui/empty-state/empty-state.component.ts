import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { UiIconComponent } from '../icon/icon.component';
import { UiIconName } from '../icons/icon-paths';

/**
 * `ui-empty-state` — centred placeholder (docs/design-system.md §5).
 * Project a `ui-button` (or similar) for the optional action.
 */
@Component({
  selector: 'ui-empty-state',
  standalone: true,
  imports: [UiIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'ui-empty-state' },
  template: `
    <span class="ui-empty-state__icon">
      <ui-icon [name]="icon()" [size]="48" />
    </span>
    <h3 class="ui-empty-state__title tr-h3">{{ title() }}</h3>
    @if (description(); as text) {
      <p class="ui-empty-state__description tr-body">{{ text }}</p>
    }
    <ng-content />
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: var(--spacing-sm);
      padding: var(--spacing-xl);
      text-align: center;
    }
    .ui-empty-state__icon {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 96px;
      height: 96px;
      border-radius: var(--radius-full);
      background: var(--color-bg-inset);
      color: var(--color-text-muted);
    }
    .ui-empty-state__title {
      color: var(--color-text-primary);
    }
    .ui-empty-state__description {
      max-width: 32ch;
      color: var(--color-text-secondary);
    }
  `,
})
export class UiEmptyStateComponent {
  readonly icon = input.required<UiIconName>();
  readonly title = input.required<string>();
  readonly description = input<string | undefined>(undefined);
}
