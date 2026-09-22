import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { UiIconComponent } from '../icon/icon.component';
import { UiIconName } from '../icons/icon-paths';

/**
 * `ui-stat-tile` — labelled metric with a leading icon box
 * (docs/design-system.md §5). Pass `value` for a plain string/number, or
 * project custom markup (e.g. a countdown) when `value` is omitted.
 */
@Component({
  selector: 'ui-stat-tile',
  standalone: true,
  imports: [UiIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'ui-stat-tile' },
  template: `
    <span class="ui-stat-tile__icon">
      <ui-icon [name]="icon()" [size]="20" />
    </span>
    <span class="ui-stat-tile__column">
      <span class="ui-stat-tile__label tr-eyebrow">{{ label() }}</span>
      <span class="ui-stat-tile__value tr-h3">
        @if (value() !== undefined) {
          {{ value() }}
        } @else {
          <ng-content />
        }
      </span>
    </span>
  `,
  styles: `
    :host {
      box-sizing: border-box;
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      padding: var(--spacing-sm) var(--spacing-md);
      border-radius: var(--radius-lg);
      background: var(--color-bg-raised);
      border: 1px solid var(--color-border-subtle);
    }
    .ui-stat-tile__icon {
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
    .ui-stat-tile__column {
      display: flex;
      min-width: 0;
      flex-direction: column;
      gap: 2px;
    }
    .ui-stat-tile__label {
      color: var(--color-text-muted);
    }
    .ui-stat-tile__value {
      overflow: hidden;
      color: var(--color-text-primary);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  `,
})
export class UiStatTileComponent {
  readonly icon = input.required<UiIconName>();
  readonly label = input.required<string>();
  readonly value = input<string | number | undefined>(undefined);
}
