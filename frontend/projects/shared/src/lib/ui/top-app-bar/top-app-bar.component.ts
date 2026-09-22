import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { UiIconComponent } from '../icon/icon.component';

/**
 * `ui-top-app-bar` — sticky header (docs/design-system.md §5). Shows the
 * compass brand mark by default, or a back button when `back` is set.
 * Project trailing action icons with the `appBarActions` attribute.
 */
@Component({
  selector: 'ui-top-app-bar',
  standalone: true,
  imports: [UiIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'ui-top-app-bar tr-safe-top' },
  template: `
    <div class="ui-top-app-bar__row">
      <div class="ui-top-app-bar__leading">
        @if (back()) {
          <button
            type="button"
            class="ui-top-app-bar__back"
            aria-label="Back"
            (click)="backPressed.emit()"
          >
            <ui-icon name="chevron-left" [size]="24" />
          </button>
        } @else {
          <span class="ui-top-app-bar__mark">
            <ui-icon name="compass" [size]="17" />
          </span>
        }
        <span class="ui-top-app-bar__title tr-h3">{{ title() }}</span>
      </div>
      <div class="ui-top-app-bar__actions">
        <ng-content select="[appBarActions]" />
      </div>
    </div>
  `,
  styles: `
    :host {
      position: sticky;
      top: 0;
      z-index: 20;
      display: block;
      background: var(--color-bg-canvas);
    }
    .ui-top-app-bar__row {
      box-sizing: border-box;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
      height: 56px;
      padding-inline: var(--spacing-xl);
    }
    .ui-top-app-bar__leading {
      display: flex;
      min-width: 0;
      align-items: center;
      gap: var(--spacing-sm);
    }
    .ui-top-app-bar__mark {
      display: flex;
      flex-shrink: 0;
      align-items: center;
      justify-content: center;
      width: 30px;
      height: 30px;
      border-radius: var(--radius-full);
      background: var(--color-brand-primary);
      color: var(--color-text-onBrand);
    }
    .ui-top-app-bar__back {
      display: flex;
      flex-shrink: 0;
      align-items: center;
      justify-content: center;
      width: var(--tap-min);
      height: var(--tap-min);
      margin-left: -10px;
      border: none;
      background: transparent;
      color: var(--color-brand-onSurface);
      cursor: pointer;
    }
    .ui-top-app-bar__title {
      overflow: hidden;
      color: var(--color-brand-onSurface);
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .ui-top-app-bar__actions {
      display: flex;
      flex-shrink: 0;
      align-items: center;
      gap: var(--spacing-2xs);
      min-height: var(--tap-min);
    }
  `,
})
export class UiTopAppBarComponent {
  readonly title = input<string | undefined>(undefined);
  readonly back = input(false);
  readonly backPressed = output<void>();
}
