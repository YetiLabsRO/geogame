import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  ViewChild,
  computed,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

let nextConfirmId = 0;

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Renders the confirm button as `btn-danger` for irreversible/destructive actions. */
  danger?: boolean;
  /**
   * When set, the confirm button stays disabled until the user types this
   * exact phrase — for irreversible operations that deserve extra friction.
   */
  requireTyping?: string;
}

/**
 * Themed replacement for the native `confirm()` dialog. Not meant to be used
 * directly — call `ConfirmService.confirm(...)` instead, which mounts one of
 * these as a self-contained overlay and resolves a promise with the result.
 */
@Component({
  selector: 'app-confirm-dialog',
  standalone: true,
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="app-confirm-backdrop" (click)="cancel()"></div>
    <div
      #panel
      class="app-confirm-panel"
      role="alertdialog"
      aria-modal="true"
      [attr.aria-labelledby]="titleId"
      [attr.aria-describedby]="messageId"
      tabindex="-1"
      (keydown.escape)="cancel()"
    >
      <h2 class="app-confirm-panel__title" [id]="titleId">{{ options().title }}</h2>
      <p class="app-confirm-panel__message" [id]="messageId">{{ options().message }}</p>

      @if (options().requireTyping; as phrase) {
        <div class="app-confirm-panel__typing">
          <label [for]="typingId">Type "{{ phrase }}" to confirm</label>
          <input
            [id]="typingId"
            type="text"
            class="form-control"
            autocomplete="off"
            spellcheck="false"
            [ngModel]="typedValue()"
            (ngModelChange)="typedValue.set($event)"
          />
        </div>
      }

      <div class="app-confirm-panel__actions">
        <button type="button" class="btn btn-outline-secondary" (click)="cancel()">
          {{ options().cancelLabel ?? 'Cancel' }}
        </button>
        <button
          type="button"
          class="btn"
          [class.btn-danger]="options().danger"
          [class.btn-primary]="!options().danger"
          [disabled]="!canConfirm()"
          (click)="confirm()"
        >
          {{ options().confirmLabel ?? 'Confirm' }}
        </button>
      </div>
    </div>
  `,
  styles: `
    :host {
      position: fixed;
      inset: 0;
      z-index: 1090;
      display: flex;
      align-items: center;
      justify-content: center;
    }

    .app-confirm-backdrop {
      position: absolute;
      inset: 0;
      background: rgba(16, 21, 26, 0.55);
    }

    .app-confirm-panel {
      position: relative;
      width: min(28rem, calc(100vw - var(--space-6)));
      max-height: calc(100vh - var(--space-6));
      overflow-y: auto;
      padding: var(--space-5);
      border-radius: var(--radius-lg);
      background: var(--panel);
      color: var(--ink);
      box-shadow: var(--shadow-3);
    }

    .app-confirm-panel__title {
      margin: 0 0 var(--space-2);
      font-size: var(--text-lg);
    }

    .app-confirm-panel__message {
      margin: 0 0 var(--space-4);
      color: var(--ink-muted);
      white-space: pre-line;
    }

    .app-confirm-panel__typing {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
      margin-bottom: var(--space-4);
      font-size: var(--text-sm);
    }

    .app-confirm-panel__actions {
      display: flex;
      justify-content: flex-end;
      gap: var(--space-2);
    }
  `,
})
export class ConfirmDialogComponent implements AfterViewInit {
  readonly options = input.required<ConfirmOptions>();
  readonly closed = output<boolean>();

  protected readonly titleId = `app-confirm-title-${nextConfirmId}`;
  protected readonly messageId = `app-confirm-message-${nextConfirmId}`;
  protected readonly typingId = `app-confirm-typing-${nextConfirmId++}`;

  protected readonly typedValue = signal('');
  protected readonly canConfirm = computed(() => {
    const phrase = this.options().requireTyping;
    return !phrase || this.typedValue() === phrase;
  });

  @ViewChild('panel') private readonly panelRef?: ElementRef<HTMLElement>;

  ngAfterViewInit(): void {
    this.panelRef?.nativeElement.focus();
  }

  protected cancel(): void {
    this.closed.emit(false);
  }

  protected confirm(): void {
    if (this.canConfirm()) {
      this.closed.emit(true);
    }
  }
}
