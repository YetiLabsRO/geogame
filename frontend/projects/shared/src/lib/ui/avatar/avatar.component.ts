import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { UiIconComponent } from '../icon/icon.component';

export type UiAvatarSize = 32 | 40 | 56;

/**
 * `ui-avatar` — circular identity badge (docs/design-system.md §5). Shows
 * an image, initials derived from `name`, or falls back to the `users`
 * icon. `teamColor` turns the ring into the runtime team colour.
 */
@Component({
  selector: 'ui-avatar',
  standalone: true,
  imports: [UiIconComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    class: 'ui-avatar',
    '[style.width.px]': 'size()',
    '[style.height.px]': 'size()',
    '[style.--team-color]': 'teamColor()',
    '[attr.data-team]': 'teamColor() ? "" : null',
  },
  template: `
    @if (src(); as url) {
      <img class="ui-avatar__img" [src]="url" [alt]="alt() ?? ''" />
    } @else if (initials(); as text) {
      <span class="ui-avatar__initials tr-h3">{{ text }}</span>
    } @else {
      <ui-icon name="users" [size]="iconSize()" [label]="alt()" />
    }
  `,
  styles: `
    :host {
      position: relative;
      display: inline-flex;
      flex-shrink: 0;
      align-items: center;
      justify-content: center;
      overflow: hidden;
      border-radius: var(--radius-full);
      background: var(--color-bg-inset);
      border: 1px solid var(--color-border-brand);
      color: var(--color-brand-onSurface);
    }
    :host([data-team]) {
      border-color: var(--team-color);
    }
    .ui-avatar__img {
      width: 100%;
      height: 100%;
      object-fit: cover;
    }
  `,
})
export class UiAvatarComponent {
  readonly size = input<UiAvatarSize>(56);
  readonly src = input<string | undefined>(undefined);
  readonly name = input<string | undefined>(undefined);
  readonly teamColor = input<string | undefined>(undefined);
  readonly alt = input<string | undefined>(undefined);

  readonly iconSize = computed(() => Math.round(this.size() * (26 / 56)));

  readonly initials = computed<string | undefined>(() => {
    const name = this.name();
    if (!name) return undefined;
    const parts = name.trim().split(/\s+/).filter(Boolean);
    if (parts.length === 0) return undefined;
    const first = parts[0]?.[0] ?? '';
    const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : '';
    return (first + last).toUpperCase() || undefined;
  });
}
