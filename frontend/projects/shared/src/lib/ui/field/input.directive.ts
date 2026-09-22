import { Directive, ElementRef, inject, signal } from '@angular/core';

import { UI_FIELD } from './field.component';

type UiInputElement = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

let nextInputId = 0;

/**
 * `[uiInput]` — pairs with `ui-field` (docs/design-system.md §5). Applies
 * to `<input>`, `<select>` or `<textarea>`; generates a stable id, wires
 * `aria-describedby`/`aria-invalid` from the wrapping `ui-field`'s
 * help/error state, and exposes `focused`/`disabled` for styling.
 */
@Directive({
  selector: '[uiInput]',
  standalone: true,
  host: {
    class: 'ui-input',
    '[attr.id]': 'id',
    '[attr.aria-describedby]': 'describedBy',
    '[attr.aria-invalid]': 'invalid ? "true" : null',
    '[attr.data-focused]': 'focused() ? "" : null',
    '[attr.data-disabled]': 'disabled ? "" : null',
    '(focus)': 'focused.set(true)',
    '(blur)': 'focused.set(false)',
  },
})
export class UiInputDirective {
  readonly id = `ui-input-${nextInputId++}`;
  readonly focused = signal(false);

  private readonly field = inject(UI_FIELD, { optional: true });
  private readonly elementRef = inject<ElementRef<UiInputElement>>(ElementRef);

  get describedBy(): string | null {
    return this.field?.describedById || null;
  }

  get invalid(): boolean {
    return this.field?.invalid ?? false;
  }

  get disabled(): boolean {
    return this.elementRef.nativeElement.disabled === true;
  }
}
