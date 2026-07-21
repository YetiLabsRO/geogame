import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';

import { GameApiService } from 'shared';

import { extractErrorMessage } from '../auth/form-error';
import {
  NotificationPreferences,
  PushService,
  PushSubscriptionInfo,
} from './push.service';

/**
 * Notification settings (realtime-and-notifications, 6.1): explicit
 * opt-in consent toggle for push notifications plus per-event toggles.
 */
@Component({
  selector: 'app-notification-settings',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="row justify-content-center">
      <div class="col-lg-6">
        <h1 class="h3 mb-3">Notification settings</h1>

        @if (!pushAvailableForSession()) {
          <div class="alert alert-info">
            Push notifications are not enabled for your current game.
          </div>
        }
        @if (!push.supported) {
          <div class="alert alert-warning">
            This browser does not support push notifications.
          </div>
        }
        @if (errorMessage(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }
        @if (infoMessage(); as msg) {
          <div class="alert alert-success">{{ msg }}</div>
        }

        <div class="card mb-3">
          <div class="card-body">
            <div class="d-flex justify-content-between align-items-center">
              <div>
                <div class="fw-semibold">Push notifications</div>
                <div class="small text-body-secondary">
                  Get notified when a tower is stolen, conquered, or a
                  bonus appears — even with the app closed. Requires your
                  explicit permission and can be turned off any time.
                </div>
              </div>
              @if (busy()) {
                <span class="spinner-border spinner-border-sm"></span>
              } @else if (subscribed()) {
                <button
                  type="button"
                  class="btn btn-sm btn-outline-danger"
                  (click)="disable()"
                >
                  Turn off
                </button>
              } @else {
                <button
                  type="button"
                  class="btn btn-sm btn-primary"
                  [disabled]="!push.supported"
                  (click)="enable()"
                >
                  Turn on
                </button>
              }
            </div>
          </div>
        </div>

        @if (preferences(); as prefs) {
          <div class="card">
            <div class="card-header">Notify me about</div>
            <div class="card-body">
              @for (item of eventToggles; track item.key) {
                <div class="form-check form-switch mb-2">
                  <input
                    class="form-check-input"
                    type="checkbox"
                    role="switch"
                    [id]="'toggle-' + item.key"
                    [checked]="prefs[item.key]"
                    [disabled]="busy()"
                    (change)="toggle(item.key, $event)"
                  />
                  <label class="form-check-label" [for]="'toggle-' + item.key">
                    {{ item.label }}
                  </label>
                </div>
              }
            </div>
          </div>
        }
      </div>
    </div>
  `,
})
export class NotificationSettingsComponent {
  private readonly api = inject(GameApiService);
  protected readonly push = inject(PushService);

  protected readonly subscriptions = signal<PushSubscriptionInfo[]>([]);
  protected readonly preferences = signal<NotificationPreferences | null>(null);
  protected readonly busy = signal(false);
  protected readonly errorMessage = signal<string | null>(null);
  protected readonly infoMessage = signal<string | null>(null);
  protected readonly pushAvailableForSession = signal(true);

  protected readonly subscribed = computed(
    () => this.subscriptions().some((s) => s.active),
  );

  protected readonly eventToggles: {
    key: 'notify_steal' | 'notify_conquer' | 'notify_bonus';
    label: string;
  }[] = [
    { key: 'notify_steal', label: 'A tower is stolen' },
    { key: 'notify_conquer', label: 'A tower is conquered' },
    { key: 'notify_bonus', label: 'A bonus appears' },
  ];

  constructor() {
    this.push.subscriptions().subscribe({
      next: (list) => this.subscriptions.set(list),
      error: () => {},
    });
    this.push.preferences().subscribe({
      next: (prefs) => this.preferences.set(prefs),
      error: (err) => this.errorMessage.set(extractErrorMessage(err)),
    });
    this.api.currentSession().subscribe({
      next: (session) =>
        this.pushAvailableForSession.set(session.push_notifications_enabled),
      error: () => {}, // no current session — leave the settings usable
    });
  }

  protected async enable(): Promise<void> {
    this.busy.set(true);
    this.errorMessage.set(null);
    this.infoMessage.set(null);
    try {
      await this.push.enable();
      this.infoMessage.set('Push notifications are on for this device.');
      this.reloadSubscriptions();
    } catch (err) {
      this.errorMessage.set(
        err instanceof Error ? err.message : 'Could not enable push notifications.',
      );
    } finally {
      this.busy.set(false);
    }
  }

  protected async disable(): Promise<void> {
    this.busy.set(true);
    this.errorMessage.set(null);
    this.infoMessage.set(null);
    try {
      await this.push.disable();
      this.infoMessage.set('Push notifications are off.');
      this.reloadSubscriptions();
    } catch (err) {
      this.errorMessage.set(
        err instanceof Error ? err.message : 'Could not disable push notifications.',
      );
    } finally {
      this.busy.set(false);
    }
  }

  protected toggle(
    key: 'notify_steal' | 'notify_conquer' | 'notify_bonus',
    event: Event,
  ): void {
    const checked = (event.target as HTMLInputElement).checked;
    this.push.updatePreferences({ [key]: checked }).subscribe({
      next: (prefs) => this.preferences.set(prefs),
      error: (err) => this.errorMessage.set(extractErrorMessage(err)),
    });
  }

  private reloadSubscriptions(): void {
    this.push.subscriptions().subscribe({
      next: (list) => this.subscriptions.set(list),
      error: () => {},
    });
  }
}
