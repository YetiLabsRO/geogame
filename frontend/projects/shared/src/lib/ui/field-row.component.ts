import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { InfoHintComponent } from './info-hint.component';

/**
 * Form-field wrapper: label + optional required marker + optional
 * `InfoHint` + projected control + optional help line + optional error
 * text.
 *
 * Usage:
 * ```html
 * <app-field-row label="Team name" hint="Shown to other captains." required [error]="nameError()">
 *   <input class="form-control" [formControl]="nameControl" [id]="'team-name'" />
 * </app-field-row>
 * ```
 */
@Component({
  selector: 'app-field-row',
  standalone: true,
  imports: [InfoHintComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div
      class="app-field-row"
      [class.app-field-row--horizontal]="layout() === 'horizontal'"
    >
      <label class="app-field-row__label" [for]="for()">
        {{ label() }}
        @if (required()) {
          <span class="app-field-row__required" aria-hidden="true">*</span>
          <span class="visually-hidden">required</span>
        }
        @if (hint()) {
          <app-info-hint [text]="hint()!" />
        }
      </label>
      <div class="app-field-row__control">
        <ng-content></ng-content>
        @if (error()) {
          <div class="app-field-row__error" role="alert">{{ error() }}</div>
        } @else if (help()) {
          <div class="app-field-row__help">{{ help() }}</div>
        }
      </div>
    </div>
  `,
  styles: `
    .app-field-row {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
      margin-bottom: var(--space-4);
    }

    .app-field-row__label {
      display: inline-flex;
      align-items: center;
      gap: var(--space-1);
      font-size: var(--text-sm);
      font-weight: 600;
      color: var(--ink);
    }

    .app-field-row__required {
      color: var(--danger);
    }

    .app-field-row__control {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
    }

    .app-field-row__help {
      font-size: var(--text-xs);
      color: var(--ink-muted);
    }

    .app-field-row__error {
      font-size: var(--text-xs);
      color: var(--danger);
    }

    @media (min-width: 640px) {
      .app-field-row--horizontal {
        flex-direction: row;
        align-items: baseline;
        gap: var(--space-4);
      }

      .app-field-row--horizontal .app-field-row__label {
        flex: 0 0 10rem;
      }

      .app-field-row--horizontal .app-field-row__control {
        flex: 1 1 auto;
      }
    }
  `,
})
export class FieldRowComponent {
  readonly label = input.required<string>();
  readonly hint = input<string | undefined>(undefined);
  readonly required = input(false);
  readonly error = input<string | undefined>(undefined);
  readonly help = input<string | undefined>(undefined);
  readonly for = input<string | undefined>(undefined);
  readonly layout = input<'stacked' | 'horizontal'>('stacked');
}
