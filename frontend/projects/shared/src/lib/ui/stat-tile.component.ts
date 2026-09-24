import { ChangeDetectionStrategy, Component, input } from '@angular/core';

export type StatTileTone = 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'info';

/**
 * Labeled metric tile for dashboards, e.g. "12 · Active towers".
 *
 * Usage:
 * ```html
 * <app-stat-tile label="Active towers" [value]="12" icon="bi-flag" tone="primary" />
 * ```
 */
@Component({
  selector: 'app-stat-tile',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="app-stat-tile" [class]="'app-stat-tile--' + tone()">
      @if (icon()) {
        <i class="bi {{ icon() }} app-stat-tile__icon" aria-hidden="true"></i>
      }
      <div class="app-stat-tile__body">
        <div class="app-stat-tile__value tabular-nums">{{ value() }}</div>
        <div class="app-stat-tile__label">{{ label() }}</div>
      </div>
    </div>
  `,
  styles: `
    .app-stat-tile {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      padding: var(--space-4);
      border-radius: var(--radius);
      background-color: var(--panel);
      border: 1px solid var(--border);
      box-shadow: var(--shadow-1);
      --tile-accent: var(--ink-muted);
    }

    .app-stat-tile--primary {
      --tile-accent: var(--primary);
    }

    .app-stat-tile--success {
      --tile-accent: var(--success);
    }

    .app-stat-tile--warning {
      --tile-accent: var(--warning);
    }

    .app-stat-tile--danger {
      --tile-accent: var(--danger);
    }

    .app-stat-tile--info {
      --tile-accent: var(--info);
    }

    .app-stat-tile__icon {
      flex: 0 0 auto;
      font-size: var(--text-xl);
      color: var(--tile-accent);
    }

    .app-stat-tile__value {
      font-size: var(--text-2xl);
      font-weight: 650;
      line-height: 1.1;
      color: var(--ink);
    }

    .app-stat-tile__label {
      margin-top: var(--space-1);
      font-size: var(--text-sm);
      color: var(--ink-muted);
    }
  `,
})
export class StatTileComponent {
  readonly label = input.required<string>();
  readonly value = input.required<string | number>();
  /** A `bi-*` bootstrap-icons class, e.g. `"bi-flag"`. */
  readonly icon = input<string | undefined>(undefined);
  readonly tone = input<StatTileTone>('default');
}
