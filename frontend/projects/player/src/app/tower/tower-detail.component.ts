import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';

import {
  GameApiService,
  GeolocationService,
  HapticsService,
  TowerState,
  UiAlertComponent,
  UiButtonComponent,
  UiCardComponent,
  UiChipComponent,
  UiEmptyStateComponent,
  UiFieldComponent,
  UiIconComponent,
  UiInputDirective,
  UiProgressMeterComponent,
  UiSpinnerComponent,
  UiStatTileComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

interface Position {
  lat: number;
  lng: number;
  accuracy: number;
}

@Component({
  selector: 'app-tower-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    RouterLink,
    UiAlertComponent,
    UiButtonComponent,
    UiCardComponent,
    UiChipComponent,
    UiEmptyStateComponent,
    UiFieldComponent,
    UiIconComponent,
    UiInputDirective,
    UiProgressMeterComponent,
    UiSpinnerComponent,
    UiStatTileComponent,
  ],
  template: `
    @if (loadError(); as msg) {
      <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
    } @else if (state(); as s) {
      <!-- Tower hero (docs/design-system.md §6) -->
      <div class="tower-hero">
        <div class="tower-hero__chips">
          @if (s.ownership; as o) {
            <ui-chip [teamColor]="o.team_color">Held by {{ o.team_name }}</ui-chip>
          } @else {
            <ui-chip tone="neutral">Unclaimed</ui-chip>
          }
          @if (s.has_initial_bonus) {
            <ui-chip tone="solid" icon="star">Bonus</ui-chip>
          }
        </div>
        <ui-icon class="tower-hero__watermark" name="castle" [size]="150" />
        <h2 class="tower-hero__name tr-h2">{{ s.name }}</h2>
      </div>

      <!-- Title block -->
      <div class="tower-title">
        <span class="tr-eyebrow">
          DIFFICULTY {{ s.next_challenge?.difficulty ?? '—' }} · {{ typeLabel() }}
          @if (isAuto()) {
            · INSTANT VALIDATION
          }
        </span>
        <h1 class="tr-h1">{{ typeLabel() }} Challenge</h1>
      </div>

      <!-- Meta stats -->
      <div class="tower-stats">
        <ui-stat-tile icon="target" label="Distance">
          @if (distanceMeters(); as d) {
            {{ formatDistance(d) }}
          } @else if (locationError()) {
            {{ locationError() }}
          } @else {
            Locating…
          }
        </ui-stat-tile>
        @if (cooloffRemaining() > 0) {
          <ui-stat-tile
            icon="clock"
            label="Cooldown"
            [value]="formatCountdown(cooloffRemaining())"
          />
        } @else if (s.next_challenge; as statsChallenge) {
          <ui-stat-tile icon="star" label="Difficulty" [value]="statsChallenge.difficulty" />
        } @else {
          <ui-stat-tile icon="star" label="Required range" [value]="s.proximity_meters + ' m'" />
        }
      </div>

      @if (distanceMeters(); as d) {
        <ui-progress-meter
          label="Distance"
          [valueLabel]="formatDistance(d) + ' / ' + s.proximity_meters + ' m'"
          [value]="s.proximity_meters"
          [max]="proximityMeterMax(d, s.proximity_meters)"
          [tone]="withinRange() ? 'success' : 'danger'"
        />
      }

      @if (s.tower_lock_mode === 'LOCK_ON_INITIATE') {
        @if (activeLock(); as lock) {
          @if (lock.held_by_us) {
            <ui-alert tone="success" [withIcon]="true">
              <strong>Tower locked to your team.</strong>
              Finish within {{ formatCountdown(lockRemaining()) }}.
            </ui-alert>
            <ui-button
              variant="secondary"
              size="sm"
              [loading]="releasing()"
              (pressed)="releaseLock()"
            >
              Give up lock
            </ui-button>
          } @else {
            <ui-alert tone="warning" [withIcon]="true">
              Locked by <strong>{{ lock.team_name }}</strong
              >. Free again in {{ formatCountdown(lockRemaining()) }} unless they finish first.
            </ui-alert>
          }
        }
        @if (lockError(); as msg) {
          <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
        }
      }

      @if (cooloffRemaining() > 0) {
        <ui-alert tone="warning" [withIcon]="true">
          <strong>Cooloff in effect.</strong> You can try again in
          {{ formatCountdown(cooloffRemaining()) }}.
        </ui-alert>
      } @else if (s.pending_submission) {
        <ui-alert tone="info" [withIcon]="true">A submission is already pending review.</ui-alert>
      } @else if (s.challenge_hidden) {
        <!-- tower-visibility (challenge axis): HIDDEN_UNTIL_ARRIVAL — the
             server withholds the challenge until we report a position
             inside the activation area. -->
        <ui-empty-state
          icon="target"
          title="Challenge hidden until arrival"
          [description]="'Get within ' + s.proximity_meters + ' m of the tower to reveal it.'"
        />
      } @else if (s.next_challenge; as c) {
        <ui-card>
          <div class="tower-task-row">
            <span class="tr-eyebrow">YOUR TASK</span>
            <ui-icon name="sparkle" [size]="18" />
          </div>
          <p class="tr-body-italic">&ldquo;{{ c.text }}&rdquo;</p>

          @if (s.presence; as p) {
            <div class="tower-divider"></div>
            <span class="tr-field-label">Presence requirement</span>
            <div class="tower-chip-row">
              @if (p.method === 'PHOTO') {
                <ui-chip tone="brand">Photo of {{ p.required_members }} member(s) required</ui-chip>
              } @else {
                <ui-chip [tone]="p.present_members >= p.required_members ? 'brand' : 'neutral'">
                  {{ p.present_members }} / {{ p.required_members }} members present
                </ui-chip>
                @if (p.window_seconds > 0) {
                  <ui-chip tone="slate">
                    hold {{ p.window_seconds }}s inside {{ p.geofence_radius_meters }} m
                  </ui-chip>
                }
              }
            </div>
            @if (p.method !== 'PHOTO' && p.present_members < p.required_members) {
              <ui-alert tone="danger" [withIcon]="true">
                Gather {{ p.required_members - p.present_members }} more teammate(s) within
                {{ p.geofence_radius_meters }} m of the tower (live location must be on).
              </ui-alert>
            }
            @if (p.photo_fallback_offered) {
              <p class="tr-body tower-muted">
                Alternatively, attach a photo showing the {{ p.required_members }} required
                member(s) — staff will review it manually.
              </p>
            }
          }

          @if (c.role_requirement; as req) {
            <div class="tower-divider"></div>
            <span class="tr-field-label">
              @if (req.mode === 'ALL') {
                Required roles (all)
              } @else {
                Required roles (any)
              }
            </span>
            <div class="tower-chip-row">
              @for (role of req.required_roles; track role.slug) {
                <ui-chip [tone]="req.missing_roles.includes(role.slug) ? 'neutral' : 'brand'">
                  {{ role.name }}
                </ui-chip>
              }
            </div>
            @if (req.team_satisfies) {
              <p class="tr-body tower-success">Your team covers the required roles.</p>
            } @else {
              <ui-alert tone="danger" [withIcon]="true">
                Your team is missing: {{ req.missing_roles.join(', ') }}. Ask staff to assign the
                role, then try again.
              </ui-alert>
            }
          }
        </ui-card>

        @if (mustInitiate()) {
          <!-- tower-locking: LOCK_ON_INITIATE — claim the tower before submitting -->
          <ui-button
            variant="primary"
            [block]="true"
            icon="key"
            [disabled]="initiating() || activeLock() !== null"
            [loading]="initiating()"
            (pressed)="initiate()"
          >
            Start challenge (lock this tower)
          </ui-button>
          @if (activeLock() !== null) {
            <p class="tr-body tower-muted tower-centered">
              Wait for the current lock to expire or be released.
            </p>
          }
        } @else {
          <!-- challenge-type-system: per-type submission inputs -->
          @if (needsCode()) {
            <ui-field
              label="YOUR ANSWER"
              icon="key"
              help="Get the code at the location (QR / NFC handout), then paste or type it here. It is checked instantly."
            >
              <input
                uiInput
                type="text"
                placeholder="Scan or paste the code"
                autocomplete="off"
                [value]="codeValue()"
                (input)="onCodeInput($event)"
              />
            </ui-field>
            <ui-button variant="secondary" [block]="true" icon="target" routerLink="/scan">
              Scan tag
            </ui-button>
          } @else {
            <div class="tower-photo-field">
              <label class="tower-photo-trigger" for="photo">
                <ui-icon name="camera" [size]="20" />
                <span class="tr-button-label">
                  @if (photoName()) {
                    Change photo
                  } @else if (needsPhoto()) {
                    Take photo (required)
                  } @else {
                    Take photo (optional)
                  }
                </span>
              </label>
              <input
                id="photo"
                type="file"
                accept="image/*"
                capture="environment"
                (change)="onPhotoSelected($event)"
                hidden
              />
              @if (photoDataUrl(); as url) {
                <img class="tower-photo-preview" [src]="url" alt="Selected photo preview" />
              }
            </div>
          }

          @if (submitError(); as msg) {
            <ui-alert tone="danger" [withIcon]="true">{{ msg }}</ui-alert>
          }
          @if (submitOutcome() === 1) {
            <ui-alert tone="success" [withIcon]="true">Code accepted — tower captured!</ui-alert>
          } @else if (submitOutcome() === 2) {
            <ui-alert tone="danger" [withIcon]="true">
              Code rejected. Check the code and try again after the cooloff.
            </ui-alert>
          } @else if (submitOutcome() === 0) {
            <ui-alert tone="success" [withIcon]="true">
              Submission received. Staff will review it shortly.
            </ui-alert>
          }

          <ui-button
            variant="primary"
            [block]="true"
            icon="arrow-right"
            [disabled]="!canSubmit()"
            [loading]="submitting()"
            (pressed)="submit()"
          >
            {{ needsCode() ? 'Validate code' : 'Submit Trial' }}
          </ui-button>
        }
      } @else {
        <ui-empty-state
          icon="castle"
          title="No challenges available"
          description="There is nothing to solve at this tower right now."
        />
      }
    } @else {
      <div class="tower-loading">
        <ui-spinner />
        <span class="tr-body">Loading tower…</span>
      </div>
    }
  `,
  styles: `
    :host {
      display: block;
    }
    .tower-loading {
      display: flex;
      align-items: center;
      gap: var(--spacing-sm);
      color: var(--color-text-secondary);
    }
    .tower-hero {
      position: relative;
      display: flex;
      height: 180px;
      overflow: hidden;
      border-radius: var(--radius-lg);
      padding: var(--spacing-md);
      background: linear-gradient(142deg, #f3ece0 0%, #e7cca3 37%, #c99e73 67%);
    }
    :host-context(:root[data-theme='dark']) .tower-hero {
      background: linear-gradient(142deg, var(--color-bg-inset) 0%, #3a2a20 100%);
    }
    @media (prefers-color-scheme: dark) {
      :host-context(:root:not([data-theme='light'])) .tower-hero {
        background: linear-gradient(142deg, var(--color-bg-inset) 0%, #3a2a20 100%);
      }
    }
    .tower-hero__chips {
      position: relative;
      z-index: 1;
      display: flex;
      align-self: flex-start;
      gap: var(--spacing-2xs);
    }
    .tower-hero__watermark {
      position: absolute;
      right: -20px;
      bottom: -20px;
      color: var(--color-brand-deep);
      opacity: 0.18;
    }
    .tower-hero__name {
      position: relative;
      z-index: 1;
      align-self: flex-end;
      margin-left: auto;
      max-width: 60%;
      text-align: right;
      overflow-wrap: anywhere;
      color: var(--color-text-primary);
    }
    .tower-title {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-2xs);
    }
    .tower-title .tr-eyebrow {
      color: var(--color-brand-onSurface);
    }
    .tower-stats {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: var(--spacing-sm);
    }
    .tower-task-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--color-brand-onSurface);
    }
    .tower-divider {
      height: 1px;
      margin: var(--spacing-2xs) 0;
      background: var(--color-border-subtle);
    }
    .tower-chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--spacing-2xs);
    }
    .tower-muted {
      color: var(--color-text-secondary);
    }
    .tower-success {
      color: var(--color-success);
    }
    .tower-centered {
      text-align: center;
    }
    .tower-photo-field {
      display: flex;
      flex-direction: column;
      gap: var(--spacing-sm);
    }
    .tower-photo-trigger {
      display: flex;
      min-height: var(--tap-min);
      align-items: center;
      justify-content: center;
      gap: var(--spacing-xs);
      border-radius: var(--radius-xl);
      background: var(--color-brand-tint);
      border: 1px solid var(--color-border-brand);
      color: var(--color-brand-onSurface);
      cursor: pointer;
    }
    .tower-photo-preview {
      width: 100%;
      max-height: 220px;
      border-radius: var(--radius-lg);
      object-fit: cover;
    }
  `,
})
export class TowerDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(GameApiService);
  private readonly geolocation = inject(GeolocationService);
  private readonly haptics = inject(HapticsService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly state = signal<TowerState | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly position = signal<Position | null>(null);
  protected readonly locationError = signal<string | null>(null);
  protected readonly now = signal<number>(Date.now());
  protected readonly photoDataUrl = signal<string | null>(null);
  protected readonly photoName = signal<string | null>(null);
  protected readonly codeValue = signal('');
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);
  /** Outcome of the last submission (0 pending / 1 confirmed / 2 rejected). */
  protected readonly submitOutcome = signal<number | null>(null);

  // challenge-type-system: what the current challenge's type requires.
  protected readonly requiredPayload = computed(
    () => this.state()?.next_challenge?.required_payload ?? [],
  );
  protected readonly needsCode = computed(() => this.requiredPayload().includes('submitted_code'));
  protected readonly needsPhoto = computed(() => this.requiredPayload().includes('photo'));
  protected readonly isAuto = computed(
    () => this.state()?.next_challenge?.effective_review_mode === 'AUTO',
  );
  protected readonly typeLabel = computed(() => {
    switch (this.state()?.next_challenge?.type) {
      case 'PHOTO':
        return 'Photo';
      case 'NFC_QR':
        return 'QR / NFC code';
      case 'RFID':
        return 'RFID tag';
      default:
        return 'Question';
    }
  });

  // tower-locking: initiate/lock flow state.
  protected readonly submitSuccess = signal(false);
  protected readonly initiating = signal(false);
  protected readonly releasing = signal(false);
  protected readonly lockError = signal<string | null>(null);

  protected readonly distanceMeters = computed(() => {
    const pos = this.position();
    const s = this.state();
    if (!pos || !s) return null;
    const [lng, lat] = s.location.coordinates;
    return haversineMeters(pos.lat, pos.lng, lat, lng);
  });

  protected readonly withinRange = computed(() => {
    const d = this.distanceMeters();
    const s = this.state();
    return d !== null && s !== null && d <= s.proximity_meters;
  });

  protected readonly cooloffRemaining = computed(() => {
    const until = this.state()?.cooloff_until;
    if (!until) return 0;
    const ms = new Date(until).getTime() - this.now();
    return Math.max(0, Math.ceil(ms / 1000));
  });

  /**
   * Seconds until the reported lock's finish deadline (0 when free or
   * lapsed) — client-side mirror of the backend's lazy expiry.
   */
  protected readonly lockRemaining = computed(() => {
    const lock = this.state()?.lock;
    if (!lock) return 0;
    const ms = new Date(lock.expires_at).getTime() - this.now();
    return Math.max(0, Math.ceil(ms / 1000));
  });

  /** The still-active lock, or null once it lapses client-side. */
  protected readonly activeLock = computed(() => {
    const lock = this.state()?.lock ?? null;
    return lock && this.lockRemaining() > 0 ? lock : null;
  });

  /**
   * Under LOCK_ON_INITIATE the finish affordance only appears while our
   * team holds the active lock; otherwise the player must initiate first.
   */
  protected readonly mustInitiate = computed(() => {
    const s = this.state();
    return (
      !!s && s.tower_lock_mode === 'LOCK_ON_INITIATE' && !(this.activeLock()?.held_by_us ?? false)
    );
  });

  protected readonly canSubmit = computed(() => {
    const s = this.state();
    return (
      !!s &&
      !!s.next_challenge &&
      !s.pending_submission &&
      this.cooloffRemaining() === 0 &&
      this.withinRange() &&
      !this.mustInitiate() &&
      !this.submitting() &&
      // Per-type payload requirements (challenge-type-system).
      (!this.needsCode() || this.codeValue().trim().length > 0) &&
      (!this.needsPhoto() || this.photoDataUrl() !== null)
    );
  });

  private watchId: string | null = null;
  private tickHandle: ReturnType<typeof setInterval> | null = null;
  private presenceHandle: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    if (!id) {
      this.loadError.set('Invalid tower.');
      return;
    }
    this.fetchState(id);
    this.startGeolocation();
    this.tickHandle = setInterval(() => this.now.set(Date.now()), 1000);
    // presence-rules: the required-vs-present count updates as
    // teammates enter/leave the geofence — refresh the state
    // periodically while a presence requirement applies.
    this.presenceHandle = setInterval(() => {
      if (this.state()?.presence) {
        this.fetchState(id);
      }
    }, 10_000);
    this.destroyRef.onDestroy(() => {
      if (this.watchId !== null) {
        this.geolocation.clearWatch(this.watchId);
      }
      if (this.tickHandle) {
        clearInterval(this.tickHandle);
      }
      if (this.presenceHandle) {
        clearInterval(this.presenceHandle);
      }
    });
  }

  private fetchState(id: number): void {
    // Pass the current position so a HIDDEN_UNTIL_ARRIVAL challenge is
    // revealed by the server the moment we are inside the activation
    // area (tower-visibility, challenge axis).
    const pos = this.position();
    this.api.towerState(id, pos ? { lat: pos.lat, lng: pos.lng } : undefined).subscribe({
      next: (s) => this.state.set(s),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  private startGeolocation(): void {
    this.watchId = this.geolocation.watch(
      (pos) => {
        this.locationError.set(null);
        this.position.set({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
        // Concealed challenge + now in range → ask the server again
        // with our position; it reveals inside the activation area.
        const s = this.state();
        if (s?.challenge_hidden && this.withinRange()) {
          this.fetchState(s.id);
        }
      },
      (err) => {
        const message = err instanceof Error ? err.message : undefined;
        this.locationError.set(message || 'Could not determine your location.');
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 10000 },
    );
  }

  /** INITIATE lifecycle phase: commit to the challenge and lock the tower. */
  protected initiate(): void {
    const s = this.state();
    if (!s || this.initiating()) return;
    this.initiating.set(true);
    this.lockError.set(null);
    this.api.initiateTower(s.id).subscribe({
      next: () => {
        this.initiating.set(false);
        this.fetchState(s.id);
      },
      error: (err) => {
        this.initiating.set(false);
        this.lockError.set(extractErrorMessage(err));
        // A 409 means another team beat us to it — refresh to show their lock.
        this.fetchState(s.id);
      },
    });
  }

  /** Voluntarily give up our active lock (CANCELLED) before the deadline. */
  protected releaseLock(): void {
    const s = this.state();
    if (!s || this.releasing()) return;
    this.releasing.set(true);
    this.lockError.set(null);
    this.api.releaseTowerLock(s.id).subscribe({
      next: () => {
        this.releasing.set(false);
        this.fetchState(s.id);
      },
      error: (err) => {
        this.releasing.set(false);
        this.lockError.set(extractErrorMessage(err));
        this.fetchState(s.id);
      },
    });
  }

  protected onPhotoSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) {
      this.photoDataUrl.set(null);
      this.photoName.set(null);
      return;
    }
    this.photoName.set(file.name);
    const reader = new FileReader();
    reader.onload = () => {
      this.photoDataUrl.set(typeof reader.result === 'string' ? reader.result : null);
    };
    reader.onerror = () => {
      this.photoDataUrl.set(null);
      this.submitError.set('Could not read the selected photo.');
    };
    reader.readAsDataURL(file);
  }

  protected onCodeInput(event: Event): void {
    this.codeValue.set((event.target as HTMLInputElement).value);
  }

  protected submit(): void {
    const s = this.state();
    const pos = this.position();
    if (!s || !s.next_challenge || !pos || !this.canSubmit()) {
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    this.submitOutcome.set(null);

    this.api
      .submitChallenge({
        tower: s.id,
        challenge: s.next_challenge.id,
        lat: pos.lat,
        lng: pos.lng,
        photo: this.photoDataUrl() ?? undefined,
        submitted_code: this.needsCode() ? this.codeValue().trim() : undefined,
      })
      .subscribe({
        next: (created) => {
          this.submitting.set(false);
          // AUTO types resolve immediately — surface the outcome now;
          // MANUAL types come back PENDING (0) as before.
          this.submitOutcome.set(created.outcome);
          if (created.outcome === 1) {
            this.haptics.notify('success');
          }
          this.photoDataUrl.set(null);
          this.photoName.set(null);
          this.codeValue.set('');
          this.fetchState(s.id);
        },
        error: (err) => {
          this.submitting.set(false);
          this.submitError.set(extractErrorMessage(err));
        },
      });
  }

  protected formatDistance(m: number): string {
    if (m < 1000) return `${Math.round(m)} m`;
    return `${(m / 1000).toFixed(2)} km`;
  }

  protected formatCountdown(seconds: number): string {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  /** Presentation-only: keeps the distance `ui-progress-meter` fill between
   *  0 (far away) and 100% (at or inside the proximity threshold). */
  protected proximityMeterMax(distance: number, proximity: number): number {
    return Math.max(distance, proximity);
  }
}

function haversineMeters(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
