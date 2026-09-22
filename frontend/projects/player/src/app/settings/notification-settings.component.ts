import {
  ChangeDetectionStrategy,
  Component,
  computed,
  inject,
  signal,
} from '@angular/core';
import { DatePipe } from '@angular/common';

import {
  GameApiService,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiSpinnerComponent,
} from 'shared';

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
  imports: [DatePipe, UiAlertComponent, UiButtonComponent, UiCardComponent, UiChipComponent, UiSpinnerComponent],
  template: `
    <div class="settings-page">
      <h1 class="tr-h1 settings-page__title">Notifications</h1>

      @if (!pushAvailableForSession()) {
        <ui-alert tone="info" [withIcon]="true">
          Push notifications are not enabled for your current game.
        </ui-alert>
      }
      @if (!push.supported) {
        <ui-alert tone="warning" [withIcon]="true">
          This browser does not support push notifications.
        </ui-alert>
      }
      @if (errorMessage(); as msg) {
        <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
      }
      @if (infoMessage(); as msg) {
        <ui-alert tone="success" [withIcon]="true">{{ msg }}</ui-alert>
      }

      <ui-card class="settings-page__master">
        <div class="settings-page__master-row">
          <div class="settings-page__master-copy">
            <span class="tr-h3">Push notifications</span>
            <p class="tr-body">
              Get notified when a tower is stolen, conquered, or a bonus appears — even with the
              app closed. Requires your explicit permission and can be turned off any time.
            </p>
          </div>
          @if (busy()) {
            <ui-spinner [size]="20" />
          } @else if (subscribed()) {
            <ui-button variant="secondary" size="sm" (pressed)="disable()">Turn off</ui-button>
          } @else {
            <ui-button
              variant="primary"
              size="sm"
              [disabled]="!push.supported"
              (pressed)="enable()"
            >
              Turn on
            </ui-button>
          }
        </div>
      </ui-card>

      @if (preferences(); as prefs) {
        <ui-card title="Notify me about" class="settings-page__prefs">
          @for (item of eventToggles; track item.key) {
            <label class="settings-page__toggle-row">
              <span class="tr-body">{{ item.label }}</span>
              <span class="settings-page__switch">
                <input
                  type="checkbox"
                  role="switch"
                  class="settings-page__switch-input"
                  [checked]="prefs[item.key]"
                  [disabled]="busy()"
                  (change)="toggle(item.key, $event)"
                />
                <span class="settings-page__switch-track"></span>
                <span class="settings-page__switch-knob"></span>
              </span>
            </label>
          }
        </ui-card>
      }

      @if (subscriptions().length > 0) {
        <ui-card title="Devices" class="settings-page__subs">
          @for (sub of subscriptions(); track sub.id) {
            <div class="settings-page__sub-row">
              <ui-chip tone="slate">{{ sub.kind }}</ui-chip>
              <span class="tr-meta-tiny settings-page__sub-date">
                since {{ sub.created_at | date: 'mediumDate' }}
              </span>
              @if (!sub.active) {
                <ui-chip tone="neutral">Inactive</ui-chip>
              }
            </div>
          }
        </ui-card>
      }
    </div>
  `,
  styles: `
    :host {
      display: block;
    }
    .settings-page {
      box-sizing: border-box;
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
      padding: var(--spacing-xl) var(--spacing-xl) var(--spacing-2xl);
      max-width: 480px;
      margin: 0 auto;
    }
    .settings-page__title {
      color: var(--color-text-primary);
    }
    .settings-page__master-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-md);
    }
    .settings-page__master-copy {
      display: flex;
      min-width: 0;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .settings-page__prefs {
      display: flex;
      flex-direction: column;
    }
    .settings-page__toggle-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--spacing-sm);
      min-height: var(--tap-min);
      padding-block: var(--spacing-2xs);
      cursor: pointer;
    }
    .settings-page__switch {
      position: relative;
      display: inline-flex;
      flex-shrink: 0;
      width: 44px;
      height: 24px;
    }
    .settings-page__switch-input {
      position: absolute;
      width: 1px;
      height: 1px;
      padding: 0;
      margin: -1px;
      overflow: hidden;
      clip: rect(0, 0, 0, 0);
      white-space: nowrap;
      border: 0;
    }
    .settings-page__switch-track {
      position: absolute;
      inset: 0;
      border-radius: var(--radius-full);
      background: var(--color-bg-inset);
      transition: background 0.2s ease;
    }
    .settings-page__switch-knob {
      position: absolute;
      top: 2px;
      left: 2px;
      width: 20px;
      height: 20px;
      border-radius: 50%;
      background: var(--color-bg-raised);
      box-shadow: var(--elevation-card);
      transition: transform 0.2s ease;
    }
    .settings-page__switch-input:checked ~ .settings-page__switch-track {
      background: var(--color-brand-primary);
    }
    .settings-page__switch-input:checked ~ .settings-page__switch-knob {
      transform: translateX(20px);
    }
    .settings-page__switch-input:focus-visible ~ .settings-page__switch-track {
      outline: 2px solid var(--color-brand-primary);
      outline-offset: 2px;
    }
    .settings-page__subs {
      display: flex;
      flex-direction: column;
    }
    .settings-page__sub-row {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      min-height: var(--tap-min);
    }
    .settings-page__sub-date {
      flex: 1;
      color: var(--color-text-muted);
    }
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
