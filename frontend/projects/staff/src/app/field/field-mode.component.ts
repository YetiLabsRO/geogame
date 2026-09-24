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
import { firstValueFrom } from 'rxjs';

import {
  AdminChallenge,
  AdminCollection,
  AdminGame,
  AdminTower,
  AdminTowerType,
  AdminZone,
  FieldEdit,
  FieldSyncService,
  MediaAssetInfo,
  MediaKind,
  MediaSubject,
  StaffApiService,
  captureToBytes,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/** One GPS reading feeding the multi-reading average. */
interface Fix {
  lat: number;
  lng: number;
  accuracy: number;
}

/**
 * What media and challenges attach to — the thing in hand.
 *
 * A tower or a zone, identified by a server id or, while it is still
 * queued, by the `localId` the queue gave it. Widening this from
 * "tower" is what lets a curator record the way into a meadow while
 * standing at its gate (tower-zone-media).
 */
interface SubjectContext {
  kind: MediaSubject;
  ref: number | string;
  name: string;
}

/** One attachment on the subject in hand — synced, or still queued. */
interface FieldMedia {
  /** Stable key for tracking; a server id or a queue local id. */
  key: string;
  id: number | null;
  localId: string | null;
  kind: MediaKind;
  durationSeconds: number | null;
}

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const ACCURACY_WARN_M = 15;
/** Untyped paint — mirrors game/models.py's DEFAULT_TOWER_* constants. */
const DEFAULT_TOWER_ICON = 'bi-geo-alt-fill';
const DEFAULT_TOWER_COLOR = '#5F6B7A';
const PHOTO_MAX_DIM = 1280;
const PHOTO_JPEG_QUALITY = 0.75;
/**
 * The duration caps this client enforces, mirroring the documented
 * defaults in `geogame/settings.py`'s `MEDIA_ASSET_LIMITS`.
 *
 * The server is the control; these exist so a recording *stops* at the
 * limit rather than being refused after the fact. Being refused after
 * the fact is the bad case: it happens once the curator has walked away
 * from the place they were describing.
 *
 * An install that raises the server's cap gets a client that still
 * stops early, which is merely conservative. One that lowers it gets
 * clips refused on upload — which is why the rejection names the limit.
 */
const AUDIO_MAX_SECONDS = 180;
const VIDEO_MAX_SECONDS = 30;

/**
 * Field authoring mode (field-authoring-mode tasks 3.1–3.6, 4.2).
 *
 * Mobile, one-handed on-site authoring: drop a tower at the device GPS
 * fix (live accuracy, re-read / averaging / nudge), walk or tap a zone
 * boundary, attach a challenge, and attach reference media — photos,
 * spoken notes and short clips — to whichever of the two is in hand
 * (tower-zone-media). All filed into a target Collection, drafts by
 * default, queued offline.
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
        @if (currentSubject(); as s) {
          <div class="card">
            <div class="card-body py-2 d-grid gap-2">
              <div class="d-flex align-items-center gap-2 flex-wrap">
                <span class="me-auto">
                  <i [class]="s.kind === 'towers' ? 'bi bi-geo-alt' : 'bi bi-pentagon'"></i>
                  {{ s.name }}
                  @if (isQueuedRef(s.ref)) {
                    <span class="badge text-bg-warning ms-1">queued</span>
                  }
                </span>
                @if (recording(); as r) {
                  <!-- While recording, the only control that matters is
                       the one that stops it. Audio stops on release, so
                       its button reports rather than invites a tap. -->
                  <button
                    type="button"
                    class="btn btn-danger"
                    [disabled]="r === 'AUDIO'"
                    (click)="stopRecording()"
                  >
                    <i [class]="r === 'AUDIO' ? 'bi bi-mic-fill me-1' : 'bi bi-stop-fill me-1'"></i>
                    {{ formatDuration(elapsed()) }} / {{ formatDuration(limitFor(r)) }}
                  </button>
                } @else {
                  <button
                    type="button"
                    class="btn btn-outline-secondary"
                    [disabled]="attaching()"
                    (click)="photoInput.click()"
                  >
                    @if (attaching()) {
                      <span class="spinner-border spinner-border-sm me-1"></span>
                    } @else {
                      <i class="bi bi-camera me-1"></i>
                    }
                    Photo
                  </button>
                  @if (canRecord()) {
                    <!-- Hold to speak, as one would a walkie-talkie:
                         a spoken note is short and a curator's other
                         hand is holding a map.

                         Only pointerdown is bound here. The release
                         is caught on the window, because a thumb slides
                         and because this button is replaced by the
                         recording one the instant recording starts: a
                         pointerup bound to an element that no longer
                         exists never arrives, and the recording would
                         run to its cap. -->
                    <button
                      type="button"
                      class="btn btn-outline-secondary"
                      [disabled]="attaching()"
                      (pointerdown)="startRecording('AUDIO')"
                    >
                      <i class="bi bi-mic me-1"></i> Hold to talk
                    </button>
                    <button
                      type="button"
                      class="btn btn-outline-secondary"
                      [disabled]="attaching()"
                      (click)="startRecording('VIDEO')"
                    >
                      <i class="bi bi-camera-video me-1"></i> Clip
                    </button>
                  } @else {
                    <!-- No MediaRecorder here. Offer what this device
                         does have — its own recorder, through a file
                         picker — rather than a button that does nothing. -->
                    <button
                      type="button"
                      class="btn btn-outline-secondary"
                      [disabled]="attaching()"
                      (click)="audioInput.click()"
                    >
                      <i class="bi bi-mic me-1"></i> Audio
                    </button>
                    <button
                      type="button"
                      class="btn btn-outline-secondary"
                      [disabled]="attaching()"
                      (click)="videoInput.click()"
                    >
                      <i class="bi bi-camera-video me-1"></i> Clip
                    </button>
                  }
                  @if (s.kind === 'towers') {
                    <button
                      type="button"
                      class="btn btn-outline-secondary"
                      (click)="openChallengeSheet()"
                    >
                      <i class="bi bi-list-task me-1"></i> Challenge
                    </button>
                  }
                }
              </div>

              <!-- What is attached, and a way to undo a mistake before
                   walking on (tower-zone-media task 5.3). -->
              @if (media().length) {
                <div class="media-strip">
                  @for (m of media(); track m.key) {
                    <span class="media-chip">
                      <i [class]="'bi ' + mediaIcon(m.kind)"></i>
                      @if (m.durationSeconds) {
                        <span>{{ formatDuration(m.durationSeconds) }}</span>
                      }
                      @if (m.localId) {
                        <i class="bi bi-cloud-arrow-up" title="Waiting to sync"></i>
                      }
                      <button
                        type="button"
                        class="btn-close"
                        [attr.aria-label]="'Remove ' + m.kind.toLowerCase()"
                        (click)="removeMedia(m)"
                      ></button>
                    </span>
                  }
                </div>
              } @else if (!recording()) {
                <div class="small text-body-secondary">
                  Nothing attached yet. Clips stop at
                  {{ formatDuration(videoMaxSeconds) }}.
                </div>
              }
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
                Accuracy ±{{ f.accuracy.toFixed(0) }} m is poor — add readings to average, or nudge
                the marker on the map.
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
                This type captures within {{ impliedRadius() }} m but the fix is only accurate to
                ±{{ fix()?.accuracy?.toFixed(0) }} m — players may not be able to reach it. Add
                readings or nudge the marker before saving.
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
            Pan the map to place the crosshair. Saved
            {{ draft() ? 'as inactive draft' : 'active' }}.
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
            {{ vertices().length }} vertices — mark at your GPS position while walking, or tap the
            map. Drag a vertex to correct it.
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
                [disabled]="
                  saving() || vertices().length < 3 || (!editingZone() && !zoneName().trim())
                "
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
                  {{ describeEdit(item) }}
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
          <span class="me-auto">Attach challenge — {{ currentSubject()?.name }}</span>
          <button type="button" class="btn-close" (click)="sheetOpen.set(false)"></button>
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
                <option [ngValue]="c.id">[{{ c.difficulty }}] {{ c.text.slice(0, 60) }}</option>
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
      (change)="onFilePicked($event, 'IMAGE')"
    />
    <!-- Only reachable where MediaRecorder is not; see the panel above. -->
    <input
      #audioInput
      type="file"
      accept="audio/*"
      capture
      class="d-none"
      (change)="onFilePicked($event, 'AUDIO')"
    />
    <input
      #videoInput
      type="file"
      accept="video/*"
      capture="environment"
      class="d-none"
      (change)="onFilePicked($event, 'VIDEO')"
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
    /* The media strip: what is attached to the thing in hand, sized so
       a chip's remove button is hittable with a thumb in a glove. */
    .media-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 0.375rem;
    }
    .media-chip {
      display: inline-flex;
      align-items: center;
      gap: 0.375rem;
      min-height: 2.25rem;
      padding: 0.25rem 0.5rem;
      border: 1px solid var(--border);
      border-radius: 999px;
      font-variant-numeric: tabular-nums;
    }
    .media-chip .btn-close {
      --bs-btn-close-opacity: 0.55;
      padding: 0.35rem;
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
  protected readonly mapContainer = viewChild.required<ElementRef<HTMLDivElement>>('mapContainer');

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
  protected readonly currentSubject = signal<SubjectContext | null>(null);
  // tower-types: one tap applies icon, colour and capture radius.
  protected readonly towerTypes = signal<AdminTowerType[]>([]);
  protected readonly typeId = signal<number | null>(null);
  protected readonly selectedType = computed<AdminTowerType | null>(
    () => this.towerTypes().find((t) => t.id === this.typeId()) ?? null,
  );
  /** Capture radius the chosen type implies; null means the Game default. */
  protected readonly impliedRadius = computed(() => this.selectedType()?.proximity_meters ?? null);
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

  // Reference media on the subject in hand (tower-zone-media)
  protected readonly videoMaxSeconds = VIDEO_MAX_SECONDS;
  protected readonly media = signal<FieldMedia[]>([]);
  protected readonly attaching = signal(false);
  /** Which kind is recording right now, or null. */
  protected readonly recording = signal<MediaKind | null>(null);
  /** Seconds the current recording has run, for the stop button's face. */
  protected readonly elapsed = signal(0);
  /**
   * Whether this device can record in-page.
   *
   * Where it cannot, the panel offers file pickers onto the device's
   * own recorder instead. Showing a mic button that silently fails is
   * worse than showing a different one that works.
   */
  protected readonly canRecord = signal(supportsRecording());
  private recorder: MediaRecorder | null = null;
  private recordedChunks: BlobPart[] = [];
  private recordingTimer: ReturnType<typeof setInterval> | null = null;
  private releaseHandler: (() => void) | null = null;

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
    this.api.listTowerTypes().subscribe({ next: (l) => this.towerTypes.set(l), error: () => {} });
    this.api.listChallenges().subscribe({ next: (l) => this.challenges.set(l), error: () => {} });
    this.api.listGames().subscribe({ next: (l) => this.games.set(l), error: () => {} });

    afterNextRender(() => this.initMap());
    this.destroyRef.onDestroy(() => {
      this.map?.remove();
      // Leaving the page must not leave the microphone live.
      this.stopRecording();
      this.clearRecordingState();
    });
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
          html:
            `<span style="background:${tower.resolved_color}">` +
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
      this.afterTowerSaved({ kind: 'towers', ref: item.localId, name: payload.name }, true);
      return;
    }
    this.saving.set(true);
    this.api.createTower(payload).subscribe({
      next: (tower) => {
        this.saving.set(false);
        this.afterTowerSaved({ kind: 'towers', ref: tower.id, name: tower.name }, false);
      },
      error: (err) => {
        this.saving.set(false);
        if (err?.status === 0) {
          // Network dropped mid-save: fall back to the offline queue.
          const item = this.queue.enqueue('create-tower', payload);
          this.afterTowerSaved({ kind: 'towers', ref: item.localId, name: payload.name }, true);
        } else {
          this.error.set(extractErrorMessage(err));
        }
      },
    });
  }

  private afterTowerSaved(ctx: SubjectContext, queued: boolean): void {
    // The thing just placed becomes context for the next one.
    if (!queued) this.loadExisting();
    this.setSubject(ctx);
    this.towerName.set('');
    this.mode.set('idle');
    this.notice.set(
      queued
        ? `${ctx.name} queued for sync — add media or a challenge now.`
        : `${ctx.name} saved — add media or a challenge now.`,
    );
  }

  /** Make something the subject in hand, and show what it already carries. */
  private setSubject(ctx: SubjectContext): void {
    this.currentSubject.set(ctx);
    this.media.set([]);
    if (typeof ctx.ref === 'number' && this.queue.online()) {
      this.api.listMedia(ctx.kind, ctx.ref).subscribe({
        next: (assets) => {
          // Still the same subject? A slow response must not repopulate
          // the strip for whatever the curator moved on to.
          if (this.currentSubject()?.ref === ctx.ref) {
            this.media.set(assets.map(asFieldMedia));
          }
        },
        error: () => undefined, // an empty strip is the honest fallback
      });
    }
  }

  // ---- Reference media (tower-zone-media task 5) ----------------------------

  protected mediaIcon(kind: MediaKind): string {
    switch (kind) {
      case 'AUDIO':
        return 'bi-mic-fill';
      case 'VIDEO':
        return 'bi-camera-video-fill';
      default:
        return 'bi-image-fill';
    }
  }

  protected limitFor(kind: MediaKind): number {
    return kind === 'VIDEO' ? VIDEO_MAX_SECONDS : AUDIO_MAX_SECONDS;
  }

  protected formatDuration(seconds: number): string {
    const whole = Math.max(0, Math.round(seconds));
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
  }

  /** A file from the camera roll, or from a device recorder we fell back to. */
  protected onFilePicked(event: Event, kind: MediaKind): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    void this.attach(file, kind);
  }

  /**
   * Record in-page, stopping at the cap for the kind.
   *
   * The timer is what enforces the video limit: a curator who records
   * two minutes and is then told thirty seconds was the maximum has
   * lost the two minutes, and is usually no longer standing where they
   * recorded them.
   */
  protected startRecording(kind: MediaKind): void {
    if (this.recording() || this.attaching() || !this.currentSubject()) return;
    if (!this.canRecord()) return;
    this.error.set(null);
    this.recording.set(kind);
    this.elapsed.set(0);
    if (kind === 'AUDIO') this.listenForRelease();

    const wantsVideo = kind === 'VIDEO';
    navigator.mediaDevices
      .getUserMedia(
        wantsVideo ? { audio: true, video: { facingMode: 'environment' } } : { audio: true },
      )
      .then((stream) => {
        // Released while permission was being granted.
        if (this.recording() !== kind) {
          stopTracks(stream);
          return;
        }
        this.recordedChunks = [];
        const recorder = new MediaRecorder(stream);
        this.recorder = recorder;
        recorder.ondataavailable = (event) => {
          if (event.data?.size) this.recordedChunks.push(event.data);
        };
        recorder.onstop = () => {
          stopTracks(stream);
          const captured = new Blob(this.recordedChunks, {
            type: recorder.mimeType || (wantsVideo ? 'video/webm' : 'audio/webm'),
          });
          this.recordedChunks = [];
          this.recorder = null;
          const seconds = this.elapsed();
          this.clearRecordingState();
          if (captured.size > 0) void this.attach(captured, kind, seconds);
        };
        recorder.start();
        const startedAt = Date.now();
        this.recordingTimer = setInterval(() => {
          const seconds = (Date.now() - startedAt) / 1000;
          this.elapsed.set(seconds);
          if (seconds >= this.limitFor(kind)) this.stopRecording();
        }, 200);
      })
      .catch(() => {
        this.clearRecordingState();
        this.error.set('Could not reach the microphone or camera.');
      });
  }

  protected stopRecording(): void {
    if (!this.recording()) return;
    const recorder = this.recorder;
    if (recorder && recorder.state !== 'inactive') {
      recorder.stop(); // `onstop` attaches what was captured
      return;
    }
    // Stopped before the recorder existed — permission is still pending.
    this.clearRecordingState();
  }

  /**
   * Stop an audio note when the finger comes up, wherever it comes up.
   *
   * On the window rather than the button: the button is gone by then,
   * and a thumb that slid off the control still means "I have finished
   * speaking".
   */
  private listenForRelease(): void {
    if (typeof window === 'undefined' || this.releaseHandler) return;
    const handler = () => this.stopRecording();
    this.releaseHandler = handler;
    window.addEventListener('pointerup', handler);
    window.addEventListener('pointercancel', handler);
  }

  private clearRecordingState(): void {
    if (this.recordingTimer !== null) {
      clearInterval(this.recordingTimer);
      this.recordingTimer = null;
    }
    if (this.releaseHandler && typeof window !== 'undefined') {
      window.removeEventListener('pointerup', this.releaseHandler);
      window.removeEventListener('pointercancel', this.releaseHandler);
    }
    this.releaseHandler = null;
    this.recording.set(null);
    this.elapsed.set(0);
  }

  /**
   * Send a capture, or queue it.
   *
   * Online with a server-side subject, it goes as multipart — a clip
   * is the one thing here big enough that base64's extra third is worth
   * avoiding. Otherwise it goes into the queue as bytes and is encoded
   * only when it is finally sent.
   */
  private async attach(
    capture: Blob,
    kind: MediaKind,
    knownDuration: number | null = null,
  ): Promise<void> {
    const subject = this.currentSubject();
    if (!subject) return;
    this.attaching.set(true);
    try {
      const file = kind === 'IMAGE' ? await compressImage(capture) : capture;
      const duration =
        kind === 'IMAGE' ? null : (knownDuration ?? (await measureDuration(file, kind)));

      const limit = this.limitFor(kind);
      if (duration !== null && duration > limit) {
        this.error.set(
          `That ${kind.toLowerCase()} runs ${this.formatDuration(duration)}; ` +
            `the limit is ${this.formatDuration(limit)}.`,
        );
        return;
      }

      if (typeof subject.ref === 'number' && this.queue.online()) {
        const sent = await this.upload(subject, file, kind, duration);
        if (sent) return;
      }
      this.queueCapture(subject, file, kind, duration);
    } catch {
      this.error.set('Could not read that capture.');
    } finally {
      this.attaching.set(false);
    }
  }

  /** True if the server took it; false if the network was the problem. */
  private async upload(
    subject: SubjectContext,
    file: Blob,
    kind: MediaKind,
    duration: number | null,
  ): Promise<boolean> {
    const form = new FormData();
    form.append('file', file, fileNameFor(kind, file.type));
    form.append('kind', kind);
    if (duration !== null) form.append('duration_seconds', String(round1(duration)));
    try {
      const asset = await firstValueFrom(
        this.api.uploadMedia(subject.kind, subject.ref as number, form),
      );
      this.media.update((items) => [...items, asFieldMedia(asset)]);
      return true;
    } catch (err) {
      const status = (err as { status?: number })?.status;
      // A dropped network falls through to the queue; a refusal is the
      // server telling the curator something they need to read.
      if (status !== 0) {
        this.error.set(extractErrorMessage(err));
        return true;
      }
      return false;
    }
  }

  private queueCapture(
    subject: SubjectContext,
    file: Blob,
    kind: MediaKind,
    duration: number | null,
  ): void {
    void captureToBytes(file).then(({ bytes, contentType }) => {
      const item = this.queue.enqueue(
        'upload-media',
        { kind, caption: '', duration_seconds: duration === null ? null : round1(duration) },
        { subjectRef: subject.ref, subject: subject.kind, bytes, contentType },
      );
      this.media.update((items) => [
        ...items,
        {
          key: item.localId,
          id: null,
          localId: item.localId,
          kind,
          durationSeconds: duration,
        },
      ]);
    });
  }

  protected removeMedia(item: FieldMedia): void {
    const subject = this.currentSubject();
    if (!subject) return;
    if (item.localId) {
      // Never sent; dropping the queue entry is the whole removal.
      this.queue.discard(item.localId);
      this.media.update((items) => items.filter((m) => m.key !== item.key));
      return;
    }
    if (item.id === null || typeof subject.ref !== 'number') return;
    this.api.deleteMedia(subject.kind, subject.ref, item.id).subscribe({
      next: () => this.media.update((items) => items.filter((m) => m.key !== item.key)),
      error: (err) => this.error.set(extractErrorMessage(err)),
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
      existing?.shape?.coordinates?.[0]?.map((pt) => [pt[0], pt[1]] as [number, number]) ?? [];
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
      const ctx: SubjectContext = {
        kind: 'zones',
        ref: existing.id,
        name: existing.name,
      };
      if (!this.queue.online()) {
        this.queue.enqueue('adjust-zone', payload);
        this.afterZoneSaved(ctx, true);
        return;
      }
      this.saving.set(true);
      this.api.updateZone(existing.id, { vertices: verts }).subscribe({
        next: () => {
          this.saving.set(false);
          this.afterZoneSaved(ctx, false);
        },
        error: (err) => {
          this.saving.set(false);
          if (err?.status === 0) {
            this.queue.enqueue('adjust-zone', payload);
            this.afterZoneSaved(ctx, true);
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
      const item = this.queue.enqueue('create-zone', payload);
      this.afterZoneSaved({ kind: 'zones', ref: item.localId, name: payload.name }, true);
      return;
    }
    this.saving.set(true);
    this.api.createZone(payload).subscribe({
      next: (zone) => {
        this.saving.set(false);
        this.zones.update((zs) => [...zs, zone]);
        this.afterZoneSaved({ kind: 'zones', ref: zone.id, name: zone.name }, false);
      },
      error: (err) => {
        this.saving.set(false);
        if (err?.status === 0) {
          const item = this.queue.enqueue('create-zone', payload);
          this.afterZoneSaved({ kind: 'zones', ref: item.localId, name: payload.name }, true);
        } else {
          this.error.set(extractErrorMessage(err));
        }
      },
    });
  }

  /**
   * A zone that has just been drawn becomes the subject in hand.
   *
   * The curator is standing at its edge with the thing fresh in mind,
   * which is the only moment "enter by the north gate" gets recorded at
   * all (tower-zone-media task 5.4).
   */
  private afterZoneSaved(ctx: SubjectContext, queued: boolean): void {
    this.mode.set('idle');
    this.editingZone.set(null);
    this.vertices.set([]);
    this.redrawZone();
    this.setSubject(ctx);
    if (!queued) this.loadExisting();
    this.notice.set(
      queued
        ? `Zone ${ctx.name} queued for sync — add media now.`
        : `Zone ${ctx.name} saved — add media now.`,
    );
  }

  // ---- Attach challenge (task 3.5) -----------------------------------------

  protected openChallengeSheet(): void {
    this.sheetOpen.set(true);
    this.challengeId.set(null);
    this.challengeText.set('');
  }

  protected saveChallenge(): void {
    const tower = this.currentSubject();
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
      this.queue.enqueue('attach-challenge', payload, {
        subjectRef: tower.ref,
        subject: 'towers',
      });
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
          this.queue.enqueue('attach-challenge', payload, {
            subjectRef: tower.ref,
            subject: 'towers',
          });
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

  protected describeEdit(item: FieldEdit): string {
    if (item.kind === 'upload-media') {
      // Which kind matters here: three chips reading "Reference media"
      // tell a curator nothing about what is still unsent.
      switch (item.payload['kind']) {
        case 'AUDIO':
          return 'Audio note';
        case 'VIDEO':
          return 'Video clip';
        default:
          return 'Reference photo';
      }
    }
    switch (item.kind) {
      case 'create-tower':
        return 'New tower';
      case 'create-zone':
        return 'New zone';
      case 'adjust-zone':
        return 'Zone boundary';
      case 'attach-challenge':
        return 'Challenge link';
      default:
        return item.kind;
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

/**
 * Downscale and JPEG-compress a captured photo.
 *
 * Done on the device because that is where the bandwidth is worth
 * saving: a curator on a hillside is on mobile data, and a phone camera
 * produces several megabytes of detail nobody needs to recognise a
 * fountain.
 */
function compressImage(source: Blob): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(source);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      const scale = Math.min(1, PHOTO_MAX_DIM / Math.max(img.width, img.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(img.width * scale);
      canvas.height = Math.round(img.height * scale);
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        reject(new Error('canvas unavailable'));
        return;
      }
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (blob) => (blob ? resolve(blob) : reject(new Error('compression failed'))),
        'image/jpeg',
        PHOTO_JPEG_QUALITY,
      );
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('image load failed'));
    };
    img.src = url;
  });
}

/** Whether this device can record audio and video in the page itself. */
function supportsRecording(): boolean {
  return (
    typeof MediaRecorder !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    typeof navigator.mediaDevices?.getUserMedia === 'function'
  );
}

/** Release the microphone and camera; the indicator light matters. */
function stopTracks(stream: MediaStream): void {
  for (const track of stream.getTracks()) track.stop();
}

/**
 * How long a capture runs, read from the browser's own decoder.
 *
 * Only needed for a file the device recorded for us — an in-page
 * recording has already been timed. Resolves to null rather than
 * failing: an unknown duration is allowed, and the server's cap still
 * applies to the size.
 */
function measureDuration(capture: Blob, kind: MediaKind): Promise<number | null> {
  return new Promise((resolve) => {
    const element = document.createElement(kind === 'VIDEO' ? 'video' : 'audio');
    const url = URL.createObjectURL(capture);
    const settle = (value: number | null) => {
      URL.revokeObjectURL(url);
      resolve(value);
    };
    element.preload = 'metadata';
    element.onloadedmetadata = () =>
      settle(Number.isFinite(element.duration) ? element.duration : null);
    element.onerror = () => settle(null);
    element.src = url;
  });
}

function asFieldMedia(asset: MediaAssetInfo): FieldMedia {
  return {
    key: `server-${asset.id}`,
    id: asset.id,
    localId: null,
    kind: asset.kind,
    durationSeconds: asset.duration_seconds,
  };
}

/**
 * A name for a capture that never had one.
 *
 * The server determines the kind from the declared content type, but a
 * stored file with a sensible extension is one an administrator can
 * recognise in a bucket listing six months later.
 */
function fileNameFor(kind: MediaKind, contentType: string): string {
  const subtype = contentType.split('/')[1]?.split(';')[0] || 'bin';
  // The token is only so that a morning's captures do not all arrive
  // called `image-capture.jpeg` and get de-duplicated into
  // `image-capture_a1B2c3.jpeg` by the storage backend.
  const token = Math.random().toString(36).slice(2, 8);
  return `${kind.toLowerCase()}-${token}.${subtype}`;
}
