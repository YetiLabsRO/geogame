import { ChangeDetectionStrategy, Component, InjectionToken, input } from '@angular/core';

import { UiIconComponent } from '../icon/icon.component';
import { UiIconName } from '../icons/icon-paths';

/**
 * What `UiInputDirective` needs from its wrapping `ui-field` to wire up
 * `aria-describedby`/`aria-invalid` on the projected control. Kept as a
 * token + interface (rather than the directive importing the component
 * class) so the two files don't need a circular runtime dependency.
 */
export interface UiFieldHost {
  readonly describedById: string;
  readonly invalid: boolean;
}

export const UI_FIELD = new InjectionToken<UiFieldHost>('UI_FIELD');

let nextMessageId = 0;

/**
 * `ui-field` — labelled input wrapper (docs/design-system.md §5). Projects
 * the control (`<input uiInput>`, `<select uiInput>`, `<textarea uiInput>`);
 * pair it with the `uiInput` directive from `./input.directive` for the
 * id/aria wiring.
 */
@Component({
  selector: 'ui-field',
  standalone: true,
  imports: [UiIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  providers: [{ provide: UI_FIELD, useExisting: UiFieldComponent }],
  host: {
    class: 'ui-field',
    '[class.ui-field--error]': 'invalid',
  },
  template: `
    <div class="ui-field__control">
      @if (icon(); as name) {
        <ui-icon class="ui-field__icon" [name]="name" [size]="18" />
      }
      <ng-content />
    </div>
    @if (label(); as text) {
      <span class="ui-field__label tr-field-label">{{ text }}</span>
    }
    @if (error(); as message) {
      <p class="ui-field__message tr-body" [id]="messageId">{{ message }}</p>
    } @else if (help(); as message) {
      <p class="ui-field__message tr-body" [id]="messageId">{{ message }}</p>
    }
  `,
  styles: `
    :host {
      display: block;
    }
    .ui-field {
      position: relative;
    }
    .ui-field__control {
      box-sizing: border-box;
      display: flex;
      align-items: center;
      gap: var(--spacing-xs);
      min-height: 52px;
      padding-inline: var(--spacing-md);
      border-radius: var(--radius-xl);
      background: var(--color-field-bg);
      border: 1px solid var(--color-border-default);
    }
    .ui-field__control:has([data-focused]) {
      border-color: var(--color-brand-primary);
    }
    .ui-field__control:has([data-disabled]) {
      opacity: 0.6;
    }
    .ui-field__icon {
      flex-shrink: 0;
      color: var(--color-text-secondary);
    }
    .ui-field__control ::ng-deep input,
    .ui-field__control ::ng-deep select,
    .ui-field__control ::ng-deep textarea {
      flex: 1;
      min-width: 0;
      border: none;
      outline: none;
      background: transparent;
      color: var(--color-text-primary);
      font-family: var(--font-ui);
      font-size: 16px;
      line-height: 24px;
      padding-block: 14px;
    }
    .ui-field__control ::ng-deep textarea {
      resize: vertical;
      min-height: 52px;
    }
    .ui-field__control ::ng-deep input::placeholder,
    .ui-field__control ::ng-deep textarea::placeholder {
      color: var(--color-text-placeholder);
    }
    .ui-field__label {
      position: absolute;
      top: -9px;
      left: 11px;
      padding-inline: 6px;
      background: var(--color-bg-canvas);
      color: var(--color-brand-onSurface);
    }
    .ui-field__message {
      margin: var(--spacing-2xs) var(--spacing-2xs) 0;
      color: var(--color-text-secondary);
    }
    .ui-field--error .ui-field__control {
      border-color: var(--color-danger);
    }
    .ui-field--error .ui-field__label {
      color: var(--color-danger);
    }
    .ui-field--error .ui-field__message {
      color: var(--color-danger);
    }
  `,
})
export class UiFieldComponent implements UiFieldHost {
  readonly label = input<string | undefined>(undefined);
  readonly help = input<string | undefined>(undefined);
  readonly error = input<string | undefined>(undefined);
  readonly icon = input<UiIconName | undefined>(undefined);

  readonly messageId = `ui-field-msg-${nextMessageId++}`;

  get describedById(): string {
    return this.help() || this.error() ? this.messageId : '';
  }

  get invalid(): boolean {
    return !!this.error();
  }
}
