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

import { GameApiService, TowerState } from 'shared';

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
  imports: [RouterLink],
  template: `
    <div class="row justify-content-center">
      <div class="col-md-8 col-lg-6">
        <a routerLink="/" class="small text-body-secondary">&larr; Back to map</a>

        @if (loadError(); as msg) {
          <div class="alert alert-danger mt-3">{{ msg }}</div>
        } @else if (state(); as s) {
          <h1 class="h3 mt-2 mb-1">{{ s.name }}</h1>
          @if (s.ownership; as o) {
            <div class="mb-3">
              <span class="badge" [style.background-color]="o.team_color">
                Held by {{ o.team_name }}
              </span>
              @if (s.has_initial_bonus) {
                <span class="badge text-bg-success ms-1">Initial bonus</span>
              }
            </div>
          } @else {
            <div class="mb-3">
              <span class="badge text-bg-secondary">Unclaimed</span>
              @if (s.has_initial_bonus) {
                <span class="badge text-bg-success ms-1">Initial bonus</span>
              }
            </div>
          }

          <div class="card mb-3">
            <div class="card-body">
              <div class="d-flex justify-content-between align-items-start">
                <div>
                  <div class="small text-body-secondary">Your distance</div>
                  <div class="fs-4 fw-semibold">
                    @if (distanceMeters(); as d) {
                      {{ formatDistance(d) }}
                    } @else if (locationError()) {
                      <span class="text-danger fs-6">{{ locationError() }}</span>
                    } @else {
                      <span class="text-body-secondary fs-6">Locating…</span>
                    }
                  </div>
                </div>
                <div class="text-end">
                  <div class="small text-body-secondary">Required</div>
                  <div class="fs-5">within {{ s.proximity_meters }} m</div>
                </div>
              </div>
              @if (distanceMeters() !== null) {
                @if (withinRange()) {
                  <div class="small text-success mt-2">
                    <i class="bi bi-check-circle"></i> In range
                  </div>
                } @else {
                  <div class="small text-warning mt-2">
                    <i class="bi bi-exclamation-triangle"></i>
                    Move closer to submit a challenge.
                  </div>
                }
              }
            </div>
          </div>

          @if (s.tower_lock_mode === 'LOCK_ON_INITIATE') {
            @if (activeLock(); as lock) {
              @if (lock.held_by_us) {
                <div class="alert alert-success d-flex justify-content-between align-items-center gap-2">
                  <div>
                    <div class="fw-semibold">
                      <i class="bi bi-lock-fill"></i> Tower locked to your team
                    </div>
                    <div class="small">
                      Finish within
                      <strong>{{ formatCountdown(lockRemaining()) }}</strong>.
                    </div>
                  </div>
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-secondary"
                    [disabled]="releasing()"
                    (click)="releaseLock()"
                  >
                    @if (releasing()) {
                      <span class="spinner-border spinner-border-sm me-1"></span>
                    }
                    Give up lock
                  </button>
                </div>
              } @else {
                <div class="alert alert-warning">
                  <div class="fw-semibold">
                    <i class="bi bi-lock-fill"></i>
                    Locked by
                    <span class="badge" [style.background-color]="lock.team_color">
                      {{ lock.team_name }}
                    </span>
                  </div>
                  <div class="small">
                    Free again in
                    <strong>{{ formatCountdown(lockRemaining()) }}</strong>
                    unless they finish first.
                  </div>
                </div>
              }
            }
            @if (lockError(); as msg) {
              <div class="alert alert-danger py-2">{{ msg }}</div>
            }
          }

          @if (cooloffRemaining() > 0) {
            <div class="alert alert-warning">
              <div class="fw-semibold">Cooloff in effect</div>
              <div class="small">
                You can try again in
                <strong>{{ formatCountdown(cooloffRemaining()) }}</strong>.
              </div>
            </div>
          } @else if (s.pending_submission) {
            <div class="alert alert-info">
              A submission is already pending review.
            </div>
          } @else if (s.next_challenge; as c) {
            <div class="card mb-3">
              <div class="card-body">
                <div class="small text-body-secondary mb-1">
                  Next challenge · difficulty {{ c.difficulty }}
                </div>
                <div class="fs-5" style="white-space: pre-line">{{ c.text }}</div>
                @if (c.role_requirement; as req) {
                  <hr class="my-2" />
                  <div class="small text-body-secondary mb-1">
                    @if (req.mode === 'ALL') {
                      Requires one holder for <strong>each</strong> role:
                    } @else {
                      Requires <strong>at least one</strong> of the roles:
                    }
                  </div>
                  <div class="mb-1">
                    @for (role of req.required_roles; track role.slug) {
                      <span
                        class="badge me-1"
                        [class.text-bg-success]="!req.missing_roles.includes(role.slug)"
                        [class.text-bg-danger]="req.missing_roles.includes(role.slug)"
                      >
                        {{ role.name }}
                      </span>
                    }
                  </div>
                  @if (req.team_satisfies) {
                    <div class="small text-success">
                      <i class="bi bi-check-circle"></i>
                      Your team covers the required roles.
                    </div>
                  } @else {
                    <div class="small text-danger">
                      <i class="bi bi-exclamation-triangle"></i>
                      Your team is missing: {{ req.missing_roles.join(', ') }}.
                      Ask staff to assign the role, then try again.
                    </div>
                  }
                }
              </div>
            </div>

            @if (mustInitiate()) {
              <button
                type="button"
                class="btn btn-primary w-100"
                [disabled]="initiating() || activeLock() !== null"
                (click)="initiate()"
              >
                @if (initiating()) {
                  <span class="spinner-border spinner-border-sm me-2"></span>
                }
                <i class="bi bi-lock"></i> Start challenge (lock this tower)
              </button>
              @if (activeLock() !== null) {
                <div class="small text-body-secondary text-center mt-1">
                  Wait for the current lock to expire or be released.
                </div>
              }
            } @else {
              <div class="mb-3">
                <label class="form-label" for="photo">Photo (optional)</label>
                <input
                  id="photo"
                  type="file"
                  class="form-control"
                  accept="image/*"
                  capture="environment"
                  (change)="onPhotoSelected($event)"
                />
                @if (photoName(); as n) {
                  <div class="small text-body-secondary mt-1">Selected: {{ n }}</div>
                }
              </div>

              @if (submitError(); as msg) {
                <div class="alert alert-danger py-2">{{ msg }}</div>
              }
              @if (submitSuccess()) {
                <div class="alert alert-success py-2">
                  Submission received. Staff will review it shortly.
                </div>
              }

              <button
                type="button"
                class="btn btn-primary w-100"
                [disabled]="!canSubmit()"
                (click)="submit()"
              >
                @if (submitting()) {
                  <span class="spinner-border spinner-border-sm me-2"></span>
                }
                Submit challenge
              </button>
            }
          } @else {
            <div class="alert alert-secondary">No challenges available for this tower.</div>
          }
        } @else {
          <div class="d-flex align-items-center text-body-secondary mt-4">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading tower…
          </div>
        }
      </div>
    </div>
  `,
})
export class TowerDetailComponent implements OnInit {
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);
  private readonly api = inject(GameApiService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly state = signal<TowerState | null>(null);
  protected readonly loadError = signal<string | null>(null);
  protected readonly position = signal<Position | null>(null);
  protected readonly locationError = signal<string | null>(null);
  protected readonly now = signal<number>(Date.now());
  protected readonly photoDataUrl = signal<string | null>(null);
  protected readonly photoName = signal<string | null>(null);
  protected readonly submitting = signal(false);
  protected readonly submitError = signal<string | null>(null);
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
      !!s &&
      s.tower_lock_mode === 'LOCK_ON_INITIATE' &&
      !(this.activeLock()?.held_by_us ?? false)
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
      !this.submitting()
    );
  });

  private watchId: number | null = null;
  private tickHandle: ReturnType<typeof setInterval> | null = null;

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    if (!id) {
      this.loadError.set('Invalid tower.');
      return;
    }
    this.fetchState(id);
    this.startGeolocation();
    this.tickHandle = setInterval(() => this.now.set(Date.now()), 1000);
    this.destroyRef.onDestroy(() => {
      if (this.watchId !== null) {
        navigator.geolocation.clearWatch(this.watchId);
      }
      if (this.tickHandle) {
        clearInterval(this.tickHandle);
      }
    });
  }

  private fetchState(id: number): void {
    this.api.towerState(id).subscribe({
      next: (s) => this.state.set(s),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  private startGeolocation(): void {
    if (!('geolocation' in navigator)) {
      this.locationError.set('Geolocation is not available.');
      return;
    }
    this.watchId = navigator.geolocation.watchPosition(
      (pos) => {
        this.locationError.set(null);
        this.position.set({
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: pos.coords.accuracy,
        });
      },
      (err) => {
        this.locationError.set(err.message || 'Could not determine your location.');
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

  protected submit(): void {
    const s = this.state();
    const pos = this.position();
    if (!s || !s.next_challenge || !pos || !this.canSubmit()) {
      return;
    }
    this.submitting.set(true);
    this.submitError.set(null);
    this.submitSuccess.set(false);

    this.api
      .submitChallenge({
        tower: s.id,
        challenge: s.next_challenge.id,
        lat: pos.lat,
        lng: pos.lng,
        photo: this.photoDataUrl() ?? undefined,
      })
      .subscribe({
        next: () => {
          this.submitting.set(false);
          this.submitSuccess.set(true);
          this.photoDataUrl.set(null);
          this.photoName.set(null);
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
}

function haversineMeters(
  lat1: number,
  lng1: number,
  lat2: number,
  lng2: number,
): number {
  const R = 6_371_000;
  const toRad = (d: number) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}
