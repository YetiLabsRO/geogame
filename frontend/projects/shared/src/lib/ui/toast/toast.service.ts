import { Injectable, signal } from '@angular/core';

export type ToastTone = 'brand' | 'success' | 'danger' | 'neutral';

export interface ToastOptions {
  tone?: ToastTone;
  /** ms before auto-dismiss; 0 disables auto-dismiss. Default 4000. */
  duration?: number;
  actionLabel?: string;
  onAction?: () => void;
}

export interface ToastMessage {
  id: number;
  message: string;
  tone: ToastTone;
  duration: number;
  actionLabel?: string;
  onAction?: () => void;
}

let nextToastId = 0;

/**
 * `ToastService` — queues toasts for `ui-toast-outlet` to render
 * (docs/design-system.md §5). Injectable anywhere; the player shell mounts
 * one outlet near the root.
 */
@Injectable({ providedIn: 'root' })
export class ToastService {
  private readonly _toasts = signal<ToastMessage[]>([]);
  readonly toasts = this._toasts.asReadonly();

  show(message: string, options: ToastOptions = {}): number {
    const id = nextToastId++;
    const toast: ToastMessage = {
      id,
      message,
      tone: options.tone ?? 'neutral',
      duration: options.duration ?? 4000,
      actionLabel: options.actionLabel,
      onAction: options.onAction,
    };
    this._toasts.update((toasts) => [...toasts, toast]);
    if (toast.duration > 0) {
      setTimeout(() => this.dismiss(id), toast.duration);
    }
    return id;
  }

  dismiss(id: number): void {
    this._toasts.update((toasts) => toasts.filter((toast) => toast.id !== id));
  }
}
