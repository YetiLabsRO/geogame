import {
  AfterViewInit,
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  computed,
  input,
  output,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';

let nextDialogId = 0;

/** Which question the dialog is asking. */
export type DialogMode = 'confirm' | 'alert' | 'prompt';

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
  /**
   * `confirm` (default) asks yes/no, `alert` states something with a single
   * acknowledging control, `prompt` asks for a line of text. Set by the
   * `DialogService` method you call rather than by hand.
   */
  mode?: DialogMode;
  /** `prompt` only — the label above the input. */
  promptLabel?: string;
  /** `prompt` only — the value the input starts with. */
  initialValue?: string;
  /** `prompt` only — placeholder text. */
  placeholder?: string;
}

/** What a dialog resolves to: a yes/no, or the prompt's text (null on cancel). */
export type DialogResult = boolean | string | null;

/** Focusable descendants, for the tab trap. */
const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), ' +
  'textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The app's own dialog, replacing the browser's `confirm`, `alert` and
 * `prompt`. Not meant to be used directly — call `DialogService` instead,
 * which mounts one of these as a self-contained overlay and resolves a
 * promise with the answer.
 *
 * Semantics: `role="alertdialog"` when the dialog announces a destructive
 * or irreversible action and `role="dialog"` otherwise, labelled by its own
 * title and described by its own message. Focus moves in on open, is held
 * inside while open, and returns to whatever had it before. Escape and the
 * backdrop both cancel.
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
      [attr.role]="options().danger ? 'alertdialog' : 'dialog'"
      aria-modal="true"
      [attr.aria-labelledby]="titleId"
      [attr.aria-describedby]="messageId"
      tabindex="-1"
      (keydown.escape)="cancel()"
      (keydown.tab)="trapTab($any($event))"
    >
      <h2 class="app-confirm-panel__title" [id]="titleId">{{ options().title }}</h2>
      <p class="app-confirm-panel__message" [id]="messageId">{{ options().message }}</p>

      @if (mode() === 'prompt') {
        <div class="app-confirm-panel__field">
          <label [for]="inputId">{{ options().promptLabel ?? 'Your answer' }}</label>
          <input
            #promptInput
            [id]="inputId"
            type="text"
            class="form-control"
            autocomplete="off"
            [placeholder]="options().placeholder ?? ''"
            [ngModel]="promptValue()"
            (ngModelChange)="promptValue.set($event)"
            (keydown.enter)="confirm()"
          />
        </div>
      }

      @if (options().requireTyping; as phrase) {
        <div class="app-confirm-panel__field">
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
        @if (mode() !== 'alert') {
          <button type="button" class="btn btn-outline-secondary" (click)="cancel()">
            {{ options().cancelLabel ?? 'Cancel' }}
          </button>
        }
        <button
          type="button"
          class="btn"
          [class.btn-danger]="options().danger"
          [class.btn-primary]="!options().danger"
          [disabled]="!canConfirm()"
          (click)="confirm()"
        >
          {{ options().confirmLabel ?? defaultConfirmLabel() }}
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

    .app-confirm-panel__field {
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
export class ConfirmDialogComponent implements AfterViewInit, OnDestroy {
  readonly options = input.required<ConfirmOptions>();
  readonly closed = output<DialogResult>();

  protected readonly titleId = `app-confirm-title-${nextDialogId}`;
  protected readonly messageId = `app-confirm-message-${nextDialogId}`;
  protected readonly typingId = `app-confirm-typing-${nextDialogId}`;
  protected readonly inputId = `app-confirm-input-${nextDialogId++}`;

  protected readonly typedValue = signal('');
  protected readonly promptValue = signal('');

  protected readonly mode = computed<DialogMode>(() => this.options().mode ?? 'confirm');

  protected readonly canConfirm = computed(() => {
    const phrase = this.options().requireTyping;
    return !phrase || this.typedValue() === phrase;
  });

  protected readonly defaultConfirmLabel = computed(() =>
    this.mode() === 'alert' ? 'OK' : 'Confirm',
  );

  @ViewChild('panel') private readonly panelRef?: ElementRef<HTMLElement>;
  @ViewChild('promptInput') private readonly promptRef?: ElementRef<HTMLInputElement>;

  /** Whatever had focus before we took it, so we can give it back. */
  private readonly previouslyFocused = document.activeElement as HTMLElement | null;
  /** The page's own overflow, restored on close. */
  private readonly previousOverflow = document.body.style.overflow;

  ngAfterViewInit(): void {
    // The page behind must not scroll under an open dialog.
    document.body.style.overflow = 'hidden';
    this.promptValue.set(this.options().initialValue ?? '');
    // A prompt is asking for the text, so focus where it is typed.
    const target = this.promptRef?.nativeElement ?? this.panelRef?.nativeElement;
    target?.focus();
  }

  ngOnDestroy(): void {
    document.body.style.overflow = this.previousOverflow;
    this.previouslyFocused?.focus?.();
  }

  /** Hold Tab inside the panel — a modal the keyboard can leave is not one. */
  protected trapTab(event: KeyboardEvent): void {
    const panel = this.panelRef?.nativeElement;
    if (!panel) return;
    const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
      (el) => el.offsetParent !== null || el === document.activeElement,
    );
    if (focusable.length === 0) {
      event.preventDefault();
      panel.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === panel)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  protected cancel(): void {
    // A cancelled prompt answers null, not an empty string — "" is a
    // thing the person could have typed.
    this.closed.emit(this.mode() === 'prompt' ? null : false);
  }

  protected confirm(): void {
    if (!this.canConfirm()) return;
    this.closed.emit(this.mode() === 'prompt' ? this.promptValue() : true);
  }
}
