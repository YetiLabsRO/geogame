import {
  ApplicationRef,
  EnvironmentInjector,
  Injectable,
  createComponent,
  inject,
} from '@angular/core';

import { ConfirmDialogComponent, ConfirmOptions } from './confirm-dialog.component';

/**
 * Themed replacement for the native `confirm()`. Self-mounting: nothing
 * needs to be added to an app's template — calling `confirm()` creates a
 * `ConfirmDialogComponent`, attaches it directly to `document.body`, and
 * tears it down again once the user answers. Safe to call from anywhere
 * `inject()`/DI is available (components, other services, guards).
 *
 * ```ts
 * private readonly confirmService = inject(ConfirmService);
 *
 * async delete(): Promise<void> {
 *   const ok = await this.confirmService.confirm({
 *     title: 'Delete team?',
 *     message: 'This removes the team and all its members. This cannot be undone.',
 *     danger: true,
 *     requireTyping: team.name,
 *   });
 *   if (ok) { ... }
 * }
 * ```
 */
@Injectable({ providedIn: 'root' })
export class ConfirmService {
  private readonly appRef = inject(ApplicationRef);
  private readonly environmentInjector = inject(EnvironmentInjector);

  confirm(options: ConfirmOptions): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      const hostElement = document.createElement('div');
      document.body.appendChild(hostElement);

      const componentRef = createComponent(ConfirmDialogComponent, {
        environmentInjector: this.environmentInjector,
        hostElement,
      });
      componentRef.setInput('options', options);

      const subscription = componentRef.instance.closed.subscribe((result: boolean) => {
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
