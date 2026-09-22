import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type UiProgressMeterTone = 'brand' | 'team' | 'success' | 'danger';

/**
 * `ui-progress-meter` — labelled progress bar (docs/design-system.md §5).
 * `tone="team"` fills from the runtime `--team-color`.
 */
@Component({
  selector: 'ui-progress-meter',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'ui-progress-meter',
    role: 'progressbar',
    '[attr.data-tone]': 'tone()',
    '[attr.aria-valuenow]': 'value()',
    '[attr.aria-valuemin]': '0',
    '[attr.aria-valuemax]': 'max()',
    '[attr.aria-label]': 'label() ?? null',
  },
  template: `
    <div class="ui-progress-meter__header tr-field-label">
      <span class="ui-progress-meter__label">{{ label() }}</span>
      <span class="ui-progress-meter__value">{{ valueLabel() }}</span>
    </div>
    <div class="ui-progress-meter__track">
      <div class="ui-progress-meter__fill" [style.width.%]="percent()"></div>
    </div>
  `,
  styles: `
    :host {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-xs);
    }
    .ui-progress-meter__header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-xs);
    }
    .ui-progress-meter__label {
      color: var(--color-text-secondary);
    }
    .ui-progress-meter__value {
      color: var(--color-brand-onSurface);
    }
    .ui-progress-meter__track {
      height: 8px;
      overflow: hidden;
      border-radius: var(--radius-full);
      background: var(--color-bg-inset);
    }
    .ui-progress-meter__fill {
      height: 100%;
      border-radius: var(--radius-full);
      background: var(--color-brand-primary);
      transition: width 0.2s ease;
    }
    :host([data-tone='team']) .ui-progress-meter__fill {
      background: var(--team-color);
    }
    :host([data-tone='success']) .ui-progress-meter__fill {
      background: var(--color-success);
    }
    :host([data-tone='danger']) .ui-progress-meter__fill {
      background: var(--color-danger);
    }
  `,
})
export class UiProgressMeterComponent {
  readonly label = input<string | undefined>(undefined);
  readonly valueLabel = input<string | undefined>(undefined);
  readonly value = input(0);
  readonly max = input(100);
  readonly tone = input<UiProgressMeterTone>('brand');

  readonly percent = computed(() => {
    const max = this.max() || 100;
    return Math.min(100, Math.max(0, (this.value() / max) * 100));
  });
}
