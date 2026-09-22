import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import {
  ThemeService,
  ThemePreference,
  ToastService,
  UI_ICON_NAMES,
  UiButtonComponent,
  UiChipComponent,
  UiFieldComponent,
  UiInputDirective,
  UiCardComponent,
  UiStatTileComponent,
  UiProgressMeterComponent,
  UiAvatarComponent,
  UiTopAppBarComponent,
  UiBottomNavComponent,
  UiToastOutletComponent,
  UiEmptyStateComponent,
  UiIconComponent,
  UiNavItem,
} from 'shared';

/**
 * Dev-only showcase of every `ui-*` component in every variant, with a
 * theme switcher — mobile-app tasks 3.6/4.1. Registered at `/dev/gallery`
 * only when `!environment.production` (see app.routes.ts).
 */
@Component({
  selector: 'app-gallery',
  standalone: true,
  imports: [
    UiButtonComponent,
    UiChipComponent,
    UiFieldComponent,
    UiInputDirective,
    UiCardComponent,
    UiStatTileComponent,
    UiProgressMeterComponent,
    UiAvatarComponent,
    UiTopAppBarComponent,
    UiBottomNavComponent,
    UiToastOutletComponent,
    UiEmptyStateComponent,
    UiIconComponent,
  ],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <ui-top-app-bar title="Design gallery" />

    <main class="gallery">
      <section class="gallery__section">
        <h2 class="tr-h2">Theme</h2>
        <div class="gallery__row">
          @for (pref of themePreferences; track pref) {
            <ui-button variant="secondary" size="sm" [block]="false" (pressed)="theme.set(pref)">
              {{ pref }}
            </ui-button>
          }
        </div>
        <p class="tr-body">Effective: {{ theme.effective() }}</p>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Icons</h2>
        <div class="gallery__row">
          @for (name of iconNames; track name) {
            <span class="gallery__icon">
              <ui-icon [name]="name" [label]="name" />
            </span>
          }
        </div>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Buttons</h2>
        <div class="gallery__row">
          <ui-button variant="primary" icon="arrow-right">Submit Trial</ui-button>
          <ui-button variant="secondary" icon="lightbulb">Request a hint</ui-button>
          <ui-button variant="tinted">Tinted</ui-button>
          <ui-button variant="primary" size="md">Medium</ui-button>
          <ui-button variant="primary" size="sm">Small</ui-button>
          <ui-button variant="primary" [loading]="true">Loading</ui-button>
          <ui-button variant="primary" [disabled]="true">Disabled</ui-button>
        </div>
        <ui-button variant="primary" [block]="true">Block button</ui-button>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Chips</h2>
        <div class="gallery__row">
          <ui-chip tone="brand">ACTIVE TRIAL</ui-chip>
          <ui-chip tone="solid">Solid</ui-chip>
          <ui-chip tone="slate">Old Town</ui-chip>
          <ui-chip tone="neutral">Neutral</ui-chip>
          <ui-chip icon="star" tone="brand">With icon</ui-chip>
          <ui-chip teamColor="#446279">Blue Falcons</ui-chip>
          <ui-chip teamColor="#a33b2a">Red Wolves</ui-chip>
        </div>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Fields</h2>
        <div class="gallery__stack">
          <ui-field label="Your answer">
            <input uiInput type="text" placeholder="Enter the carved year…" />
          </ui-field>
          <ui-field label="Team name" icon="users" help="Visible to your society">
            <input uiInput type="text" placeholder="The Wanderers" />
          </ui-field>
          <ui-field label="Join code" error="That code doesn't exist.">
            <input uiInput type="text" value="XJ4Q" />
          </ui-field>
          <ui-field label="Notes">
            <textarea uiInput rows="3" placeholder="Anything else?"></textarea>
          </ui-field>
        </div>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Cards</h2>
        <div class="gallery__stack">
          <ui-card eyebrow="Your task" title="The Keeper's Riddle">
            <p class="tr-body-italic">
              "Find the year carved above the archway where the astronomer once watched the stars —
              then subtract the keeper's age."
            </p>
            <div cardActions>
              <ui-button variant="primary" size="sm">Submit</ui-button>
            </div>
          </ui-card>
          <ui-card variant="flat" padding="sm" title="Flat, small padding">
            A flat card with tighter padding.
          </ui-card>
        </div>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Stat tiles</h2>
        <div class="gallery__row">
          <ui-stat-tile icon="clock" label="Time left" value="04:32" />
          <ui-stat-tile icon="star" label="Reward" value="500 XP" />
        </div>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Progress meters</h2>
        <div class="gallery__stack">
          <ui-progress-meter label="Distance to tower" valueLabel="120m" [value]="60" />
          <ui-progress-meter
            label="Team score"
            valueLabel="82%"
            [value]="82"
            tone="team"
            style="--team-color: #446279"
          />
          <ui-progress-meter label="Cooldown" valueLabel="Ready" [value]="100" tone="success" />
          <ui-progress-meter label="Out of range" valueLabel="12%" [value]="12" tone="danger" />
        </div>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Avatars</h2>
        <div class="gallery__row">
          <ui-avatar [size]="32" name="Julian Vance" />
          <ui-avatar [size]="40" name="Julian Vance" />
          <ui-avatar [size]="56" name="Julian Vance" />
          <ui-avatar [size]="56" />
          <ui-avatar [size]="56" name="Blue Falcons" teamColor="#446279" />
        </div>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Empty state</h2>
        <ui-empty-state
          icon="map"
          title="No towers yet"
          description="Explore the map to find your first tower."
        >
          <ui-button variant="primary" size="sm">Open map</ui-button>
        </ui-empty-state>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Toast</h2>
        <div class="gallery__row">
          <ui-button variant="secondary" size="sm" (pressed)="showToast('neutral')"
            >Neutral toast</ui-button
          >
          <ui-button variant="secondary" size="sm" (pressed)="showToast('brand')"
            >Brand toast</ui-button
          >
          <ui-button variant="secondary" size="sm" (pressed)="showToast('success')"
            >Success toast</ui-button
          >
          <ui-button variant="secondary" size="sm" (pressed)="showToast('danger')"
            >Danger toast</ui-button
          >
        </div>
      </section>

      <section class="gallery__section">
        <h2 class="tr-h2">Bottom nav (fake, not fixed)</h2>
        <div class="gallery__nav-frame">
          <ui-bottom-nav [items]="navItems" style="position: static" />
        </div>
      </section>
    </main>

    <ui-toast-outlet />
  `,
  styles: `
    :host {
      display: block;
      padding-bottom: var(--spacing-3xl);
    }
    .gallery {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-2xl);
      padding: var(--spacing-xl);
    }
    .gallery__section {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .gallery__row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: var(--spacing-sm);
    }
    .gallery__stack {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-md);
    }
    .gallery__icon {
      display: flex;
      align-items: center;
      gap: var(--spacing-2xs);
      padding: var(--spacing-xs);
      border-radius: var(--radius-md);
      background: var(--color-bg-surface);
    }
    .gallery__nav-frame {
      position: relative;
      border: 1px solid var(--color-border-subtle);
      border-radius: var(--radius-lg);
      overflow: hidden;
    }
  `,
})
export class GalleryComponent {
  protected readonly theme = inject(ThemeService);
  private readonly toastService = inject(ToastService);

  protected readonly themePreferences: ThemePreference[] = ['system', 'light', 'dark'];
  protected readonly iconNames = UI_ICON_NAMES;

  protected readonly navItems: UiNavItem[] = [
    { label: 'Journey', icon: 'map', route: '/', exact: true },
    { label: 'Society', icon: 'users', route: '/team' },
    { label: 'Chronicle', icon: 'book', route: '/history' },
    { label: 'Ledger', icon: 'id-card', route: '/ledger' },
  ];

  protected showToast(tone: 'brand' | 'success' | 'danger' | 'neutral'): void {
    this.toastService.show(`This is a ${tone} toast`, { tone, actionLabel: 'Dismiss' });
  }
}
