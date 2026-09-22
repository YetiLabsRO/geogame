import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';

import { ICON_PATHS, UiIconName } from '../icons/icon-paths';

export { UI_ICON_NAMES, type UiIconName } from '../icons/icon-paths';

/**
 * `ui-icon` — inlines one of the 16 design-system line icons (24×24,
 * stroke 1.75, `currentColor`). See docs/design-system.md §4.
 */
@Component({
  selector: 'ui-icon',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'ui-icon',
    '[style.width.px]': 'size()',
    '[style.height.px]': 'size()',
    '[attr.role]': 'label() ? "img" : null',
    '[attr.aria-label]': 'label() ?? null',
    '[attr.aria-hidden]': 'label() ? null : "true"',
  },
  template: `
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="1.75"
      stroke-linecap="round"
      stroke-linejoin="round"
      [innerHTML]="markup()"
    ></svg>
  `,
  styles: `
    :host {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      color: inherit;
    }
    svg {
      display: block;
      width: 100%;
      height: 100%;
    }
  `,
})
export class UiIconComponent {
  readonly name = input.required<UiIconName>();
  readonly size = input(24);
  /** Accessible label. Omit for decorative icons (the default). */
  readonly label = input<string | undefined>(undefined);

  private readonly sanitizer = inject(DomSanitizer);

  readonly markup = computed<SafeHtml>(() =>
    this.sanitizer.bypassSecurityTrustHtml(ICON_PATHS[this.name()]),
  );
}
