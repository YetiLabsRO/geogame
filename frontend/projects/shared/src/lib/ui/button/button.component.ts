import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { UiIconComponent } from '../icon/icon.component';
import { UiIconName } from '../icons/icon-paths';

export type UiButtonVariant = 'primary' | 'secondary' | 'tinted';
export type UiButtonSize = 'sm' | 'md' | 'lg';

/**
 * `ui-button` — pill action button (docs/design-system.md §5). Renders a
 * real `<button>` internally so it works inside `<form>`s (submit type,
 * native `disabled`).
 */
@Component({
  selector: 'ui-button',
  standalone: true,
  imports: [UiIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'ui-button',
    '[class.ui-button--block]': 'block()',
    '[attr.data-variant]': 'variant()',
    '[attr.data-size]': 'size()',
  },
  template: `
    <button
      class="ui-button__el"
      [class.tr-button-serif]="variant() === 'primary'"
      [class.tr-button-label]="variant() !== 'primary'"
      [type]="type()"
      [disabled]="disabled() || loading()"
      (click)="pressed.emit()"
    >
      <span class="ui-button__label"><ng-content /></span>
      @if (loading()) {
        <span class="ui-button__spinner" aria-hidden="true"></span>
      } @else if (icon(); as name) {
        <ui-icon class="ui-button__icon" [name]="name" [size]="20" />
      }
    </button>
  `,
  styles: `
    :host {
      display: inline-block;
    }
    :host(.ui-button--block) {
      display: block;
      width: 100%;
    }
    .ui-button__el {
      box-sizing: border-box;
      display: inline-flex;
      width: 100%;
      align-items: center;
      justify-content: center;
      gap: var(--spacing-xs);
      height: 56px;
      padding-inline: var(--spacing-xl);
      border-radius: var(--radius-xl);
      border: none;
      background: transparent;
      color: inherit;
      cursor: pointer;
      -webkit-tap-highlight-color: transparent;
    }
    .ui-button__el:disabled {
      cursor: not-allowed;
      opacity: 0.45;
    }
    .ui-button__el:focus-visible {
      outline: 2px solid var(--color-brand-primary);
      outline-offset: 2px;
    }
    .ui-button__label {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }
    .ui-button__icon,
    .ui-button__spinner {
      flex-shrink: 0;
    }

    :host([data-variant='primary']) .ui-button__el {
      background: var(--color-brand-primary);
      color: var(--color-text-onBrand);
      box-shadow: var(--elevation-brand-glow);
    }
    :host([data-variant='secondary']) .ui-button__el {
      background: transparent;
      color: var(--color-brand-onSurface);
      border: 1.5px solid var(--color-border-default);
    }
    :host([data-variant='tinted']) .ui-button__el {
      background: var(--color-brand-tint);
      color: var(--color-brand-onSurface);
      border: 1px solid var(--color-border-brand);
    }

    :host([data-size='lg']) .ui-button__el {
      height: 56px;
    }
    :host([data-size='md']) .ui-button__el {
      height: 48px;
    }
    :host([data-size='sm']) .ui-button__el {
      /* Figma draws 40px; 44px keeps the WCAG tap-target minimum. */
      height: 44px;
      padding-inline: var(--spacing-md);
      font-size: 12px;
      line-height: 16px;
    }

    .ui-button__spinner {
      width: 20px;
      height: 20px;
      border-radius: 50%;
      border: 2px solid currentColor;
      border-top-color: transparent;
      opacity: 0.7;
      animation: ui-button-spin 0.7s linear infinite;
    }
    @keyframes ui-button-spin {
      to {
        transform: rotate(360deg);
      }
    }
  `,
})
export class UiButtonComponent {
  readonly variant = input<UiButtonVariant>('primary');
  readonly size = input<UiButtonSize>('lg');
  readonly block = input(false);
  readonly loading = input(false);
  readonly disabled = input(false);
  readonly type = input<'button' | 'submit'>('button');
  readonly icon = input<UiIconName | undefined>(undefined);

  readonly pressed = output<void>();
}
