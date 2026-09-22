import { ChangeDetectionStrategy, Component, input } from '@angular/core';

/**
 * `ui-spinner` — indeterminate loading ring (replaces Bootstrap
 * `.spinner-border`). Inherits `currentColor`; wrap it with text for a
 * labelled loading row. Buttons have their own `loading` input.
 */
@Component({
  selector: 'ui-spinner',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'ui-spinner',
    role: 'status',
    '[attr.aria-label]': 'label()',
    '[style.width.px]': 'size()',
    '[style.height.px]': 'size()',
  },
  template: '',
  styles: `
    :host {
      display: inline-block;
      flex-shrink: 0;
      border-radius: 50%;
      border: 2px solid currentColor;
      border-top-color: transparent;
      opacity: 0.7;
      animation: ui-spinner-spin 0.7s linear infinite;
    }
    @keyframes ui-spinner-spin {
      to {
        transform: rotate(360deg);
      }
    }
  `,
})
export class UiSpinnerComponent {
  readonly size = input(20);
  readonly label = input('Loading');
}
