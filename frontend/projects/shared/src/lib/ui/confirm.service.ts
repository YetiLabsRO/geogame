import {
  ApplicationRef,
  EnvironmentInjector,
  Injectable,
  createComponent,
  inject,
} from '@angular/core';

import {
  ConfirmDialogComponent,
  ConfirmOptions,
  DialogResult,
} from './confirm-dialog.component';

/** A confirm's options — everything but the prompt-only fields. */
export type ConfirmDialogOptions = Omit<
  ConfirmOptions,
  'mode' | 'promptLabel' | 'initialValue' | 'placeholder'
>;

/** An alert states something; there is nothing to decline. */
export type AlertDialogOptions = Omit<
  ConfirmOptions,
  'mode' | 'cancelLabel' | 'requireTyping' | 'promptLabel' | 'initialValue' | 'placeholder'
>;

/** A prompt asks for a line of text. */
export type PromptDialogOptions = Omit<ConfirmOptions, 'mode' | 'requireTyping'>;

/**
 * The app's own dialogs, replacing the browser's `confirm`, `alert` and
 * `prompt`. Self-mounting: nothing needs to be added to an app's template —
 * calling one of these creates a `ConfirmDialogComponent`, attaches it to
 * `document.body`, and tears it down once the person answers. Safe to call
 * from anywhere `inject()`/DI is available.
 *
 * ```ts
 * private readonly dialogs = inject(DialogService);
 *
 * async delete(): Promise<void> {
 *   const ok = await this.dialogs.confirm({
 *     title: 'Delete team?',
 *     message: 'This removes the team and all its members. This cannot be undone.',
 *     danger: true,
 *     requireTyping: team.name,
 *   });
 *   if (ok) { ... }
 * }
 * ```
 *
 * A `danger: true` dialog is announced as an `alertdialog`; the rest as a
 * `dialog`. See `ConfirmDialogComponent` for the keyboard contract.
 */
@Injectable({ providedIn: 'root' })
export class DialogService {
  private readonly appRef = inject(ApplicationRef);
  private readonly environmentInjector = inject(EnvironmentInjector);

  /** Ask a yes/no question. Resolves true when confirmed. */
  confirm(options: ConfirmDialogOptions): Promise<boolean> {
    return this.open({ ...options, mode: 'confirm' }) as Promise<boolean>;
  }

  /**
   * State something the person must acknowledge. Resolves when they do —
   * there is no "no" to give, so nothing branches on the result.
   */
  alert(options: AlertDialogOptions): Promise<void> {
    return this.open({ ...options, mode: 'alert' }).then(() => undefined);
  }

  /** Ask for a line of text. Resolves the text, or null if cancelled. */
  prompt(options: PromptDialogOptions): Promise<string | null> {
    return this.open({ ...options, mode: 'prompt' }) as Promise<string | null>;
  }

  private open(options: ConfirmOptions): Promise<DialogResult> {
    return new Promise<DialogResult>((resolve) => {
      const hostElement = document.createElement('div');
      document.body.appendChild(hostElement);

      const componentRef = createComponent(ConfirmDialogComponent, {
        environmentInjector: this.environmentInjector,
        hostElement,
      });
      componentRef.setInput('options', options);

      const subscription = componentRef.instance.closed.subscribe((result: DialogResult) => {
        subscription.unsubscribe();
        this.appRef.detachView(componentRef.hostView);
        componentRef.destroy();
        hostElement.remove();
        resolve(result);
      });

      this.appRef.attachView(componentRef.hostView);
    });
  }
}

/**
 * @deprecated Use `DialogService`, which answers all three kinds of
 * question. Kept so existing `confirm()` callers keep working; new code
 * should inject `DialogService`.
 */
@Injectable({ providedIn: 'root' })
export class ConfirmService extends DialogService {}
