import { ChangeDetectionStrategy, Component, inject } from '@angular/core';

import { ToastMessage, ToastService } from './toast.service';

/**
 * `ui-toast-outlet` — renders queued `ToastService` messages stacked above
 * the bottom nav (docs/design-system.md §5). Mount once near the shell root.
 */
@Component({
  selector: 'ui-toast-outlet',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'ui-toast-outlet' },
  template: `
    @for (toast of toasts(); track toast.id) {
      <div class="ui-toast tr-body" role="status" [attr.data-tone]="toast.tone">
        <span class="ui-toast__message">{{ toast.message }}</span>
        @if (toast.actionLabel) {
          <button
            type="button"
            class="ui-toast__action tr-button-label"
            (click)="handleAction(toast)"
          >
            {{ toast.actionLabel }}
          </button>
        }
      </div>
    }
  `,
  styles: `
    :host {
      position: fixed;
      right: var(--spacing-md);
      bottom: calc(78px + var(--safe-bottom) + 12px);
      left: var(--spacing-md);
      z-index: 40;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-xs);
      pointer-events: none;
    }
    .ui-toast {
      box-sizing: border-box;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
      padding: var(--spacing-sm) var(--spacing-md);
      border-radius: var(--radius-lg);
      border: 1px solid var(--color-border-subtle);
      border-left: 3px solid var(--color-text-muted);
      background: var(--color-bg-raised);
      box-shadow: var(--elevation-card);
      color: var(--color-text-primary);
      pointer-events: auto;
    }
    .ui-toast[data-tone='brand'] {
      border-left-color: var(--color-brand-primary);
    }
    .ui-toast[data-tone='success'] {
      border-left-color: var(--color-success);
    }
    .ui-toast[data-tone='danger'] {
      border-left-color: var(--color-danger);
    }
    .ui-toast__action {
      flex-shrink: 0;
      border: none;
      background: transparent;
      color: var(--color-brand-onSurface);
      cursor: pointer;
    }
  `,
})
export class UiToastOutletComponent {
  private readonly service = inject(ToastService);
  readonly toasts = this.service.toasts;

  handleAction(toast: ToastMessage): void {
    toast.onAction?.();
    this.service.dismiss(toast.id);
  }
}
