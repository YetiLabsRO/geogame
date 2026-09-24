import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  HostListener,
  computed,
  inject,
  input,
  signal,
} from '@angular/core';

let nextInfoHintId = 0;

/**
 * Inline "info" icon button that reveals help text on hover (desktop) and on
 * click/tap (touch-friendly). Replaces the old hover-only `title="..."`
 * pattern used across the apps.
 *
 * Usage:
 * ```html
 * <app-info-hint text="Only captains can invite new members." />
 * <app-info-hint>
 *   Richer <strong>projected</strong> content works too.
 * </app-info-hint>
 * ```
 */
@Component({
  selector: 'app-info-hint',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="app-info-hint" [class.app-info-hint--open]="isOpen()">
      <button
        type="button"
        class="app-info-hint__trigger"
        [attr.aria-expanded]="isOpen()"
        [attr.aria-describedby]="isOpen() ? hintId : null"
        [attr.aria-label]="ariaLabel()"
        (click)="toggle($event)"
        (mouseenter)="show()"
        (mouseleave)="scheduleHide()"
        (focus)="show()"
        (blur)="scheduleHide()"
      >
        <i class="bi bi-info-circle" aria-hidden="true"></i>
      </button>
      @if (isOpen()) {
        <span
          class="app-info-hint__bubble"
          role="tooltip"
          [id]="hintId"
          (mouseenter)="show()"
          (mouseleave)="scheduleHide()"
        >
          {{ text() }}
          <ng-content></ng-content>
        </span>
      }
    </span>
  `,
  styles: `
    .app-info-hint {
      position: relative;
      display: inline-flex;
      vertical-align: middle;
    }

    .app-info-hint__trigger {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1.25rem;
      height: 1.25rem;
      padding: 0;
      border: none;
      background: transparent;
      color: var(--ink-muted);
      border-radius: 50%;
      cursor: help;
      line-height: 1;
      font-size: var(--text-md);
    }

    .app-info-hint__trigger:hover,
    .app-info-hint__trigger:focus-visible,
    .app-info-hint--open .app-info-hint__trigger {
      color: var(--primary);
    }

    .app-info-hint__bubble {
      position: absolute;
      z-index: 1070;
      top: calc(100% + var(--space-2));
      left: 50%;
      transform: translateX(-50%);
      width: max-content;
      max-width: 16rem;
      padding: var(--space-2) var(--space-3);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background: var(--panel);
      color: var(--ink);
      box-shadow: var(--shadow-2);
      font-size: var(--text-sm);
      font-weight: 400;
      line-height: 1.4;
      text-align: left;
      white-space: normal;
    }
  `,
})
export class InfoHintComponent {
  /** Plain-text hint. Use projected content instead for richer markup. */
  readonly text = input<string>('');
  readonly ariaLabel = input<string>('More information');

  protected readonly hintId = `app-info-hint-${nextInfoHintId++}`;

  private readonly hovered = signal(false);
  private readonly pinned = signal(false);
  protected readonly isOpen = computed(() => this.hovered() || this.pinned());

  private readonly host = inject(ElementRef<HTMLElement>);
  private hideTimeout: ReturnType<typeof setTimeout> | null = null;

  protected show(): void {
    this.clearHideTimeout();
    this.hovered.set(true);
  }

  protected scheduleHide(): void {
    this.clearHideTimeout();
    // Small grace period so moving the pointer from the trigger to the
    // bubble doesn't flicker it closed.
    this.hideTimeout = setTimeout(() => this.hovered.set(false), 120);
  }

  protected toggle(event: Event): void {
    event.stopPropagation();
    this.pinned.update((value) => !value);
  }

  @HostListener('document:click', ['$event'])
  protected onDocumentClick(event: MouseEvent): void {
    if (this.pinned() && !this.host.nativeElement.contains(event.target as Node)) {
      this.pinned.set(false);
    }
  }

  @HostListener('document:keydown.escape')
  protected onEscape(): void {
    this.pinned.set(false);
    this.hovered.set(false);
  }

  private clearHideTimeout(): void {
    if (this.hideTimeout !== null) {
      clearTimeout(this.hideTimeout);
      this.hideTimeout = null;
    }
  }
}
