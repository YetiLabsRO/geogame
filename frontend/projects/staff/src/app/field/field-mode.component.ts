import {
  afterNextRender,
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import * as L from 'leaflet';

import {
  AdminChallenge,
  AdminCollection,
  AdminGame,
  AdminTower,
  AdminTowerType,
  AdminZone,
  FieldSyncService,
  StaffApiService,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/** One GPS reading feeding the multi-reading average. */
interface Fix {
  lat: number;
  lng: number;
  accuracy: number;
}

/** The tower photos/challenges attach to: a server id or a queued localId. */
interface TowerContext {
  ref: number | string;
  name: string;
}

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const ACCURACY_WARN_M = 15;
/** Untyped paint — mirrors game/models.py's DEFAULT_TOWER_* constants. */
const DEFAULT_TOWER_ICON = 'bi-geo-alt-fill';
const DEFAULT_TOWER_COLOR = '#5F6B7A';
const PHOTO_MAX_DIM = 1280;
const PHOTO_JPEG_QUALITY = 0.75;

/**
 * Field authoring mode (field-authoring-mode tasks 3.1–3.6, 4.2).
 *
 * Mobile, one-handed on-site authoring: drop a tower at the device GPS
 * fix (live accuracy, re-read / averaging / nudge), attach compressed
 * camera photos, walk or tap a zone boundary, attach a challenge — all
 * filed into a target Collection, drafts by default, queued offline.
 */
@Component({
  selector: 'app-field-mode',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule],
  template: `
    <!-- Top bar: collection switcher + draft toggle + sync state -->
    <div class="d-flex flex-wrap align-items-center gap-2 mb-2">
      <h1 class="h5 mb-0 me-auto">Field mode</h1>
      @if (queue.online()) {
        <span class="badge text-bg-success">online</span>
      } @else {
        <span class="badge text-bg-warning">offline</span>
      }
      @if (queue.pendingCount() > 0 || queue.failedCount() > 0) {
        <button
          type="button"
          class="btn btn-sm btn-outline-primary"
          [disabled]="queue.syncing() || !queue.online()"
          (click)="syncNow()"
        >
          @if (queue.syncing()) {
            <span class="spinner-border spinner-border-sm me-1"></span>
          }
          Sync
          <span class="badge text-bg-secondary ms-1">{{ queue.pendingCount() }}</span>
          @if (queue.failedCount() > 0) {
            <span class="badge text-bg-danger ms-1">{{ queue.failedCount() }}</span>
          }
        </button>
      }
    </div>

    <div class="row g-2 align-items-center mb-2">
      <div class="col-8">
        <select
          class="form-select"
          [ngModel]="collectionId()"
          (ngModelChange)="onCollectionChange($event)"
        >
          <option [ngValue]="null">— target collection —</option>
          @for (c of collections(); track c.id) {
            <option [ngValue]="c.id">{{ c.name }}</option>
          }
        </select>
      </div>
      <div class="col-4">
        <div class="form-check form-switch">
          <input
            id="draft-toggle"
            type="checkbox"
            class="form-check-input"
            role="switch"
            [ngModel]="draft()"
            (ngModelChange)="draft.set($event)"
          />
          <label class="form-check-label" for="draft-toggle">Draft</label>
        </div>
      </div>
    </div>

    @if (notice(); as msg) {
      <div class="alert alert-success py-2 mb-2">{{ msg }}</div>
    }
    @if (error(); as msg) {
      <div class="alert alert-danger py-2 mb-2">{{ msg }}</div>
    }

    <!-- Map -->
    <div class="map-shell mb-2">
      <div class="map" #mapContainer></div>

      <!-- Placement crosshair. The point stays fixed at the centre of
           the screen and the MAP moves under it: the target becomes the
           whole map instead of a 20px marker, and the thing being
           positioned is never under the thumb doing the positioning. -->
      @if (mode() === 'tower') {
        <div class="placement-crosshair" aria-hidden="true">
          <span class="ring"></span>
          <span class="dot"></span>
        </div>
        <div class="offset-chip" role="status">
          @if (offsetMeters(); as d) {
            <i class="bi bi-arrows-move"></i> {{ d.toFixed(0) }} m from you
            <button type="button" class="btn btn-link btn-sm p-0 ms-2" (click)="centreOnMe()">
              centre on me
            </button>
          } @else {
            <i class="bi bi-person-fill"></i> at your position
          }
        </div>
      }

      @if (fix(); as f) {
        <div
          class="gps-chip"
          [class.text-bg-danger]="f.accuracy > accuracyWarnM"
          [class.text-bg-light]="f.accuracy <= accuracyWarnM"
        >
          <i class="bi bi-crosshair"></i>
          ±{{ f.accuracy.toFixed(0) }} m
          @if (mode() === 'tower' && readings().length > 1) {
            · avg of {{ readings().length }}
          }
        </div>
      }
    </div>

    <!-- Idle: the two big entry actions -->
    @if (mode() === 'idle') {
      <div class="d-grid gap-2">
        <button type="button" class="btn btn-primary btn-lg" (click)="startTower()">
          <i class="bi bi-geo-alt-fill me-1"></i> Drop tower here
        </button>
        <div class="row g-2">
          <div class="col-6">
            <button
              type="button"
              class="btn btn-outline-primary btn-lg w-100"
              (click)="startZone(null)"
            >
              <i class="bi bi-bounding-box me-1"></i> New zone
            </button>
          </div>
          <div class="col-6">
            <select
              class="form-select form-select-lg h-100"
              [ngModel]="null"
              (ngModelChange)="startZone($event)"
            >
              <option [ngValue]="null">Adjust zone…</option>
              @for (z of zones(); track z.id) {
                <option [ngValue]="z">{{ z.name }}</option>
              }
            </select>
          </div>
        </div>
        @if (currentTower(); as t) {
          <div class="card">
            <div class="card-body py-2">
              <div class="d-flex align-items-center gap-2 flex-wrap">
                <span class="me-auto">
                  <i class="bi bi-geo-alt"></i> {{ t.name }}
                  @if (isQueuedRef(t.ref)) {
                    <span class="badge text-bg-warning ms-1">queued</span>
                  }
                  @if (photoCount() > 0) {
                    <span class="badge text-bg-light border ms-1">
                      {{ photoCount() }} <i class="bi bi-camera"></i>
                    </span>
                  }
                </span>
                <button
                  type="button"
                  class="btn btn-outline-secondary"
                  [disabled]="uploadingPhoto()"
                  (click)="photoInput.click()"
                >
                  @if (uploadingPhoto()) {
                    <span class="spinner-border spinner-border-sm me-1"></span>
                  } @else {
                    <i class="bi bi-camera me-1"></i>
                  }
                  Photo
                </button>
                <button
                  type="button"
                  class="btn btn-outline-secondary"
                  (click)="openChallengeSheet()"
                >
                  <i class="bi bi-list-task me-1"></i> Challenge
                </button>
              </div>
            </div>
          </div>
        }
      </div>
    }

    <!-- Tower capture panel -->
    @if (mode() === 'tower') {
      <div class="card">
        <div class="card-body d-grid gap-2">
          @if (reading()) {
            <div class="text-body-secondary">
              <span class="spinner-border spinner-border-sm me-2"></span>
              Reading GPS…
            </div>
          }
          @if (fix(); as f) {
            @if (f.accuracy > accuracyWarnM) {
              <div class="alert alert-warning py-2 mb-0">
                Accuracy ±{{ f.accuracy.toFixed(0) }} m is poor — add readings to
                average, or nudge the marker on the map.
              </div>
            }
          }
          <input
            class="form-control form-control-lg"
            type="text"
            placeholder="Tower name"
            [ngModel]="towerName()"
            (ngModelChange)="towerName.set($event)"
          />

          <!-- tower-types: one tap styles and configures the capture. -->
          @if (towerTypes().length) {
            <div class="type-chips" role="group" aria-label="Tower type">
              @for (t of towerTypes(); track t.id) {
                <button
                  type="button"
                  class="type-chip"
                  [class.selected]="typeId() === t.id"
                  [attr.aria-pressed]="typeId() === t.id"
                  (click)="chooseType(t.id)"
                >
                  <span class="chip-dot" [style.background-color]="t.color">
                    <i class="bi" [class]="t.icon"></i>
                  </span>
                  {{ t.name }}
                </button>
              }
            </div>
            <div class="form-text mt-0">
              @if (selectedType(); as t) {
                {{ t.name }} ·
                {{
                  impliedRadius() === null
                    ? 'capture radius from the game'
                    : 'capture radius ' + impliedRadius() + ' m'
                }}
              } @else {
                No type — neutral styling and the game's capture radius.
              }
            </div>
            @if (radiusBelowAccuracy()) {
              <div class="alert alert-warning py-2 mb-0">
                This type captures within {{ impliedRadius() }} m but the fix is only
                accurate to ±{{ fix()?.accuracy?.toFixed(0) }} m — players may not be able
                to reach it. Add readings or nudge the marker before saving.
              </div>
            }
          }
          <div class="row g-2">
            <div class="col-6">
              <button
                type="button"
                class="btn btn-outline-secondary btn-lg w-100"
                [disabled]="reading()"
                (click)="reRead()"
              >
                <i class="bi bi-arrow-repeat me-1"></i> Re-read
              </button>
            </div>
            <div class="col-6">
              <button
                type="button"
                class="btn btn-outline-secondary btn-lg w-100"
                [disabled]="reading()"
                (click)="addReading()"
              >
                <i class="bi bi-plus-circle me-1"></i> Add reading
              </button>
            </div>
          </div>
          <div class="row g-2">
            <div class="col-6">
              <button
                type="button"
                class="btn btn-outline-danger btn-lg w-100"
                (click)="cancelCapture()"
              >
                Cancel
              </button>
            </div>
            <div class="col-6">
              <button
                type="button"
                class="btn btn-primary btn-lg w-100"
                [disabled]="saving() || !towerName().trim() || !towerPos()"
                (click)="saveTower()"
              >
                @if (saving()) {
                  <span class="spinner-border spinner-border-sm me-1"></span>
                }
                Save tower
              </button>
            </div>
          </div>
          <div class="form-text">
            Pan the map to place the crosshair. Saved {{ draft() ? 'as inactive draft' : 'active' }}.
          </div>
        </div>
      </div>
    }

    <!-- Zone drawing panel -->
    @if (mode() === 'zone') {
      <div class="card">
        <div class="card-body d-grid gap-2">
          @if (!editingZone()) {
            <input
              class="form-control form-control-lg"
              type="text"
              placeholder="Zone name"
              [ngModel]="zoneName()"
              (ngModelChange)="zoneName.set($event)"
            />
          } @else {
            <div class="fw-semibold">Adjusting: {{ editingZone()!.name }}</div>
          }
          <div class="text-body-secondary">
            {{ vertices().length }} vertices — mark at your GPS position while
            walking, or tap the map. Drag a vertex to correct it.
          </div>
          <div class="row g-2">
            <div class="col-6">
              <button
                type="button"
                class="btn btn-outline-primary btn-lg w-100"
                [disabled]="reading()"
                (click)="markHere()"
              >
                <i class="bi bi-geo me-1"></i> Mark here
              </button>
            </div>
            <div class="col-6">
              <button
                type="button"
                class="btn btn-outline-secondary btn-lg w-100"
                [disabled]="vertices().length === 0"
                (click)="undoVertex()"
              >
                <i class="bi bi-arrow-counterclockwise me-1"></i> Undo
              </button>
            </div>
          </div>
          <div class="row g-2">
            <div class="col-6">
              <button
                type="button"
                class="btn btn-outline-danger btn-lg w-100"
                (click)="cancelCapture()"
              >
                Cancel
              </button>
            </div>
            <div class="col-6">
              <button
                type="button"
                class="btn btn-primary btn-lg w-100"
                [disabled]="saving() || vertices().length < 3 || (!editingZone() && !zoneName().trim())"
                (click)="saveZone()"
              >
                @if (saving()) {
                  <span class="spinner-border spinner-border-sm me-1"></span>
                }
                {{ editingZone() ? 'Save boundary' : 'Save zone' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    }

    <!-- Failed / queued sync items (task 4.2) -->
    @if (queue.items().length > 0) {
      <div class="card mt-2">
        <div class="card-header py-2">
          Pending sync
          <span class="badge text-bg-secondary">{{ queue.pendingCount() }}</span>
          @if (queue.failedCount() > 0) {
            <span class="badge text-bg-danger">{{ queue.failedCount() }} failed</span>
          }
        </div>
        <ul class="list-group list-group-flush">
          @for (item of queue.items(); track item.localId) {
            <li class="list-group-item py-2">
              <div class="d-flex align-items-center gap-2">
                <span class="me-auto">
                  {{ describeEdit(item.kind) }}
                  @if (item.payload['name']; as name) {
                    · {{ name }}
                  }
                  @if (item.status === 'failed') {
                    <span class="badge text-bg-danger ms-1">failed</span>
                  }
                </span>
                @if (item.status === 'failed') {
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-primary"
                    (click)="queue.retry(item.localId)"
                  >
                    Retry
                  </button>
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-danger"
                    (click)="queue.discard(item.localId)"
                  >
                    Discard
                  </button>
                }
              </div>
              @if (item.error; as err) {
                <div class="small text-danger mt-1">{{ err }}</div>
              }
            </li>
          }
        </ul>
      </div>
    }

    <!-- Attach-challenge bottom sheet (task 3.5) -->
    @if (sheetOpen()) {
      <div class="sheet-backdrop" (click)="sheetOpen.set(false)"></div>
      <div class="sheet card">
        <div class="card-header d-flex align-items-center">
          <span class="me-auto">Attach challenge — {{ currentTower()?.name }}</span>
          <button
            type="button"
            class="btn-close"
            (click)="sheetOpen.set(false)"
          ></button>
        </div>
        <div class="card-body d-grid gap-2">
          <div class="btn-group w-100">
            <button
              type="button"
              class="btn"
              [class.btn-primary]="challengeTab() === 'existing'"
              [class.btn-outline-primary]="challengeTab() !== 'existing'"
              (click)="challengeTab.set('existing')"
            >
              Existing
            </button>
            <button
              type="button"
              class="btn"
              [class.btn-primary]="challengeTab() === 'new'"
              [class.btn-outline-primary]="challengeTab() !== 'new'"
              (click)="challengeTab.set('new')"
            >
              New
            </button>
          </div>
          @if (challengeTab() === 'existing') {
            <select
              class="form-select form-select-lg"
              [ngModel]="challengeId()"
              (ngModelChange)="challengeId.set($event)"
            >
              <option [ngValue]="null">— pick a challenge —</option>
              @for (c of challenges(); track c.id) {
                <option [ngValue]="c.id">
                  [{{ c.difficulty }}] {{ c.text.slice(0, 60) }}
                </option>
              }
            </select>
          } @else {
            <select
              class="form-select"
              [ngModel]="challengeGameId()"
              (ngModelChange)="challengeGameId.set($event)"
            >
              <option [ngValue]="null">— game (challenge bank) —</option>
              @for (g of games(); track g.id) {
                <option [ngValue]="g.id">{{ g.name }}</option>
              }
            </select>
            <textarea
              class="form-control"
              rows="3"
              placeholder="Challenge text"
              [ngModel]="challengeText()"
              (ngModelChange)="challengeText.set($event)"
            ></textarea>
            <input
              class="form-control"
              type="number"
              min="1"
              placeholder="Difficulty"
              [ngModel]="challengeDifficulty()"
              (ngModelChange)="challengeDifficulty.set($event)"
            />
          }
          <button
            type="button"
            class="btn btn-primary btn-lg"
            [disabled]="saving() || !challengeReady()"
            (click)="saveChallenge()"
          >
            @if (saving()) {
              <span class="spinner-border spinner-border-sm me-1"></span>
            }
            Attach
          </button>
        </div>
      </div>
    }

    <input
      #photoInput
      type="file"
      accept="image/*"
      capture="environment"
      class="d-none"
      (change)="onPhotoPicked($event)"
    />
  `,
  styles: `
    .map-shell {
      position: relative;
    }
    /* tower-types: the chip row is the primary control in this panel,
       so size it for a gloved thumb rather than as a refinement. */
    .type-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 0.375rem;
    }
    .type-chip {
      display: inline-flex;
      align-items: center;
      gap: 0.375rem;
      min-height: 2.5rem;
      padding: 0.375rem 0.625rem;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--panel);
      color: var(--ink);
      font-size: 0.9375rem;
    }
    .type-chip.selected {
      border-color: var(--primary);
      box-shadow: inset 0 0 0 1px var(--primary);
      color: var(--primary-strong);
      font-weight: 600;
    }
    .chip-dot {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1.5rem;
      height: 1.5rem;
      border-radius: 50%;
      color: #fff;
      font-size: 0.8125rem;
      box-shadow: inset 0 0 0 1px rgb(0 0 0 / 25%);
    }
    .map {
      height: 45vh;
      min-height: 16rem;
      width: 100%;
      border-radius: 0.375rem;
    }
    .placement-crosshair {
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      z-index: 900;
      /* Never intercepts a gesture: the map underneath has to keep
         receiving every pan. */
      pointer-events: none;
      width: 44px;
      height: 44px;
    }
    .placement-crosshair .ring {
      position: absolute;
      inset: 0;
      border: 2px solid rgba(255, 255, 255, 0.9);
      border-radius: 50%;
      box-shadow:
        0 0 0 2px rgba(0, 0, 0, 0.45),
        inset 0 0 0 2px rgba(0, 0, 0, 0.45);
    }
    .placement-crosshair .dot {
      position: absolute;
      top: 50%;
      left: 50%;
      width: 6px;
      height: 6px;
      margin: -3px 0 0 -3px;
      border-radius: 50%;
      background: #fff;
      box-shadow: 0 0 0 2px rgba(0, 0, 0, 0.55);
    }
    .offset-chip {
      position: absolute;
      left: 50%;
      bottom: 0.5rem;
      transform: translateX(-50%);
      z-index: 1000;
      display: flex;
      align-items: center;
      white-space: nowrap;
      border: 1px solid rgba(0, 0, 0, 0.15);
      border-radius: 999px;
      padding: 0.25rem 0.75rem;
      font-size: 0.875rem;
      background: var(--panel);
      color: var(--ink);
      box-shadow: var(--shadow-2);
    }
    .gps-chip {
      position: absolute;
      top: 0.5rem;
      right: 0.5rem;
      z-index: 1000;
      border: 1px solid rgba(0, 0, 0, 0.15);
      border-radius: 999px;
      padding: 0.25rem 0.75rem;
      font-size: 0.9rem;
      font-weight: 600;
    }
    .sheet-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.4);
      z-index: 1040;
    }
    .sheet {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: 1050;
      border-radius: 0.75rem 0.75rem 0 0;
      max-height: 75vh;
      overflow-y: auto;
    }
  `,
})
export class FieldModeComponent {
  private readonly api = inject(StaffApiService);
  protected readonly queue = inject(FieldSyncService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly accuracyWarnM = ACCURACY_WARN_M;
  protected readonly mapContainer =
    viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');

  // Mode + capture state
  protected readonly mode = signal<'idle' | 'tower' | 'zone'>('idle');
  protected readonly collections = signal<AdminCollection[]>([]);
  /**
   * What the target Collection already holds, drawn on the field map.
   *
   * Without it the map had no memory: it drew where you are and what
   * you are making, and nothing you had ever made — so a curator could
   * stand beside a tower they added last month and record it again.
   */
  protected readonly existingTowers = signal<AdminTower[]>([]);
  protected readonly existingZones = signal<AdminZone[]>([]);
  protected readonly collectionId = signal<number | null>(null);
  protected readonly draft = signal(true);
  protected readonly notice = signal<string | null>(null);
  protected readonly error = signal<string | null>(null);
  protected readonly saving = signal(false);

  // Geolocation
  protected readonly reading = signal(false);
  protected readonly readings = signal<Fix[]>([]);
  private readonly nudge = signal<{ lat: number; lng: number } | null>(null);
  /** Displayed fix: the running average of this capture's readings. */
  protected readonly fix = computed<Fix | null>(() => average(this.readings()));
  /** Where the crosshair currently sits — the live map centre. */
  private readonly mapCentre = signal<{ lat: number; lng: number } | null>(null);
  /**
   * Position that will be saved.
   *
   * In tower mode that is the crosshair, full stop: pin, crosshair and
   * saved point are one thing, so no two of them can disagree about
   * where the tower goes. `nudge` survives only as the marker-drag
   * path, and dragging recentres the map so the crosshair follows.
   */
  protected readonly towerPos = computed<{ lat: number; lng: number } | null>(() => {
    if (this.mode() === 'tower') return this.mapCentre() ?? this.nudge() ?? this.fix();
    return this.nudge() ?? this.fix();
  });
  /**
   * How far the chosen point has drifted from the device's own reading.
   *
   * Null at (or within a metre of) the fix. Panning the map is
   * invisible otherwise — a curator who walked while the map was open
   * needs to be told the point is no longer where they are standing.
   */
  protected readonly offsetMeters = computed<number | null>(() => {
    const fix = this.fix();
    const chosen = this.towerPos();
    if (!fix || !chosen) return null;
    const metres = distanceMeters(fix, chosen);
    return metres < 1 ? null : metres;
  });

  // Tower capture
  protected readonly towerName = signal('');
  protected readonly currentTower = signal<TowerContext | null>(null);
  // tower-types: one tap applies icon, colour and capture radius.
  protected readonly towerTypes = signal<AdminTowerType[]>([]);
  protected readonly typeId = signal<number | null>(null);
  protected readonly selectedType = computed<AdminTowerType | null>(
    () => this.towerTypes().find((t) => t.id === this.typeId()) ?? null,
  );
  /** Capture radius the chosen type implies; null means the Game default. */
  protected readonly impliedRadius = computed(
    () => this.selectedType()?.proximity_meters ?? null,
  );
  /**
   * True when the fix is less precise than the radius the tower will
   * carry — a tower placed less precisely than its own capture radius
   * cannot reliably be captured, and that is worth saying before the
   * curator walks away rather than after the game.
   */
  protected readonly radiusBelowAccuracy = computed(() => {
    const radius = this.impliedRadius();
    const fix = this.fix();
    return radius !== null && fix !== null && fix.accuracy > radius;
  });
  protected readonly photoCount = signal(0);
  protected readonly uploadingPhoto = signal(false);

  // Zone capture
  protected readonly zones = signal<AdminZone[]>([]);
  protected readonly zoneName = signal('');
  protected readonly editingZone = signal<AdminZone | null>(null);
  /** Boundary as [lng, lat] pairs, capture order. */
  protected readonly vertices = signal<[number, number][]>([]);

  // Challenge sheet
  protected readonly sheetOpen = signal(false);
  protected readonly challenges = signal<AdminChallenge[]>([]);
  protected readonly games = signal<AdminGame[]>([]);
  protected readonly challengeTab = signal<'existing' | 'new'>('existing');
  protected readonly challengeId = signal<number | null>(null);
  protected readonly challengeGameId = signal<number | null>(null);
  protected readonly challengeText = signal('');
  protected readonly challengeDifficulty = signal(1);
  protected readonly challengeReady = computed(() =>
    this.challengeTab() === 'existing'
      ? this.challengeId() !== null
      : this.challengeGameId() !== null && this.challengeText().trim().length > 0,
  );

  private map: L.Map | null = null;
  private existingLayer: L.LayerGroup | null = null;
  private deviceMarker: L.CircleMarker | null = null;
  private accuracyCircle: L.Circle | null = null;
  private towerMarker: L.Marker | null = null;
  private zonePolygon: L.Polygon | null = null;
  private vertexMarkers: L.CircleMarker[] = [];

  constructor() {
    this.api.listCollections().subscribe({
      next: (list) => {
        this.collections.set(list);
        if (list.length === 1) {
          this.collectionId.set(list[0].id);
          this.loadExisting();
        }
      },
      error: () => {},
    });
    this.api.listZones().subscribe({ next: (l) => this.zones.set(l), error: () => {} });
    this.api
      .listTowerTypes()
      .subscribe({ next: (l) => this.towerTypes.set(l), error: () => {} });
    this.api
      .listChallenges()
      .subscribe({ next: (l) => this.challenges.set(l), error: () => {} });
    this.api.listGames().subscribe({ next: (l) => this.games.set(l), error: () => {} });

    afterNextRender(() => this.initMap());
    this.destroyRef.onDestroy(() => this.map?.remove());
  }

  // ---- Map + geolocation ---------------------------------------------------

  private initMap(): void {
    this.map = L.map(this.mapContainer().nativeElement).setView(FALLBACK_CENTER, 17);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);
    // Beneath everything being created: existing work is context, not
    // the live decision.
    this.existingLayer = L.layerGroup().addTo(this.map);
    this.map.on('click', (e: L.LeafletMouseEvent) => {
      if (this.mode() === 'zone') {
        this.appendVertex([e.latlng.lng, e.latlng.lat]);
      }
    });
    // The crosshair is the map centre, so the centre is state.
    const syncCentre = () => {
      const c = this.map?.getCenter();
      if (c) this.mapCentre.set({ lat: c.lat, lng: c.lng });
    };
    this.map.on('move', syncCentre);
    syncCentre();
    // 3.1 — ask for the device position up front and center on it.
    void this.readFix()
      .then((f) => {
        this.map?.setView([f.lat, f.lng], 18);
        this.showDevice(f);
      })
      .catch(() => {
        this.error.set(
          'Location unavailable — enable GPS/location permission to author in the field.',
        );
      });
  }

  /** One-shot high-accuracy geolocation fix (per capture, no tracking). */
  private readFix(): Promise<Fix> {
    this.reading.set(true);
    return new Promise<Fix>((resolve, reject) => {
      if (!('geolocation' in navigator)) {
        this.reading.set(false);
        reject(new Error('Geolocation unsupported'));
        return;
      }
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          this.reading.set(false);
          const f: Fix = {
            lat: pos.coords.latitude,
            lng: pos.coords.longitude,
            accuracy: pos.coords.accuracy,
          };
          this.showDevice(f);
          resolve(f);
        },
        (err) => {
          this.reading.set(false);
          this.error.set(`GPS error: ${err.message}`);
          reject(err);
        },
        { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 },
      );
    });
  }

  private showDevice(f: Fix): void {
    if (!this.map) return;
    const pos: [number, number] = [f.lat, f.lng];
    if (!this.deviceMarker) {
      this.deviceMarker = L.circleMarker(pos, {
        radius: 6,
        color: '#0d6efd',
        fillOpacity: 0.9,
      }).addTo(this.map);
      this.accuracyCircle = L.circle(pos, {
        radius: f.accuracy,
        color: '#0d6efd',
        weight: 1,
        fillOpacity: 0.08,
      }).addTo(this.map);
    } else {
      this.deviceMarker.setLatLng(pos);
      this.accuracyCircle?.setLatLng(pos).setRadius(f.accuracy);
    }
  }

  // ---- The target collection's existing elements ---------------------------

  protected onCollectionChange(id: number | null): void {
    this.collectionId.set(id);
    this.loadExisting();
  }

  private loadExisting(): void {
    const id = this.collectionId();
    if (!id) {
      this.existingTowers.set([]);
      this.existingZones.set([]);
      this.renderExisting();
      return;
    }
    this.api.listTowers(id).subscribe({
      next: (list) => {
        this.existingTowers.set(list);
        this.renderExisting();
      },
      error: () => {},
    });
    this.api.listZones(id).subscribe({
      next: (list) => {
        this.existingZones.set(list);
        this.renderExisting();
      },
      error: () => {},
    });
  }

  private renderExisting(): void {
    if (!this.existingLayer) return;
    this.existingLayer.clearLayers();

    for (const zone of this.existingZones()) {
      if (!zone.shape) continue;
      const color = zone.color || '#5F6B7A';
      L.geoJSON(zone.shape as unknown as GeoJSON.GeoJsonObject, {
        style: { color, weight: 1, fillColor: color, fillOpacity: 0.08, dashArray: '4 3' },
      })
        .bindTooltip(`${zone.name} (in this collection)`)
        .addTo(this.existingLayer);
    }

    for (const tower of this.existingTowers()) {
      if (!tower.location) continue;
      const [lng, lat] = tower.location.coordinates;
      L.marker([lat, lng], {
        icon: L.divIcon({
          // Muted, so the element being captured stays the loudest
          // thing on the screen.
          className: 'tower-pin muted',
          html: `<span style="background:${tower.resolved_color}">` +
                `<i class="bi ${tower.resolved_icon}"></i></span>`,
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        }),
        interactive: true,
        keyboard: false,
      })
        .bindTooltip(`${tower.name} — already in this collection`)
        .addTo(this.existingLayer);
    }
  }

  // ---- Tower capture (task 3.2) --------------------------------------------

  protected startTower(): void {
    this.mode.set('tower');
    this.error.set(null);
    this.notice.set(null);
    this.readings.set([]);
    this.nudge.set(null);
    this.typeId.set(null);
    void this.readFix().then((f) => {
      this.readings.set([f]);
      this.map?.setView([f.lat, f.lng], 18);
      this.mapCentre.set({ lat: f.lat, lng: f.lng });
      this.placeTowerMarker();
    });
  }

  protected reRead(): void {
    this.nudge.set(null);
    void this.readFix().then((f) => {
      this.readings.set([f]);
      this.centreOnFix();
      this.placeTowerMarker();
    });
  }

  protected addReading(): void {
    this.nudge.set(null);
    void this.readFix().then((f) => {
      this.readings.update((r) => [...r, f]);
      // Averaging moved the fix, so move the crosshair with it —
      // otherwise "add reading" would silently stop affecting where
      // the tower actually lands.
      this.centreOnFix();
      this.placeTowerMarker();
    });
  }

  /** Put the crosshair back on the device's own reading. */
  protected centreOnMe(): void {
    this.nudge.set(null);
    this.centreOnFix();
    this.placeTowerMarker();
  }

  private centreOnFix(): void {
    const f = this.fix();
    if (!f || !this.map) return;
    this.map.setView([f.lat, f.lng], this.map.getZoom());
    this.mapCentre.set({ lat: f.lat, lng: f.lng });
  }

  /** The chosen type's paint, or the untyped default. */
  private towerIcon(): L.DivIcon {
    const type = this.selectedType();
    const icon = type?.icon || DEFAULT_TOWER_ICON;
    const color = type?.color || DEFAULT_TOWER_COLOR;
    return L.divIcon({
      className: 'tower-pin',
      html: `<span style="background:${color}"><i class="bi ${icon}"></i></span>`,
      iconSize: [32, 32],
      iconAnchor: [16, 16],
    });
  }

  private placeTowerMarker(): void {
    const pos = this.towerPos();
    if (!this.map || !pos) return;
    if (!this.towerMarker) {
      this.towerMarker = L.marker([pos.lat, pos.lng], {
        draggable: true,
        icon: this.towerIcon(),
      }).addTo(this.map);
      this.towerMarker.on('dragend', () => {
        const p = this.towerMarker!.getLatLng();
        this.nudge.set({ lat: p.lat, lng: p.lng });
        // Keep pin, crosshair and saved point coincident: with a mouse
        // the drag is the nicer gesture, and it must not create a
        // second candidate position.
        this.map?.setView([p.lat, p.lng], this.map.getZoom());
        this.mapCentre.set({ lat: p.lat, lng: p.lng });
      });
    } else {
      this.towerMarker.setLatLng([pos.lat, pos.lng]);
      this.towerMarker.setIcon(this.towerIcon());
    }
  }

  /** Choosing a type repaints the pin immediately — the point of one tap. */
  protected chooseType(id: number | null): void {
    this.typeId.set(this.typeId() === id ? null : id);
    if (this.towerMarker) this.towerMarker.setIcon(this.towerIcon());
  }

  protected saveTower(): void {
    const pos = this.towerPos();
    const fix = this.fix();
    if (!pos || this.saving()) return;
    const payload = {
      name: this.towerName().trim(),
      lat: pos.lat,
      lng: pos.lng,
      category: 1,
      is_active: !this.draft(),
      authored_accuracy_m: fix ? round1(fix.accuracy) : null,
      collection: this.collectionId(),
      tower_type: this.typeId(),
    };
    if (!this.queue.online()) {
      const item = this.queue.enqueue('create-tower', payload);
      this.afterTowerSaved({ ref: item.localId, name: payload.name }, true);
      return;
    }
    this.saving.set(true);
    this.api.createTower(payload).subscribe({
      next: (tower) => {
        this.saving.set(false);
        this.afterTowerSaved({ ref: tower.id, name: tower.name }, false);
      },
      error: (err) => {
        this.saving.set(false);
        if (err?.status === 0) {
          // Network dropped mid-save: fall back to the offline queue.
          const item = this.queue.enqueue('create-tower', payload);
          this.afterTowerSaved({ ref: item.localId, name: payload.name }, true);
        } else {
          this.error.set(extractErrorMessage(err));
        }
      },
    });
  }

  private afterTowerSaved(ctx: TowerContext, queued: boolean): void {
    // The thing just placed becomes context for the next one.
    if (!queued) this.loadExisting();
    this.currentTower.set(ctx);
    this.photoCount.set(0);
    this.towerName.set('');
    this.mode.set('idle');
    this.notice.set(
      queued
        ? `${ctx.name} queued for sync — add photos or a challenge now.`
        : `${ctx.name} saved — add photos or a challenge now.`,
    );
  }

  // ---- Reference photos (task 3.3) -----------------------------------------

  protected onPhotoPicked(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    const tower = this.currentTower();
    if (!file || !tower) return;
    this.uploadingPhoto.set(true);
    void compressImage(file, PHOTO_MAX_DIM, PHOTO_JPEG_QUALITY)
      .then((dataUrl) => {
        const payload = { image: dataUrl, caption: '' };
        if (typeof tower.ref === 'number' && this.queue.online()) {
          this.api.uploadTowerPhoto(tower.ref, payload).subscribe({
            next: () => {
              this.uploadingPhoto.set(false);
              this.photoCount.update((n) => n + 1);
            },
            error: (err) => {
              this.uploadingPhoto.set(false);
              if (err?.status === 0) {
                this.queue.enqueue('upload-photo', payload, tower.ref);
                this.photoCount.update((n) => n + 1);
              } else {
                this.error.set(extractErrorMessage(err));
              }
            },
          });
        } else {
          this.queue.enqueue('upload-photo', payload, tower.ref);
          this.uploadingPhoto.set(false);
          this.photoCount.update((n) => n + 1);
        }
      })
      .catch(() => {
        this.uploadingPhoto.set(false);
        this.error.set('Could not read the photo.');
      });
  }

  // ---- Zone drawing (task 3.4) ---------------------------------------------

  protected startZone(existing: AdminZone | null): void {
    this.mode.set('zone');
    this.error.set(null);
    this.notice.set(null);
    this.editingZone.set(existing);
    this.zoneName.set('');
    const ring =
      existing?.shape?.coordinates?.[0]?.map(
        (pt) => [pt[0], pt[1]] as [number, number],
      ) ?? [];
    // Drop the GeoJSON closing point — the server re-closes the ring.
    if (ring.length > 1) ring.pop();
    this.vertices.set(ring);
    this.redrawZone();
    if (ring.length > 0 && this.map) {
      this.map.fitBounds(L.latLngBounds(ring.map(([lng, lat]) => [lat, lng])));
    }
  }

  protected markHere(): void {
    void this.readFix().then((f) => {
      this.appendVertex([f.lng, f.lat]);
      this.map?.setView([f.lat, f.lng]);
    });
  }

  protected undoVertex(): void {
    this.vertices.update((v) => v.slice(0, -1));
    this.redrawZone();
  }

  private appendVertex(lnglat: [number, number]): void {
    this.vertices.update((v) => [...v, lnglat]);
    this.redrawZone();
  }

  private redrawZone(): void {
    if (!this.map) return;
    this.zonePolygon?.remove();
    this.zonePolygon = null;
    this.vertexMarkers.forEach((m) => m.remove());
    this.vertexMarkers = [];
    const verts = this.vertices();
    if (verts.length === 0) return;
    const latlngs = verts.map(([lng, lat]) => [lat, lng] as [number, number]);
    this.zonePolygon = L.polygon(latlngs, {
      color: this.editingZone()?.color || '#198754',
      weight: 2,
      fillOpacity: 0.15,
    }).addTo(this.map);
    verts.forEach(([lng, lat], index) => {
      const marker = L.circleMarker([lat, lng], {
        radius: 9,
        color: '#198754',
        fillColor: '#ffffff',
        fillOpacity: 1,
      }).addTo(this.map!);
      // circleMarker has no drag support: drag = tap vertex, tap new spot.
      marker.on('click', (e: L.LeafletMouseEvent) => {
        L.DomEvent.stopPropagation(e);
        this.grabbedVertex = index;
      });
      this.vertexMarkers.push(marker);
    });
    // A grabbed vertex moves to the next map tap instead of appending.
    this.map.off('click');
    this.map.on('click', (e: L.LeafletMouseEvent) => {
      if (this.mode() !== 'zone') return;
      if (this.grabbedVertex !== null) {
        const i = this.grabbedVertex;
        this.grabbedVertex = null;
        this.vertices.update((v) =>
          v.map((pt, idx) => (idx === i ? [e.latlng.lng, e.latlng.lat] : pt)),
        );
        this.redrawZone();
      } else {
        this.appendVertex([e.latlng.lng, e.latlng.lat]);
      }
    });
  }

  private grabbedVertex: number | null = null;

  protected saveZone(): void {
    if (this.saving()) return;
    const verts = this.vertices();
    const existing = this.editingZone();
    if (existing) {
      const payload = { id: existing.id, vertices: verts };
      if (!this.queue.online()) {
        this.queue.enqueue('adjust-zone', payload);
        this.afterZoneSaved(existing.name, true);
        return;
      }
      this.saving.set(true);
      this.api.updateZone(existing.id, { vertices: verts }).subscribe({
        next: () => {
          this.saving.set(false);
          this.afterZoneSaved(existing.name, false);
        },
        error: (err) => {
          this.saving.set(false);
          if (err?.status === 0) {
            this.queue.enqueue('adjust-zone', payload);
            this.afterZoneSaved(existing.name, true);
          } else {
            this.error.set(extractErrorMessage(err));
          }
        },
      });
      return;
    }
    const payload = {
      name: this.zoneName().trim(),
      scoring_type: 3, // proportional-with-possession default
      vertices: verts,
      collection: this.collectionId(),
    };
    if (!this.queue.online()) {
      this.queue.enqueue('create-zone', payload);
      this.afterZoneSaved(payload.name, true);
      return;
    }
    this.saving.set(true);
    this.api.createZone(payload).subscribe({
      next: (zone) => {
        this.saving.set(false);
        this.zones.update((zs) => [...zs, zone]);
        this.afterZoneSaved(zone.name, false);
      },
      error: (err) => {
        this.saving.set(false);
        if (err?.status === 0) {
          this.queue.enqueue('create-zone', payload);
          this.afterZoneSaved(payload.name, true);
        } else {
          this.error.set(extractErrorMessage(err));
        }
      },
    });
  }

  private afterZoneSaved(name: string, queued: boolean): void {
    this.mode.set('idle');
    this.editingZone.set(null);
    this.vertices.set([]);
    this.redrawZone();
    this.notice.set(queued ? `Zone ${name} queued for sync.` : `Zone ${name} saved.`);
  }

  // ---- Attach challenge (task 3.5) -----------------------------------------

  protected openChallengeSheet(): void {
    this.sheetOpen.set(true);
    this.challengeId.set(null);
    this.challengeText.set('');
  }

  protected saveChallenge(): void {
    const tower = this.currentTower();
    if (!tower || this.saving()) return;
    const payload =
      this.challengeTab() === 'existing'
        ? { challenge: this.challengeId()! }
        : {
            game: this.challengeGameId()!,
            text: this.challengeText().trim(),
            difficulty: this.challengeDifficulty() || 1,
          };
    if (typeof tower.ref !== 'number' || !this.queue.online()) {
      this.queue.enqueue('attach-challenge', payload, tower.ref);
      this.sheetOpen.set(false);
      this.notice.set('Challenge link queued for sync.');
      return;
    }
    this.saving.set(true);
    this.api.attachChallenge(tower.ref, payload).subscribe({
      next: () => {
        this.saving.set(false);
        this.sheetOpen.set(false);
        this.notice.set(`Challenge attached to ${tower.name}.`);
      },
      error: (err) => {
        this.saving.set(false);
        if (err?.status === 0) {
          this.queue.enqueue('attach-challenge', payload, tower.ref);
          this.sheetOpen.set(false);
          this.notice.set('Challenge link queued for sync.');
        } else {
          this.error.set(extractErrorMessage(err));
        }
      },
    });
  }

  // ---- Misc ----------------------------------------------------------------

  protected cancelCapture(): void {
    this.mode.set('idle');
    this.readings.set([]);
    this.nudge.set(null);
    this.editingZone.set(null);
    this.vertices.set([]);
    this.towerMarker?.remove();
    this.towerMarker = null;
    this.redrawZone();
  }

  protected syncNow(): void {
    void this.queue.sync();
  }

  protected isQueuedRef(ref: number | string): boolean {
    return typeof ref === 'string';
  }

  protected describeEdit(kind: string): string {
    switch (kind) {
      case 'create-tower':
        return 'New tower';
      case 'create-zone':
        return 'New zone';
      case 'adjust-zone':
        return 'Zone boundary';
      case 'upload-photo':
        return 'Reference photo';
      case 'attach-challenge':
        return 'Challenge link';
      default:
        return kind;
    }
  }
}

/** Great-circle metres between two points (equirectangular is plenty
    at the tens-of-metres scale this is read at). */
export function distanceMeters(
  a: { lat: number; lng: number },
  b: { lat: number; lng: number },
): number {
  const R = 6371000;
  const toRad = Math.PI / 180;
  const x = (b.lng - a.lng) * toRad * Math.cos(((a.lat + b.lat) / 2) * toRad);
  const y = (b.lat - a.lat) * toRad;
  return Math.sqrt(x * x + y * y) * R;
}

function average(readings: Fix[]): Fix | null {
  if (readings.length === 0) return null;
  const n = readings.length;
  return {
    lat: readings.reduce((s, r) => s + r.lat, 0) / n,
    lng: readings.reduce((s, r) => s + r.lng, 0) / n,
    accuracy: readings.reduce((s, r) => s + r.accuracy, 0) / n,
  };
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

/** Downscale + JPEG-compress a captured photo; resolves to a data URL. */
function compressImage(file: File, maxDim: number, quality: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, maxDim / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('canvas unavailable'));
        return;
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      resolve(canvas.toDataURL('image/jpeg', quality));
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('image load failed'));
    };
    img.src = url;
  });
}
