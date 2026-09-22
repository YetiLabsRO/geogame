import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { UiIconComponent } from '../icon/icon.component';
import { UiIconName } from '../icons/icon-paths';

export type UiChipTone = 'brand' | 'solid' | 'slate' | 'neutral';

/**
 * `ui-chip` — pill label (docs/design-system.md §5). A `teamColor` input
 * switches the chip to the runtime team style regardless of `tone`.
 */
@Component({
  selector: 'ui-chip',
  standalone: true,
  imports: [UiIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'ui-chip tr-eyebrow',
    '[attr.data-tone]': 'tone()',
    '[attr.data-team]': 'teamColor() ? "" : null',
    '[style.--team-color]': 'teamColor()',
  },
  template: `
    @if (icon(); as name) {
      <ui-icon class="ui-chip__icon" [name]="name" [size]="14" />
    }
    <span class="ui-chip__label"><ng-content /></span>
  `,
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      gap: var(--spacing-2xs);
      padding: 4px var(--spacing-sm);
      border-radius: var(--radius-full);
      border: 1px solid transparent;
      white-space: nowrap;
    }
    .ui-chip__icon {
      flex-shrink: 0;
    }

    :host([data-tone='brand']) {
      background: var(--color-brand-tint);
      border-color: var(--color-border-brand);
      color: var(--color-brand-onSurface);
    }
    :host([data-tone='solid']) {
      background: var(--color-brand-primary);
      color: var(--color-text-onBrand);
    }
    :host([data-tone='slate']) {
      background: var(--color-bg-inset);
      color: var(--color-accent-slate);
    }
    :host([data-tone='neutral']) {
      background: var(--color-bg-inset);
      color: var(--color-text-muted);
    }

    /* Runtime team colour wins over any tone. */
    :host([data-team]) {
      background: color-mix(in srgb, var(--team-color) 15%, transparent);
      border-color: var(--team-color);
      color: var(--team-color);
    }
  `,
})
export class UiChipComponent {
  readonly tone = input<UiChipTone>('neutral');
  readonly teamColor = input<string | undefined>(undefined);
  readonly icon = input<UiIconName | undefined>(undefined);
}
