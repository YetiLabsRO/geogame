import { HttpClient } from '@angular/common/http';
import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  HostListener,
  ViewEncapsulation,
  afterNextRender,
  computed,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import * as L from 'leaflet';
import { forkJoin } from 'rxjs';
import * as turf from '@turf/turf';

import {
  AdminCollection,
  AdminGame,
  AdminTower,
  AdminTowerType,
  AdminZone,
  ConfirmService,
  FieldRowComponent,
  InfoHintComponent,
  PageHeaderComponent,
  StaffApiService,
  StatTileComponent,
} from 'shared';

import { extractErrorMessage } from '../../auth/form-error';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type EditorTool = 'select' | 'tower' | 'zone';

/** A boundary point, [lng, lat] -- matches the backend's `vertices` contract. */
type LngLat = [number, number];

/** Reactive (form-bound) fields of the zone currently being drawn/edited. */
interface ZoneDraftMeta {
  /** Existing zone id being edited, or null for a brand-new zone. */
  zoneId: number | null;
  name: string;
  color: string;
  scoringType: number;
}

interface PendingTower {
  /** tower-types: chosen before saving, so the pin paints as you decide. */
  towerTypeId: number | null;
  lat: number;
  lng: number;
  name: string;
  saving: boolean;
  error: string | null;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 15;
/** Click-near-first-vertex tolerance (px) that closes a drawn ring. */
const CLOSE_TOLERANCE_PX = 12;
const DEFAULT_ZONE_COLOR = '#2C74B3';
/** Zone.SCORE_LIN (game/models.py) -- "points proportional to possession". */
const DEFAULT_SCORING_TYPE = 3;

/** Untyped paint — mirrors game/models.py's DEFAULT_TOWER_* constants. */
const DEFAULT_TOWER_ICON = 'bi-geo-alt-fill';
const DEFAULT_TOWER_COLOR = '#5F6B7A';

/**
 * A tower marker painted by its resolved type styling (tower-types).
 *
 * `resolved_*` comes off the API already worked out — tower override,
 * else type, else default — so this never re-implements that chain.
 */
function towerIcon(
  options: { icon?: string; color?: string; pending?: boolean } = {},
): L.DivIcon {
  const icon = options.icon || DEFAULT_TOWER_ICON;
  const color = options.color || DEFAULT_TOWER_COLOR;
  return L.divIcon({
    className: `map-editor-tower-icon${options.pending ? ' pending' : ''}`,
    html: `<span style="background:${color}"><i class="bi ${icon}"></i></span>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}
const VERTEX_ICON = L.divIcon({
  className: 'map-editor-vertex-icon',
  html: '',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});
const MIDPOINT_ICON = L.divIcon({
  className: 'map-editor-midpoint-icon',
  html: '',
  iconSize: [10, 10],
  iconAnchor: [5, 5],
});

function midpointLngLat(a: LngLat, b: LngLat): LngLat {
  return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
}

function isTextInputFocused(): boolean {
  const el = document.activeElement;
  if (!el) return false;
  return el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT';
}

/**
 * Staff desktop map editor: place/move towers, draw/edit zone boundaries
 * with real draggable vertex handles, snap to nearby geometry, and preview
 * "existing zones win" overlap clipping before saving. Full geometry CRUD
 * used to only be possible in the Django admin or the GPS-first field-mode;
 * this gives staff a proper desktop editor with a live map.
 *
 * The authoritative overlap clip is server-side (`AdminZoneSerializer`,
 * `game/admin_api.py`) -- the client-side clip computed here (via
 * `@turf/turf`) is an advisory preview only, so staff see the saved result
 * before committing and can back out of a fully-swallowed shape early.
 */
@Component({
  selector: 'app-admin-map-editor',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  // Leaflet renders markers/polygons as DOM Angular's emulated view
  // encapsulation never touches (they're created imperatively, outside the
  // template) -- component-scoped `styles` can't reach them. Going
  // encapsulation-free lets the marker-icon rules below (namespaced
  // `map-editor-*`) actually apply, same trick the theme docs recommend for
  // any component that owns a Leaflet map.
  encapsulation: ViewEncapsulation.None,
  imports: [FormsModule, FieldRowComponent, InfoHintComponent, PageHeaderComponent, StatTileComponent],
  template: `
    <app-page-header title="Map editor" [subtitle]="headerSubtitle()" [topoBg]="true">
      <div actions class="map-editor-selectors">
        <label class="map-editor-selector">
          <span class="map-editor-selector__label">Game</span>
          <select
            class="form-select form-select-sm"
            [ngModel]="selectedGameId()"
            (ngModelChange)="onGameChange($event)"
          >
            <option [ngValue]="null">All games</option>
            @for (g of games(); track g.id) {
              <option [ngValue]="g.id">{{ g.name }}</option>
            }
          </select>
        </label>
        <label class="map-editor-selector">
          <span class="map-editor-selector__label">Collection</span>
          <select
            class="form-select form-select-sm"
            [ngModel]="selectedCollectionId()"
            (ngModelChange)="onCollectionChange($event)"
          >
            <option [ngValue]="null" disabled>Select a collection…</option>
            @for (c of collectionsForSelectedGame(); track c.id) {
              <option [ngValue]="c.id">{{ c.name }}</option>
            }
          </select>
        </label>
        <app-stat-tile label="Towers" [value]="towers().length" icon="bi-broadcast" tone="primary" />
        <app-stat-tile label="Zones" [value]="zones().length" icon="bi-pentagon" tone="info" />
      </div>
    </app-page-header>

    <p class="map-editor-hint-row small text-body-secondary">
      <app-info-hint>
        <strong>Snapping:</strong> while dragging a vertex or a tower, nearby existing zone
        vertices, edges, and towers within the snap tolerance pull the point into alignment —
        use it to share clean edges between adjacent zones.
        <br /><strong>Existing zones win:</strong> a new or edited zone that overlaps an
        existing one is clipped to the non-overlapping remainder on save (enforced by the
        server; previewed here first). A zone entirely inside an existing one is rejected —
        edit the existing zone instead.
      </app-info-hint>
      Snapping and existing-zone-wins overlap rules apply while drawing.
    </p>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }
    @if (notice(); as msg) {
      <div class="alert alert-success py-2">{{ msg }}</div>
    }

    <div class="map-editor-shell">
      <div class="map-editor-host" #mapContainer></div>

      <aside
        class="map-editor-palette"
        [class.map-editor-palette--collapsed]="paletteCollapsed()"
      >
        <button
          type="button"
          class="map-editor-palette__toggle"
          (click)="paletteCollapsed.set(!paletteCollapsed())"
          [attr.aria-expanded]="!paletteCollapsed()"
          aria-label="Toggle tool palette"
        >
          <i
            class="bi"
            [class.bi-chevron-left]="!paletteCollapsed()"
            [class.bi-chevron-right]="paletteCollapsed()"
          ></i>
        </button>

        @if (!paletteCollapsed()) {
          <div class="map-editor-palette__body">
            <div class="map-editor-tool-group" role="group" aria-label="Editor tool">
              <button
                type="button"
                class="btn btn-sm"
                [class.btn-primary]="tool() === 'select'"
                [class.btn-outline-secondary]="tool() !== 'select'"
                (click)="setTool('select')"
              >
                <i class="bi bi-cursor"></i> Select
              </button>
              <button
                type="button"
                class="btn btn-sm"
                [class.btn-primary]="tool() === 'tower'"
                [class.btn-outline-secondary]="tool() !== 'tower'"
                (click)="setTool('tower')"
              >
                <i class="bi bi-geo-alt"></i> Tower
              </button>
              <button
                type="button"
                class="btn btn-sm"
                [class.btn-primary]="tool() === 'zone'"
                [class.btn-outline-secondary]="tool() !== 'zone'"
                (click)="setTool('zone')"
              >
                <i class="bi bi-pentagon"></i> Zone
              </button>
            </div>

            <p class="map-editor-tool-help small text-body-secondary mb-0">
              @switch (tool()) {
                @case ('tower') {
                  Click the map to place a new tower.
                }
                @case ('zone') {
                  @if (drawingActiveSig()) {
                    Click to add vertices. Click the first vertex again (or press Enter) to
                    close the shape.
                  } @else if (zoneDraft()) {
                    Drag handles to adjust. Click a midpoint to insert a vertex. Right-click
                    (or select + Delete) removes one. Drag the shape itself to move it.
                  } @else {
                    Click the map to start drawing a new zone.
                  }
                }
                @default {
                  Drag a tower to move it. Click a zone to edit its boundary.
                }
              }
            </p>

            <div class="map-editor-divider"></div>

            <div class="map-editor-row">
              <button
                type="button"
                class="btn btn-sm btn-outline-secondary"
                [disabled]="!canUndo()"
                (click)="undo()"
              >
                <i class="bi bi-arrow-counterclockwise"></i> Undo
              </button>
            </div>

            <div class="map-editor-snap">
              <label class="form-check form-switch mb-1">
                <input
                  class="form-check-input"
                  type="checkbox"
                  role="switch"
                  [ngModel]="snapEnabled()"
                  (ngModelChange)="snapEnabled.set($event)"
                />
                <span class="form-check-label small">Snap to nearby geometry</span>
              </label>
              <label class="small d-block mb-0">
                Tolerance: {{ snapTolerancePx() }}px
                <input
                  type="range"
                  class="form-range"
                  min="4"
                  max="40"
                  [ngModel]="snapTolerancePx()"
                  (ngModelChange)="snapTolerancePx.set($event)"
                  [disabled]="!snapEnabled()"
                />
              </label>
            </div>

            <div class="map-editor-divider"></div>

            <div class="map-editor-legend small text-body-secondary">
              <div>
                <span class="map-editor-legend__swatch map-editor-legend__swatch--zone"></span>
                Existing zone
              </div>
              <div>
                <span class="map-editor-legend__swatch map-editor-legend__swatch--draft"></span>
                Draft boundary
              </div>
              <div>
                <span class="map-editor-legend__swatch map-editor-legend__swatch--clip"></span>
                What will be saved (clipped)
              </div>
              <div><i class="bi bi-broadcast"></i> Tower</div>
            </div>

            @if (pendingTower(); as pt) {
              <div class="map-editor-divider"></div>
              <div class="map-editor-form">
                <h2 class="map-editor-form__title">New tower</h2>
                <p class="map-editor-hint">
                  Placed on the map — drag the pin to adjust before saving.
                </p>
                <app-field-row label="Name" [required]="true" [error]="pt.error ?? undefined" for="new-tower-name">
                  <input
                    id="new-tower-name"
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="pt.name"
                    (ngModelChange)="updatePendingTowerName($event)"
                  />
                </app-field-row>
                @if (towerTypes().length) {
                  <app-field-row label="Type" for="new-tower-type">
                    <select
                      id="new-tower-type"
                      class="form-select form-select-sm"
                      [ngModel]="pt.towerTypeId"
                      (ngModelChange)="updatePendingTowerType($event)"
                    >
                      <option [ngValue]="null">untyped</option>
                      @for (t of towerTypes(); track t.id) {
                        <option [ngValue]="t.id">{{ t.name }}</option>
                      }
                    </select>
                  </app-field-row>
                }
                <div class="map-editor-row">
                  <button
                    type="button"
                    class="btn btn-sm btn-primary"
                    [disabled]="pt.saving"
                    (click)="savePendingTower()"
                  >
                    @if (pt.saving) {
                      <span class="spinner-border spinner-border-sm me-1"></span>
                    }
                    Place tower
                  </button>
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-secondary"
                    [disabled]="pt.saving"
                    (click)="cancelPendingTower()"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            }

            @if (selectedTower(); as st) {
              <div class="map-editor-divider"></div>
              <div class="map-editor-form">
                <h2 class="map-editor-form__title">{{ st.name }}</h2>
                <app-field-row label="Name" for="edit-tower-name">
                  <input
                    id="edit-tower-name"
                    class="form-control form-control-sm"
                    type="text"
                    [ngModel]="st.name"
                    (ngModelChange)="renameSelectedTower($event)"
                  />
                </app-field-row>
                <div class="map-editor-row">
                  <button type="button" class="btn btn-sm btn-outline-danger" (click)="deleteSelectedTower()">
                    <i class="bi bi-trash"></i> Delete tower
                  </button>
                  <button type="button" class="btn btn-sm btn-outline-secondary" (click)="selectedTower.set(null)">
                    Close
                  </button>
                </div>
              </div>
            }

            @if (zoneDraft(); as draft) {
              <div class="map-editor-divider"></div>
              <div class="map-editor-form">
                <h2 class="map-editor-form__title">
                  {{ draft.zoneId === null ? 'New zone' : 'Edit zone' }}
                  <span class="badge text-bg-light border">{{ draftVertexCount() }} vertices</span>
                </h2>

                @if (zoneDraftWarning(); as warn) {
                  <div class="alert alert-warning py-2 small mb-2">{{ warn }}</div>
                }
                @if (zoneDraftError(); as err) {
                  <div class="alert alert-danger py-2 small mb-2">{{ err }}</div>
                }

                @if (!drawingActiveSig()) {
                  <app-field-row label="Name" [required]="true" for="zone-draft-name">
                    <input
                      id="zone-draft-name"
                      class="form-control form-control-sm"
                      type="text"
                      [ngModel]="draft.name"
                      (ngModelChange)="updateZoneDraft('name', $event)"
                    />
                  </app-field-row>
                  <app-field-row label="Color" for="zone-draft-color">
                    <input
                      id="zone-draft-color"
                      class="form-control form-control-color form-control-sm"
                      type="color"
                      [ngModel]="draft.color"
                      (ngModelChange)="updateZoneDraft('color', $event)"
                    />
                  </app-field-row>
                  <app-field-row label="Scoring" for="zone-draft-scoring">
                    <select
                      id="zone-draft-scoring"
                      class="form-select form-select-sm"
                      [ngModel]="draft.scoringType"
                      (ngModelChange)="updateZoneDraft('scoringType', $event)"
                    >
                      <option [ngValue]="1">Logarithmic (more early)</option>
                      <option [ngValue]="2">Exponential (more over time)</option>
                      <option [ngValue]="3">Linear (proportional)</option>
                      <option [ngValue]="4">Bonus (capped 200)</option>
                    </select>
                  </app-field-row>

                  <div class="map-editor-row">
                    <button
                      type="button"
                      class="btn btn-sm btn-primary"
                      [disabled]="zoneDraftSaving() || zoneDraftBlocked()"
                      (click)="saveZoneDraft()"
                    >
                      @if (zoneDraftSaving()) {
                        <span class="spinner-border spinner-border-sm me-1"></span>
                      }
                      {{ draft.zoneId === null ? 'Create zone' : 'Save changes' }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      [disabled]="zoneDraftSaving()"
                      (click)="cancelZoneDraft()"
                    >
                      Cancel
                    </button>
                  </div>
                  @if (draft.zoneId !== null) {
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-danger mt-2"
                      [disabled]="zoneDraftSaving()"
                      (click)="deleteZoneDraft()"
                    >
                      <i class="bi bi-trash"></i> Delete zone
                    </button>
                  }
                } @else {
                  <div class="map-editor-row">
                    <button
                      type="button"
                      class="btn btn-sm btn-primary"
                      [disabled]="draftVertexCount() < 3"
                      (click)="finishDrawing()"
                    >
                      Finish shape
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" (click)="cancelZoneDraft()">
                      Cancel
                    </button>
                  </div>
                }
              </div>
            }
          </div>
        }
      </aside>
    </div>
  `,
  styles: `
    :host {
      display: block;
    }

    .map-editor-selectors {
      display: flex;
      flex-wrap: wrap;
      align-items: end;
      gap: var(--space-3);
    }

    .map-editor-selector {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
      min-width: 10rem;
    }

    .map-editor-selector__label {
      font-size: var(--text-xs);
      font-weight: 600;
      color: var(--ink-muted);
    }

    .map-editor-hint {
      margin: 0 0 var(--space-2);
      font-size: var(--text-xs);
      color: var(--ink-muted);
    }

    .map-editor-hint-row {
      display: flex;
      align-items: center;
      gap: var(--space-2);
      margin-bottom: var(--space-3);
    }

    .map-editor-shell {
      position: relative;
      height: calc(100vh - 16rem);
      min-height: 26rem;
      border-radius: var(--radius-lg);
      overflow: hidden;
      border: 1px solid var(--border);
      box-shadow: var(--shadow-1);
    }

    .map-editor-host {
      height: 100%;
      width: 100%;
    }

    .map-editor-palette {
      position: absolute;
      top: var(--space-3);
      left: var(--space-3);
      z-index: 1000;
      width: 18rem;
      max-width: calc(100% - 2 * var(--space-3));
      max-height: calc(100% - 2 * var(--space-3));
      overflow-y: auto;
      background-color: var(--panel);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow-3);
    }

    .map-editor-palette--collapsed {
      width: auto;
    }

    .map-editor-palette__toggle {
      position: sticky;
      top: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 2rem;
      height: 2rem;
      margin: var(--space-2);
      border: 1px solid var(--border);
      border-radius: var(--radius-sm);
      background-color: var(--panel-sunken);
      color: var(--ink);
    }

    .map-editor-palette__body {
      padding: 0 var(--space-3) var(--space-3);
      display: flex;
      flex-direction: column;
      gap: var(--space-2);
    }

    .map-editor-tool-group {
      display: flex;
      gap: var(--space-1);
    }

    .map-editor-tool-group .btn {
      flex: 1 1 auto;
    }

    .map-editor-divider {
      border-top: 1px solid var(--border);
      margin: var(--space-1) 0;
    }

    .map-editor-row {
      display: flex;
      flex-wrap: wrap;
      gap: var(--space-2);
      align-items: center;
    }

    .map-editor-snap .form-range {
      width: 100%;
    }

    .map-editor-legend {
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
    }

    .map-editor-legend__swatch {
      display: inline-block;
      width: 0.9rem;
      height: 0.9rem;
      border-radius: 3px;
      margin-right: var(--space-1);
      vertical-align: middle;
      border: 2px solid var(--info);
      background-color: rgba(44, 116, 179, 0.25);
    }

    .map-editor-legend__swatch--draft {
      border-style: dashed;
      border-color: var(--primary);
      background-color: rgba(47, 122, 79, 0.15);
    }

    .map-editor-legend__swatch--clip {
      border-color: var(--warning);
      background-color: rgba(224, 123, 57, 0.35);
    }

    .map-editor-form__title {
      font-size: var(--text-sm);
      font-weight: 650;
      margin: 0 0 var(--space-2);
      display: flex;
      align-items: center;
      gap: var(--space-2);
    }

    /* --- Leaflet-rendered DOM below: created imperatively, so it needs
       unscoped (ViewEncapsulation.None) rules, namespaced to avoid
       colliding with any other page's classes. --- */

    .map-editor-tower-icon {
      width: 26px;
      height: 26px;
      box-shadow: var(--shadow-2);
      border-radius: 50%;
    }

    .map-editor-tower-icon span {
      width: 26px;
      height: 26px;
      border-radius: 50%;
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      /* A white ring against busy tiles, and a dark one so a pale type
         colour still has an edge. */
      box-shadow:
        0 0 0 2px var(--panel),
        inset 0 0 0 1px rgb(0 0 0 / 25%);
    }

    /* The unsaved one: dashed and pulsing, so it reads as a decision in
       progress rather than as a tower that already exists. */
    .map-editor-tower-icon.pending span {
      box-shadow:
        0 0 0 2px var(--panel),
        0 0 0 4px var(--primary);
      animation: map-editor-pending-pulse 1.6s ease-in-out infinite;
      cursor: grab;
    }

    .map-editor-tower-icon.pending:active span {
      cursor: grabbing;
    }

    @keyframes map-editor-pending-pulse {
      0%,
      100% {
        opacity: 1;
      }
      50% {
        opacity: 0.55;
      }
    }

    @media (prefers-reduced-motion: reduce) {
      .map-editor-tower-icon.pending span {
        animation: none;
      }
    }

    .map-editor-vertex-icon {
      width: 14px;
      height: 14px;
      border-radius: 50%;
      background-color: var(--panel);
      border: 2px solid var(--primary);
      box-shadow: var(--shadow-1);
      cursor: grab;
    }

    .map-editor-vertex-icon:active {
      cursor: grabbing;
    }

    .map-editor-midpoint-icon {
      width: 10px;
      height: 10px;
      border-radius: 50%;
      background-color: var(--panel);
      border: 2px solid var(--ink-muted);
      opacity: 0.7;
      cursor: copy;
    }

    .map-editor-midpoint-icon:hover {
      opacity: 1;
      border-color: var(--primary);
    }

    @media (max-width: 640px) {
      .map-editor-palette {
        width: calc(100% - 2 * var(--space-3));
      }

      .map-editor-shell {
        height: calc(100vh - 20rem);
      }
    }
  `,
})
export class MapEditorComponent {
  private readonly api = inject(StaffApiService);
  private readonly http = inject(HttpClient);
  private readonly confirmService = inject(ConfirmService);
  private readonly destroyRef = inject(DestroyRef);

  protected readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');

  // ---- data ----------------------------------------------------------------

  protected readonly games = signal<AdminGame[]>([]);
  protected readonly collections = signal<AdminCollection[]>([]);
  protected readonly selectedGameId = signal<number | null>(null);
  protected readonly selectedCollectionId = signal<number | null>(null);
  protected readonly towers = signal<AdminTower[]>([]);
  protected readonly towerTypes = signal<AdminTowerType[]>([]);
  protected readonly zones = signal<AdminZone[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly notice = signal<string | null>(null);

  // ---- tool palette ----------------------------------------------------------

  protected readonly tool = signal<EditorTool>('select');
  protected readonly paletteCollapsed = signal(false);
  protected readonly snapEnabled = signal(true);
  protected readonly snapTolerancePx = signal(18);

  // ---- zone draft (new-shape drawing OR editing an existing zone) ----------

  protected readonly zoneDraft = signal<ZoneDraftMeta | null>(null);
  protected readonly zoneDraftSaving = signal(false);
  protected readonly zoneDraftError = signal<string | null>(null);
  /** Non-blocking: informational (partial overlap -- server will clip it). */
  protected readonly zoneDraftWarning = signal<string | null>(null);
  /** Blocking: the draft would be fully swallowed by existing zone(s). */
  protected readonly zoneDraftBlocked = signal(false);
  protected readonly draftVertexCount = signal(0);
  protected readonly drawingActiveSig = signal(false);
  protected readonly canUndo = signal(false);

  // ---- towers ----------------------------------------------------------------

  protected readonly pendingTower = signal<PendingTower | null>(null);
  /**
   * The not-yet-saved tower, drawn on the map the instant it is placed.
   *
   * Without it, clicking the map opened a name field in the side
   * palette and put nothing where the click landed — so the one thing
   * the click was about (where) was the one thing invisible until after
   * a name had been typed and the server had answered.
   */
  private pendingMarker: L.Marker | null = null;
  protected readonly selectedTower = signal<AdminTower | null>(null);

  protected readonly collectionsForSelectedGame = computed(() => {
    const gameId = this.selectedGameId();
    const all = this.collections();
    if (gameId === null) return all;
    const game = this.games().find((g) => g.id === gameId);
    if (!game) return all;
    return all.filter((c) => game.collections.includes(c.id));
  });

  protected readonly headerSubtitle = computed(() => {
    const collectionId = this.selectedCollectionId();
    if (collectionId === null) return 'Select a collection to start editing.';
    const collection = this.collections().find((c) => c.id === collectionId);
    const name = collection?.name ?? '…';
    return `${this.towers().length} towers · ${this.zones().length} zones · ${name}`;
  });

  // ---- Leaflet state (imperative, not signals -- see THEME.md/player map) --

  private map: L.Map | null = null;
  private towerLayerGroup: L.LayerGroup | null = null;
  private zoneLayerGroup: L.LayerGroup | null = null;
  private draftLayerGroup: L.LayerGroup | null = null;
  private mapReady = false;

  private draftRing: LngLat[] = [];
  private drawingActive = false;
  private undoStack: LngLat[][] = [];
  private activeVertexIndex: number | null = null;

  private vertexMarkers: L.Marker[] = [];
  private midpointMarkers: L.Marker[] = [];
  private draftPolygon: L.Polygon | null = null;
  private draftLine: L.Polyline | null = null;
  private clipPreviewLayer: L.GeoJSON | null = null;
  private snapIndicator: L.CircleMarker | null = null;

  private draftStrokeColor = '#2F7A4F';
  private clipPreviewColor = '#E07B39';
  private snapIndicatorColor = '#379A5B';

  constructor() {
    if (typeof window !== 'undefined' && window.innerWidth < 640) {
      this.paletteCollapsed.set(true);
    }

    afterNextRender(() => this.initMap());

    this.api.listTowerTypes().subscribe({
      next: (list) => this.towerTypes.set(list),
      error: () => {},
    });

    this.api.listGames().subscribe({
      next: (list) => this.games.set(list),
      error: () => {},
    });
    this.api.listCollections().subscribe({
      next: (list) => {
        this.collections.set(list);
        if (this.selectedCollectionId() === null && list.length > 0) {
          this.selectedCollectionId.set(list[0].id);
          this.reloadGeometry();
        }
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });

    this.destroyRef.onDestroy(() => this.map?.remove());
  }

  // ---- game/collection selection --------------------------------------------

  protected onGameChange(gameId: number | null): void {
    this.selectedGameId.set(gameId);
    const options = this.collectionsForSelectedGame();
    if (!options.some((c) => c.id === this.selectedCollectionId())) {
      this.onCollectionChange(options[0]?.id ?? null);
    }
  }

  protected onCollectionChange(collectionId: number | null): void {
    if (this.zoneDraft()) this.exitZoneDraft();
    this.pendingTower.set(null);
    this.selectedTower.set(null);
    this.selectedCollectionId.set(collectionId);
    this.reloadGeometry();
  }

  private reloadGeometry(): void {
    const collectionId = this.selectedCollectionId();
    if (collectionId === null) {
      this.towers.set([]);
      this.zones.set([]);
      if (this.mapReady) {
        this.renderTowers();
        this.renderZones();
      }
      return;
    }
    this.loading.set(true);
    this.loadError.set(null);
    forkJoin({
      towers: this.api.listTowers(collectionId),
      zones: this.api.listZones(collectionId),
    }).subscribe({
      next: ({ towers, zones }) => {
        this.towers.set(towers);
        this.zones.set(zones);
        this.loading.set(false);
        if (this.mapReady) {
          this.renderTowers();
          this.renderZones();
          this.fitToData(towers, zones);
        }
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  // ---- map setup ---------------------------------------------------------

  private initMap(): void {
    const container = this.mapContainer().nativeElement;
    this.map = L.map(container).setView(FALLBACK_CENTER, FALLBACK_ZOOM);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);

    this.towerLayerGroup = L.layerGroup().addTo(this.map);
    this.zoneLayerGroup = L.layerGroup().addTo(this.map);
    this.draftLayerGroup = L.layerGroup().addTo(this.map);

    this.draftStrokeColor = this.readCssVar('--primary', this.draftStrokeColor);
    this.clipPreviewColor = this.readCssVar('--warning', this.clipPreviewColor);
    this.snapIndicatorColor = this.readCssVar('--success', this.snapIndicatorColor);

    this.map.on('click', (e: L.LeafletMouseEvent) => this.onMapClick(e));
    this.map.on('mousemove', (e: L.LeafletMouseEvent) => this.onMapMouseMove(e));

    this.mapReady = true;
    this.renderTowers();
    this.renderZones();
    this.fitToData(this.towers(), this.zones());
  }

  private fitToData(towers: AdminTower[], zones: AdminZone[]): void {
    if (!this.map) return;
    const points: L.LatLngExpression[] = [];
    for (const t of towers) {
      if (t.location) points.push([t.location.coordinates[1], t.location.coordinates[0]]);
    }
    for (const z of zones) {
      if (!z.shape) continue;
      for (const [lng, lat] of z.shape.coordinates[0]) points.push([lat, lng]);
    }
    if (points.length === 0) return;
    this.map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 18 });
  }

  private readCssVar(name: string, fallback: string): string {
    if (typeof document === 'undefined') return fallback;
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  // ---- tool switching ------------------------------------------------------

  protected setTool(tool: EditorTool): void {
    if (this.tool() === tool) return;
    if (this.zoneDraft()) {
      this.exitZoneDraft();
      this.renderZones();
    }
    this.pendingTower.set(null);
    this.clearPendingMarker();
    this.selectedTower.set(null);
    this.tool.set(tool);
    this.renderTowers(); // draggable-state depends on "no zone being edited"
  }

  // ---- map interaction -------------------------------------------------------

  private onMapClick(e: L.LeafletMouseEvent): void {
    const tool = this.tool();
    if (tool === 'tower') {
      if (this.zoneDraft()) return;
      this.startPendingTower(e.latlng);
      return;
    }
    if (tool === 'zone') {
      this.handleZoneDrawClick(e);
    }
  }

  private onMapMouseMove(e: L.LeafletMouseEvent): void {
    if (this.tool() === 'zone' && this.drawingActive) {
      const snap = this.trySnap(e.latlng, this.zoneDraft()?.zoneId ?? null);
      if (snap) this.showSnapIndicator(snap);
      else this.hideSnapIndicator();
    }
  }

  // ---- tower placement -----------------------------------------------------

  private startPendingTower(latlng: L.LatLng): void {
    const snap = this.trySnap(latlng, null);
    const point = snap ?? latlng;
    this.hideSnapIndicator();
    this.pendingTower.set({
      lat: point.lat, lng: point.lng, name: '',
      towerTypeId: null, saving: false, error: null,
    });
    this.showPendingMarker(point);
  }

  /** Put the pin down first; the name is the part that can wait. */
  private showPendingMarker(point: L.LatLng | { lat: number; lng: number }): void {
    if (!this.map) return;
    const latlng = L.latLng(point.lat, point.lng);
    if (!this.pendingMarker) {
      this.pendingMarker = L.marker(latlng, {
        icon: towerIcon({ pending: true }),
        draggable: true,
        // Above the saved towers: it is the one thing being decided.
        zIndexOffset: 1000,
      });
      this.pendingMarker.bindTooltip('New tower — drag to reposition');
      this.pendingMarker.on('dragstart', () => this.hideSnapIndicator());
      this.pendingMarker.on('drag', (ev) => {
        const snapped = this.trySnap((ev.target as L.Marker).getLatLng(), null);
        if (snapped) this.showSnapIndicator(snapped);
        else this.hideSnapIndicator();
      });
      this.pendingMarker.on('dragend', (ev) => this.onPendingDragEnd(ev.target as L.Marker));
      this.pendingMarker.addTo(this.map);
      this.pendingMarker.openTooltip();
    } else {
      this.pendingMarker.setLatLng(latlng);
    }
  }

  /** Repositioning before saving: the marker is the source of truth. */
  private onPendingDragEnd(marker: L.Marker): void {
    this.hideSnapIndicator();
    const snapped = this.trySnap(marker.getLatLng(), null);
    const point = snapped ?? marker.getLatLng();
    marker.setLatLng(point);
    const pt = this.pendingTower();
    if (pt) this.pendingTower.set({ ...pt, lat: point.lat, lng: point.lng });
  }

  private clearPendingMarker(): void {
    if (this.pendingMarker && this.map) this.map.removeLayer(this.pendingMarker);
    this.pendingMarker = null;
  }

  protected updatePendingTowerName(name: string): void {
    const pt = this.pendingTower();
    if (!pt) return;
    this.pendingTower.set({ ...pt, name });
  }

  protected updatePendingTowerType(towerTypeId: number | null): void {
    const pt = this.pendingTower();
    if (!pt) return;
    this.pendingTower.set({ ...pt, towerTypeId });
    // Repaint the pin as the choice is made, so the map answers
    // "what will this look like" without a save.
    const type = this.towerTypes().find((t) => t.id === towerTypeId);
    this.pendingMarker?.setIcon(
      towerIcon({ icon: type?.icon, color: type?.color, pending: true }),
    );
  }

  protected savePendingTower(): void {
    const pt = this.pendingTower();
    if (!pt || pt.saving) return;
    if (!pt.name.trim()) {
      this.pendingTower.set({ ...pt, error: 'Name is required.' });
      return;
    }
    const collectionId = this.selectedCollectionId();
    if (!collectionId) {
      this.pendingTower.set({ ...pt, error: 'Select a collection first.' });
      return;
    }
    this.pendingTower.set({ ...pt, saving: true, error: null });
    this.api
      .createTower({
        name: pt.name.trim(),
        lat: pt.lat,
        lng: pt.lng,
        collection: collectionId,
        // Required by AdminTowerSerializer despite being typed optional on
        // CreateTowerPayload (the field-authoring mobile flow always sends
        // them too, see FieldAuthoringTowerApiTest in game/tests.py) --
        // desk-placed towers default to a plain, active tower.
        category: 1, // Tower.CATEGORY_NORMAL (game/models.py)
        is_active: true,
        tower_type: pt.towerTypeId,
      })
      .subscribe({
        next: (tower) => {
          this.notice.set(`Tower "${tower.name}" placed.`);
          this.pendingTower.set(null);
          this.clearPendingMarker();
          this.reloadGeometry();
        },
        error: (err) => {
          const current = this.pendingTower();
          if (current) {
            this.pendingTower.set({ ...current, saving: false, error: extractErrorMessage(err) });
          }
        },
      });
  }

  protected cancelPendingTower(): void {
    this.pendingTower.set(null);
    this.clearPendingMarker();
  }

  private onTowerDragEnd(tower: AdminTower, marker: L.Marker): void {
    this.hideSnapIndicator();
    const snap = this.trySnap(marker.getLatLng(), null);
    const point = snap ?? marker.getLatLng();
    marker.setLatLng(point);
    this.api.updateTower(tower.id, { lat: point.lat, lng: point.lng }).subscribe({
      next: (updated) => {
        this.notice.set(`"${updated.name}" moved.`);
        this.reloadGeometry();
      },
      error: (err) => {
        this.loadError.set(extractErrorMessage(err));
        if (tower.location) {
          const [lng, lat] = tower.location.coordinates;
          marker.setLatLng([lat, lng]);
        }
      },
    });
  }

  protected renameSelectedTower(name: string): void {
    const tower = this.selectedTower();
    if (!tower || !name.trim()) return;
    this.api.updateTower(tower.id, { name: name.trim() }).subscribe({
      next: (updated) => {
        this.selectedTower.set(updated);
        this.reloadGeometry();
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected async deleteSelectedTower(): Promise<void> {
    const tower = this.selectedTower();
    if (!tower) return;
    const ok = await this.confirmService.confirm({
      title: 'Delete tower?',
      message: `Delete "${tower.name}"? This cannot be undone.`,
      danger: true,
    });
    if (!ok) return;
    this.http.delete(`/api/staff/towers/${tower.id}/`).subscribe({
      next: () => {
        this.notice.set(`Tower "${tower.name}" deleted.`);
        this.selectedTower.set(null);
        this.reloadGeometry();
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  // ---- zone draft lifecycle -------------------------------------------------

  private beginNewZoneDraft(): void {
    this.draftRing = [];
    this.drawingActive = true;
    this.undoStack = [];
    this.canUndo.set(false);
    this.activeVertexIndex = null;
    this.zoneDraftError.set(null);
    this.zoneDraftWarning.set(null);
    this.zoneDraftBlocked.set(false);
    this.zoneDraft.set({
      zoneId: null,
      name: '',
      color: DEFAULT_ZONE_COLOR,
      scoringType: DEFAULT_SCORING_TYPE,
    });
  }

  private enterZoneEdit(zone: AdminZone): void {
    if (this.zoneDraft() || !zone.shape) return;
    const ring = zone.shape.coordinates[0].slice(0, -1) as LngLat[];
    this.draftRing = ring.map((p) => [p[0], p[1]] as LngLat);
    this.drawingActive = false;
    this.undoStack = [];
    this.canUndo.set(false);
    this.activeVertexIndex = null;
    this.zoneDraftError.set(null);
    this.zoneDraft.set({
      zoneId: zone.id,
      name: zone.name,
      color: zone.color,
      scoringType: zone.scoring_type,
    });
    this.renderZones(); // hide the static render of the zone now being edited
    this.rebuildDraftLayer();
  }

  protected updateZoneDraft<K extends keyof ZoneDraftMeta>(field: K, value: ZoneDraftMeta[K]): void {
    const draft = this.zoneDraft();
    if (!draft) return;
    this.zoneDraft.set({ ...draft, [field]: value });
  }

  protected finishDrawing(): void {
    if (this.draftRing.length < 3) return;
    this.drawingActive = false;
    this.rebuildDraftLayer();
  }

  private exitZoneDraft(): void {
    this.zoneDraft.set(null);
    this.draftRing = [];
    this.drawingActive = false;
    this.activeVertexIndex = null;
    this.undoStack = [];
    this.canUndo.set(false);
    this.zoneDraftError.set(null);
    this.zoneDraftWarning.set(null);
    this.zoneDraftBlocked.set(false);
    this.rebuildDraftLayer();
  }

  protected cancelZoneDraft(): void {
    this.exitZoneDraft();
    this.renderZones();
  }

  protected saveZoneDraft(): void {
    const draft = this.zoneDraft();
    if (!draft || this.zoneDraftSaving() || this.zoneDraftBlocked()) return;
    if (this.draftRing.length < 3) {
      this.zoneDraftError.set('Draw at least 3 vertices before saving.');
      return;
    }
    if (!draft.name.trim()) {
      this.zoneDraftError.set('Name is required.');
      return;
    }
    const vertices: [number, number][] = this.draftRing.map(([lng, lat]) => [lng, lat]);
    this.zoneDraftSaving.set(true);
    this.zoneDraftError.set(null);

    if (draft.zoneId === null) {
      const collectionId = this.selectedCollectionId();
      if (!collectionId) {
        this.zoneDraftSaving.set(false);
        this.zoneDraftError.set('Select a collection first — new zones must be filed into one.');
        return;
      }
      this.api
        .createZone({
          name: draft.name.trim(),
          scoring_type: draft.scoringType,
          color: draft.color,
          vertices,
          collection: collectionId,
        })
        .subscribe({
          next: (zone) => this.onZoneSaved(zone),
          error: (err) => this.onZoneSaveError(err),
        });
    } else {
      this.api
        .updateZone(draft.zoneId, {
          name: draft.name.trim(),
          scoring_type: draft.scoringType,
          color: draft.color,
          vertices,
        })
        .subscribe({
          next: (zone) => this.onZoneSaved(zone),
          error: (err) => this.onZoneSaveError(err),
        });
    }
  }

  private onZoneSaved(zone: AdminZone): void {
    this.zoneDraftSaving.set(false);
    this.notice.set(`Zone "${zone.name}" saved.`);
    this.exitZoneDraft();
    this.reloadGeometry();
  }

  private onZoneSaveError(err: unknown): void {
    this.zoneDraftSaving.set(false);
    this.zoneDraftError.set(extractErrorMessage(err));
  }

  protected async deleteZoneDraft(): Promise<void> {
    const draft = this.zoneDraft();
    if (!draft || draft.zoneId === null || this.zoneDraftSaving()) return;
    const ok = await this.confirmService.confirm({
      title: 'Delete zone?',
      message: `Delete "${draft.name}"? This removes it from every collection/game that references it and cannot be undone.`,
      danger: true,
      requireTyping: draft.name,
    });
    if (!ok) return;
    this.zoneDraftSaving.set(true);
    this.http.delete(`/api/staff/zones/${draft.zoneId}/`).subscribe({
      next: () => {
        this.zoneDraftSaving.set(false);
        this.notice.set(`Zone "${draft.name}" deleted.`);
        this.exitZoneDraft();
        this.reloadGeometry();
      },
      error: (err) => {
        this.zoneDraftSaving.set(false);
        this.zoneDraftError.set(extractErrorMessage(err));
      },
    });
  }

  // ---- drawing: click-to-add-vertex phase -----------------------------------

  private handleZoneDrawClick(e: L.LeafletMouseEvent): void {
    const draft = this.zoneDraft();
    if (draft && !this.drawingActive) return; // editing an existing/finished shape; use handles
    if (!draft) this.beginNewZoneDraft();

    if (this.draftRing.length >= 3 && this.map) {
      const first = this.draftRing[0];
      const firstPx = this.map.latLngToContainerPoint(L.latLng(first[1], first[0]));
      const clickPx = this.map.latLngToContainerPoint(e.latlng);
      if (firstPx.distanceTo(clickPx) <= CLOSE_TOLERANCE_PX) {
        this.finishDrawing();
        return;
      }
    }

    const snap = this.trySnap(e.latlng, this.zoneDraft()?.zoneId ?? null);
    const point = snap ?? e.latlng;
    this.pushUndoSnapshot();
    this.draftRing.push([point.lng, point.lat]);
    this.hideSnapIndicator();
    this.rebuildDraftLayer();
  }

  // ---- vertex / midpoint / whole-shape editing -------------------------------

  private makeVertexMarker(pt: LngLat, index: number): L.Marker {
    const marker = L.marker([pt[1], pt[0]], { draggable: true, icon: VERTEX_ICON, zIndexOffset: 1000 });
    marker.on('dragstart', () => this.pushUndoSnapshot());
    marker.on('drag', (ev) => this.onVertexDrag(index, (ev.target as L.Marker).getLatLng()));
    marker.on('dragend', () => this.onVertexDragEnd(index));
    marker.on('contextmenu', (ev: L.LeafletMouseEvent) => {
      L.DomEvent.stopPropagation(ev);
      L.DomEvent.preventDefault(ev.originalEvent);
      this.deleteVertex(index);
    });
    marker.on('click', (ev: L.LeafletMouseEvent) => {
      L.DomEvent.stopPropagation(ev);
      // The vertex handle sits ON TOP of the map at its own pixel, so a
      // click meant to close the ring by hitting vertex 0 directly (the
      // natural reading of "click the first vertex again") would
      // otherwise never reach `handleZoneDrawClick`'s proximity check --
      // it lands on this marker first. Handle the close here too.
      if (this.drawingActive && index === 0 && this.draftRing.length >= 3) {
        this.finishDrawing();
        return;
      }
      this.activeVertexIndex = index;
    });
    return marker;
  }

  private onVertexDrag(index: number, latlng: L.LatLng): void {
    const draft = this.zoneDraft();
    const snap = this.trySnap(latlng, draft?.zoneId ?? null);
    const point = snap ?? latlng;
    if (snap) {
      this.showSnapIndicator(snap);
      this.vertexMarkers[index]?.setLatLng(point);
    } else {
      this.hideSnapIndicator();
    }
    this.draftRing[index] = [point.lng, point.lat];
    this.updateDraftShapeLive();
  }

  private onVertexDragEnd(index: number): void {
    this.hideSnapIndicator();
    this.activeVertexIndex = index;
  }

  protected deleteVertex(index: number): void {
    const ring = this.draftRing;
    if (!this.zoneDraft() || ring.length <= 3) {
      this.zoneDraftError.set('A zone needs at least 3 vertices — delete the whole shape instead.');
      return;
    }
    this.pushUndoSnapshot();
    ring.splice(index, 1);
    if (this.activeVertexIndex !== null && this.activeVertexIndex >= ring.length) {
      this.activeVertexIndex = null;
    }
    this.rebuildDraftLayer();
  }

  private insertVertexAtMidpoint(edgeIndex: number): void {
    this.pushUndoSnapshot();
    const ring = this.draftRing;
    const mid = midpointLngLat(ring[edgeIndex], ring[(edgeIndex + 1) % ring.length]);
    ring.splice(edgeIndex + 1, 0, mid);
    this.rebuildDraftLayer();
  }

  private wirePolygonDrag(polygon: L.Polygon): void {
    polygon.on('mousedown', (e: L.LeafletMouseEvent) => {
      if (this.tool() !== 'select' || !this.map) return;
      L.DomEvent.stopPropagation(e);
      L.DomEvent.preventDefault(e.originalEvent);
      this.pushUndoSnapshot();
      let last = e.latlng;
      const map = this.map;
      map.dragging.disable();
      const onMove = (ev: L.LeafletMouseEvent) => {
        const dLng = ev.latlng.lng - last.lng;
        const dLat = ev.latlng.lat - last.lat;
        last = ev.latlng;
        this.draftRing = this.draftRing.map(([lng, lat]) => [lng + dLng, lat + dLat] as LngLat);
        this.vertexMarkers.forEach((m, i) => {
          const p = this.draftRing[i];
          if (p) m.setLatLng([p[1], p[0]]);
        });
        this.updateDraftShapeLive();
      };
      const onUp = () => {
        map.off('mousemove', onMove);
        map.off('mouseup', onUp);
        map.dragging.enable();
      };
      map.on('mousemove', onMove);
      map.on('mouseup', onUp);
    });
  }

  // ---- undo -----------------------------------------------------------------

  private pushUndoSnapshot(): void {
    this.undoStack.push(this.draftRing.map((p) => [p[0], p[1]] as LngLat));
    if (this.undoStack.length > 50) this.undoStack.shift();
    this.canUndo.set(true);
  }

  protected undo(): void {
    const prev = this.undoStack.pop();
    if (!prev) return;
    this.draftRing = prev;
    this.canUndo.set(this.undoStack.length > 0);
    this.rebuildDraftLayer();
  }

  // ---- snapping ---------------------------------------------------------------

  private trySnap(latlng: L.LatLng, excludeZoneId: number | null): L.LatLng | null {
    if (!this.snapEnabled() || !this.map) return null;
    const tolerance = this.snapTolerancePx();
    const clickPt = this.map.latLngToContainerPoint(latlng);
    let best: L.LatLng | null = null;
    let bestDist = Infinity;

    const consider = (candidate: L.LatLng) => {
      const pt = this.map!.latLngToContainerPoint(candidate);
      const dist = pt.distanceTo(clickPt);
      if (dist <= tolerance && dist < bestDist) {
        bestDist = dist;
        best = candidate;
      }
    };

    for (const tower of this.towers()) {
      if (!tower.location) continue;
      const [lng, lat] = tower.location.coordinates;
      consider(L.latLng(lat, lng));
    }

    for (const zone of this.zones()) {
      if (zone.id === excludeZoneId || !zone.shape) continue;
      const ring = zone.shape.coordinates[0];
      for (let i = 0; i < ring.length - 1; i++) {
        const a = L.latLng(ring[i][1], ring[i][0]);
        const b = L.latLng(ring[i + 1][1], ring[i + 1][0]);
        consider(a);
        consider(this.closestPointOnSegment(latlng, a, b));
      }
    }

    return best;
  }

  private closestPointOnSegment(p: L.LatLng, a: L.LatLng, b: L.LatLng): L.LatLng {
    const map = this.map!;
    const pP = map.latLngToContainerPoint(p);
    const pA = map.latLngToContainerPoint(a);
    const pB = map.latLngToContainerPoint(b);
    const abx = pB.x - pA.x;
    const aby = pB.y - pA.y;
    const lenSq = abx * abx + aby * aby;
    let t = lenSq === 0 ? 0 : ((pP.x - pA.x) * abx + (pP.y - pA.y) * aby) / lenSq;
    t = Math.max(0, Math.min(1, t));
    const closest = L.point(pA.x + abx * t, pA.y + aby * t);
    return map.containerPointToLatLng(closest);
  }

  private showSnapIndicator(latlng: L.LatLng): void {
    if (!this.map) return;
    if (!this.snapIndicator) {
      this.snapIndicator = L.circleMarker(latlng, {
        radius: 7,
        color: this.snapIndicatorColor,
        weight: 2,
        fillColor: this.snapIndicatorColor,
        fillOpacity: 0.3,
        interactive: false,
      }).addTo(this.map);
    } else {
      this.snapIndicator.setLatLng(latlng);
    }
  }

  private hideSnapIndicator(): void {
    if (this.snapIndicator && this.map) {
      this.map.removeLayer(this.snapIndicator);
    }
    this.snapIndicator = null;
  }

  // ---- client-side clip preview (advisory; server is authoritative) --------

  private removeClipPreviewLayer(): void {
    if (this.clipPreviewLayer && this.draftLayerGroup) {
      this.draftLayerGroup.removeLayer(this.clipPreviewLayer);
    }
    this.clipPreviewLayer = null;
  }

  private updateClipPreview(): void {
    this.removeClipPreviewLayer();
    const draft = this.zoneDraft();
    if (!draft || this.drawingActive || this.draftRing.length < 3) {
      this.zoneDraftWarning.set(null);
      this.zoneDraftBlocked.set(false);
      return;
    }
    const others = this.zones().filter((z) => z.id !== draft.zoneId && !!z.shape);
    if (others.length === 0) {
      this.zoneDraftWarning.set(null);
      this.zoneDraftBlocked.set(false);
      return;
    }

    const closedRing = [...this.draftRing, this.draftRing[0]];
    let drawn: ReturnType<typeof turf.polygon>;
    try {
      drawn = turf.polygon([closedRing]);
    } catch {
      // Self-intersecting mid-edit ring; the backend surfaces this on save.
      this.zoneDraftWarning.set(null);
      this.zoneDraftBlocked.set(false);
      return;
    }

    let clipped: ReturnType<typeof turf.difference>;
    try {
      const otherFeatures = others.map((z) => turf.polygon(z.shape!.coordinates as number[][][]));
      clipped = turf.difference(turf.featureCollection([drawn, ...otherFeatures]));
    } catch {
      this.zoneDraftWarning.set(null);
      this.zoneDraftBlocked.set(false);
      return;
    }

    if (!clipped) {
      this.zoneDraftWarning.set(
        'This zone is fully contained within existing zone(s). Existing zones win overlaps — ' +
          'draw outside them, or edit the existing zone instead.',
      );
      this.zoneDraftBlocked.set(true);
      return;
    }

    const drawnArea = turf.area(drawn);
    const clippedArea = turf.area(clipped);
    if (clippedArea < drawnArea * 0.999) {
      this.zoneDraftWarning.set(
        'Overlaps existing zone(s) — the shaded preview is what will actually be saved ' +
          '(existing zones always win).',
      );
      this.zoneDraftBlocked.set(false);
      if (this.draftLayerGroup) {
        this.clipPreviewLayer = L.geoJSON(clipped as unknown as GeoJSON.GeoJsonObject, {
          style: this.clipPreviewStyle(),
        }).addTo(this.draftLayerGroup);
      }
    } else {
      this.zoneDraftWarning.set(null);
      this.zoneDraftBlocked.set(false);
    }
  }

  // ---- rendering ---------------------------------------------------------------

  private renderTowers(): void {
    if (!this.towerLayerGroup) return;
    this.towerLayerGroup.clearLayers();
    const draggableAllowed = this.zoneDraft() === null;
    for (const tower of this.towers()) {
      if (!tower.location) continue;
      const [lng, lat] = tower.location.coordinates;
      const marker = L.marker([lat, lng], {
        icon: towerIcon({ icon: tower.resolved_icon, color: tower.resolved_color }),
        draggable: draggableAllowed,
      });
      marker.bindTooltip(tower.name);
      marker.on('dragstart', () => this.hideSnapIndicator());
      marker.on('drag', (ev) => {
        const snap = this.trySnap((ev.target as L.Marker).getLatLng(), null);
        if (snap) this.showSnapIndicator(snap);
        else this.hideSnapIndicator();
      });
      marker.on('dragend', (ev) => this.onTowerDragEnd(tower, ev.target as L.Marker));
      marker.on('click', (ev: L.LeafletMouseEvent) => {
        // Only capture the click (and stop it reaching the map's own
        // click handler) when 'select' is actually going to use it --
        // otherwise a tower sitting under a zone-draw click would
        // silently swallow the vertex the user meant to place there.
        if (this.tool() === 'select' && !this.zoneDraft()) {
          L.DomEvent.stopPropagation(ev);
          this.selectedTower.set(tower);
        }
      });
      marker.addTo(this.towerLayerGroup);
    }
  }

  private zoneStyle(zone: AdminZone): L.PathOptions {
    const color = zone.color || '#333333';
    return { color, weight: 2, fillColor: color, fillOpacity: 0.18 };
  }

  private renderZones(): void {
    if (!this.zoneLayerGroup) return;
    this.zoneLayerGroup.clearLayers();
    const editingId = this.zoneDraft()?.zoneId ?? null;
    for (const zone of this.zones()) {
      if (!zone.shape || zone.id === editingId) continue;
      const layer = L.geoJSON(zone.shape as unknown as GeoJSON.GeoJsonObject, {
        style: this.zoneStyle(zone),
      });
      layer.bindTooltip(zone.name);
      layer.on('click', (ev: L.LeafletMouseEvent) => {
        // Same rule as the tower marker above: don't swallow the click
        // unless 'select' is actually going to act on it, so drawing a
        // zone vertex (or placing a tower) on top of an existing zone
        // still reaches the map's click handler.
        if (this.tool() === 'select' && !this.zoneDraft()) {
          L.DomEvent.stopPropagation(ev);
          this.enterZoneEdit(zone);
        }
      });
      layer.addTo(this.zoneLayerGroup);
    }
  }

  private draftPolygonStyle(): L.PathOptions {
    return {
      color: this.draftStrokeColor,
      weight: 2,
      dashArray: '6 4',
      fillColor: this.draftStrokeColor,
      fillOpacity: 0.12,
    };
  }

  private draftLineStyle(): L.PathOptions {
    return { color: this.draftStrokeColor, weight: 2, dashArray: '6 4' };
  }

  private clipPreviewStyle(): L.PathOptions {
    return { color: this.clipPreviewColor, weight: 2, fillColor: this.clipPreviewColor, fillOpacity: 0.35 };
  }

  private rebuildDraftLayer(): void {
    this.draftVertexCount.set(this.draftRing.length);
    this.drawingActiveSig.set(this.drawingActive);
    if (!this.draftLayerGroup) return;
    this.draftLayerGroup.clearLayers();
    this.vertexMarkers = [];
    this.midpointMarkers = [];
    this.draftPolygon = null;
    this.draftLine = null;
    this.clipPreviewLayer = null;

    const ring = this.draftRing;
    const latlngs = ring.map(([lng, lat]) => L.latLng(lat, lng));

    if (ring.length >= 3 && !this.drawingActive) {
      this.draftPolygon = L.polygon(latlngs, this.draftPolygonStyle()).addTo(this.draftLayerGroup);
      this.wirePolygonDrag(this.draftPolygon);
    } else if (latlngs.length >= 1) {
      this.draftLine = L.polyline(latlngs, this.draftLineStyle()).addTo(this.draftLayerGroup);
    }

    ring.forEach((pt, index) => {
      const marker = this.makeVertexMarker(pt, index);
      marker.addTo(this.draftLayerGroup!);
      this.vertexMarkers.push(marker);
    });

    if (!this.drawingActive && ring.length >= 3) {
      this.rebuildMidpoints();
    }

    this.updateClipPreview();
  }

  private rebuildMidpoints(): void {
    if (!this.draftLayerGroup) return;
    this.midpointMarkers.forEach((m) => this.draftLayerGroup!.removeLayer(m));
    this.midpointMarkers = [];
    const ring = this.draftRing;
    const n = ring.length;
    for (let i = 0; i < n; i++) {
      const mid = midpointLngLat(ring[i], ring[(i + 1) % n]);
      const marker = L.marker([mid[1], mid[0]], { icon: MIDPOINT_ICON, draggable: false, zIndexOffset: 500 });
      const edgeIndex = i;
      marker.on('click', (ev: L.LeafletMouseEvent) => {
        L.DomEvent.stopPropagation(ev);
        this.insertVertexAtMidpoint(edgeIndex);
      });
      marker.addTo(this.draftLayerGroup);
      this.midpointMarkers.push(marker);
    }
  }

  private updateMidpointPositions(): void {
    if (this.drawingActive) return;
    const ring = this.draftRing;
    const n = ring.length;
    if (this.midpointMarkers.length !== n) return; // structural change pending a rebuild
    this.midpointMarkers.forEach((marker, i) => {
      const mid = midpointLngLat(ring[i], ring[(i + 1) % n]);
      marker.setLatLng([mid[1], mid[0]]);
    });
  }

  private updateDraftShapeLive(): void {
    const latlngs = this.draftRing.map(([lng, lat]) => L.latLng(lat, lng));
    if (this.draftPolygon) {
      this.draftPolygon.setLatLngs(latlngs);
    } else if (this.draftLine) {
      this.draftLine.setLatLngs(latlngs);
    }
    this.updateMidpointPositions();
    this.updateClipPreview();
  }

  // ---- keyboard shortcuts ---------------------------------------------------

  @HostListener('document:keydown', ['$event'])
  protected onKeydown(ev: KeyboardEvent): void {
    if (!this.zoneDraft()) return;
    if (isTextInputFocused()) {
      if (ev.key === 'Escape') this.cancelZoneDraft();
      return;
    }
    if ((ev.key === 'Delete' || ev.key === 'Backspace') && this.activeVertexIndex !== null) {
      ev.preventDefault();
      this.deleteVertex(this.activeVertexIndex);
      return;
    }
    if (ev.key === 'Escape') {
      ev.preventDefault();
      this.cancelZoneDraft();
      return;
    }
    if (ev.key === 'Enter' && this.drawingActive && this.draftRing.length >= 3) {
      ev.preventDefault();
      this.finishDrawing();
      return;
    }
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === 'z') {
      ev.preventDefault();
      this.undo();
    }
  }
}
