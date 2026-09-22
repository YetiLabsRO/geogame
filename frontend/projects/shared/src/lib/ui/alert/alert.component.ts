import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { UiIconComponent } from '../icon/icon.component';
import { UiIconName } from '../icons/icon-paths';

export type UiAlertTone = 'info' | 'success' | 'warning' | 'danger';

/**
 * `ui-alert` — inline notice (replaces Bootstrap `.alert`). A tinted
 * panel with a 3px tone bar on the left; `danger` announces as an alert,
 * the other tones as status text. Transient messages belong in
 * `ToastService` instead.
 */
@Component({
  selector: 'ui-alert',
  standalone: true,
  imports: [UiIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'ui-alert tr-body',
    '[attr.data-tone]': 'tone()',
    '[attr.role]': 'tone() === "danger" ? "alert" : "status"',
  },
  template: `
    @if (icon(); as name) {
      <ui-icon class="ui-alert__icon" [name]="name" [size]="18" />
    }
    <div class="ui-alert__body"><ng-content /></div>
  `,
  styles: `
    :host {
      display: flex;
      gap: var(--spacing-sm);
      align-items: flex-start;
      padding: var(--spacing-sm) var(--spacing-md);
      border-radius: var(--radius-md);
      border-left: 3px solid var(--_tone);
      background: var(--_tint);
      color: var(--color-text-primary);
      --_tone: var(--color-accent-slate);
      --_tint: var(--color-bg-inset);
    }
    :host([data-tone='success']) {
      --_tone: var(--color-success);
      --_tint: var(--color-success-tint);
    }
    :host([data-tone='warning']) {
      --_tone: var(--color-warning);
      --_tint: var(--color-warning-tint);
    }
    :host([data-tone='danger']) {
      --_tone: var(--color-danger);
      --_tint: var(--color-danger-tint);
    }
    .ui-alert__icon {
      flex-shrink: 0;
      margin-top: 1px;
      color: var(--_tone);
    }
    .ui-alert__body {
      min-width: 0;
      flex: 1;
    }
  `,
})
export class UiAlertComponent {
  readonly tone = input<UiAlertTone>('info');
  /** Optional leading icon; defaults per tone when `true`. */
  readonly withIcon = input(false);

  readonly icon = computed<UiIconName | null>(() => {
    if (!this.withIcon()) return null;
    switch (this.tone()) {
      case 'success':
        return 'star';
      case 'warning':
        return 'bell';
      case 'danger':
        return 'target';
      default:
        return 'lightbulb';
    }
  });
}
