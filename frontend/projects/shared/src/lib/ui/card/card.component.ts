import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export type UiCardVariant = 'raised' | 'flat';
export type UiCardPadding = 'md' | 'sm';

/**
 * `ui-card` — surface container (docs/design-system.md §5). Projects the
 * body by default; an element marked `cardActions` projects into a
 * dedicated slot below the body (e.g. a row of buttons).
 */
@Component({
  selector: 'ui-card',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'ui-card',
    '[attr.data-variant]': 'variant()',
    '[attr.data-padding]': 'padding()',
  },
  template: `
    @if (eyebrow(); as text) {
      <span class="ui-card__eyebrow tr-eyebrow">{{ text }}</span>
    }
    @if (title(); as text) {
      <h3 class="ui-card__title tr-card-title">{{ text }}</h3>
    }
    <div class="ui-card__body tr-body">
      <ng-content />
    </div>
    <ng-content select="[cardActions]" />
  `,
  styles: `
    :host {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
      padding: var(--spacing-xl);
      border-radius: var(--radius-lg);
      background: var(--color-bg-raised);
      border: 1px solid var(--color-border-subtle);
      color: var(--color-text-secondary);
    }
    :host([data-padding='sm']) {
      padding: 18px var(--spacing-md);
    }
    :host([data-variant='raised']) {
      box-shadow: var(--elevation-card);
    }
    .ui-card__eyebrow {
      color: var(--color-brand-onSurface);
    }
    .ui-card__title {
      color: var(--color-text-primary);
    }
  `,
})
export class UiCardComponent {
  readonly title = input<string | undefined>(undefined);
  readonly eyebrow = input<string | undefined>(undefined);
  readonly variant = input<UiCardVariant>('raised');
  readonly padding = input<UiCardPadding>('md');
}
