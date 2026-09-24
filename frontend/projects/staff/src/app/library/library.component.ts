import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import * as L from 'leaflet';

import {
  LibraryCollection,
  LibraryFeed,
  LibraryTower,
  LibraryZone,
  PageHeaderComponent,
  StaffApiService,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 14;

/** What the inspector is pointed at. */
type Selection =
  | { kind: 'tower'; tower: LibraryTower }
  | { kind: 'zone'; zone: LibraryZone }
  | null;

/**
 * The map-first library (library-map capability).
 *
 * The page this replaces curated geographic assets through two
 * dropdowns of names and two lists of names. Every question a curator
 * actually asks it — do these belong together, is this one an outlier,
 * does this zone contain those towers — is spatial, and no arrangement
 * of those controls answers a spatial question. So the library is drawn.
 *
 * The map shows *everything*, and the selected Collection is a
 * highlight over it. That is deliberate: the interesting information is
 * what is NOT in the collection yet — the tower two streets over that
 * ought to be, the one four kilometres away that ought not — and a map
 * showing only members cannot show you either.
 */
@Component({
  selector: 'app-library',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, PageHeaderComponent],
  template: `
    <app-page-header
      title="Library"
      subtitle="Every tower and zone in the repository. Pick a collection to see and change what it holds."
    />

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    <div class="library">
      <div class="map-column">
        <div #mapContainer class="map"></div>
        @if (busy()) {
          <div class="map-busy"><span class="spinner-border spinner-border-sm"></span></div>
        }
        <div class="legend">
          @if (activeCollection(); as c) {
            <strong>{{ c.name }}</strong> · {{ c.tower_count }} towers,
            {{ c.zone_count }} zones · tap an element to add or remove it
          } @else {
            Showing the whole library · pick a collection to curate it
          }
        </div>
      </div>

      <aside class="panel">
        <div class="panel-block">
          <label class="form-label small mb-1" for="lib-collection">Collection</label>
          <select
            id="lib-collection"
            class="form-select form-select-sm"
            [ngModel]="collectionId()"
            (ngModelChange)="collectionId.set($event === null ? null : +$event)"
          >
            <option [ngValue]="null">— whole library —</option>
            @for (c of collections(); track c.id) {
              <option [ngValue]="c.id">
                {{ c.name }} ({{ c.tower_count }}/{{ c.zone_count }})
              </option>
            }
          </select>

          @if (creating()) {
            <div class="d-flex gap-1 mt-2">
              <input
                class="form-control form-control-sm"
                placeholder="New collection name"
                [ngModel]="newName()"
                (ngModelChange)="newName.set($event)"
              />
              <button
                type="button"
                class="btn btn-sm btn-primary"
                [disabled]="!newName().trim() || busy()"
                (click)="createCollection()"
              >
                Add
              </button>
              <button
                type="button"
                class="btn btn-sm btn-outline-secondary"
                (click)="creating.set(false)"
              >
                ✕
              </button>
            </div>
          } @else {
            <button
              type="button"
              class="btn btn-sm btn-link p-0 mt-1"
              (click)="creating.set(true)"
            >
              + new collection
            </button>
          }
        </div>

        <div class="panel-block">
          <input
            class="form-control form-control-sm mb-2"
            placeholder="Search by name…"
            [ngModel]="search()"
            (ngModelChange)="search.set($event)"
            aria-label="Search the library"
          />
          <select
            class="form-select form-select-sm"
            [ngModel]="typeFilter()"
            (ngModelChange)="typeFilter.set($event === null ? null : +$event)"
            aria-label="Filter by tower type"
          >
            <option [ngValue]="null">any type</option>
            @for (t of towerTypes(); track t.id) {
              <option [ngValue]="t.id">{{ t.name }}</option>
            }
            <option [ngValue]="-1">untyped</option>
          </select>
        </div>

        @if (selection(); as sel) {
          <div class="panel-block inspector">
            @if (sel.kind === 'tower') {
              <div class="d-flex align-items-center gap-2 mb-1">
                <span class="swatch" [style.background-color]="sel.tower.color">
                  <i class="bi" [class]="sel.tower.icon"></i>
                </span>
                <strong>{{ sel.tower.name }}</strong>
              </div>
              <div class="small text-body-secondary">
                {{ sel.tower.tower_type_name ?? 'untyped' }} ·
                {{ sel.tower.media_count }} media
                @if (!sel.tower.is_active) {
                  · <span class="badge text-bg-secondary">draft</span>
                }
              </div>
              <div class="small mt-2">
                <!-- Naming every collection an element belongs to is what
                     stops "remove" reading as "delete" — the single most
                     dangerous misreading available on this page. -->
                In {{ membershipNames(sel.tower.collection_ids).length }} collection(s):
                {{ membershipNames(sel.tower.collection_ids).join(', ') || '—' }}
              </div>
              @if (activeCollection(); as c) {
                <button
                  type="button"
                  class="btn btn-sm w-100 mt-2"
                  [class.btn-outline-danger]="isMember(sel.tower.collection_ids)"
                  [class.btn-primary]="!isMember(sel.tower.collection_ids)"
                  [disabled]="busy()"
                  (click)="toggleTower(sel.tower)"
                >
                  {{ isMember(sel.tower.collection_ids) ? 'Remove from' : 'Add to' }}
                  {{ c.name }}
                </button>
                <div class="form-text">
                  Membership only. The tower stays in the repository either way.
                </div>
              }
            } @else {
              <div class="d-flex align-items-center gap-2 mb-1">
                <span class="swatch square" [style.background-color]="sel.zone.color"></span>
                <strong>{{ sel.zone.name }}</strong>
              </div>
              <div class="small mt-2">
                In {{ membershipNames(sel.zone.collection_ids).length }} collection(s):
                {{ membershipNames(sel.zone.collection_ids).join(', ') || '—' }}
              </div>
              @if (activeCollection(); as c) {
                <button
                  type="button"
                  class="btn btn-sm w-100 mt-2"
                  [class.btn-outline-danger]="isMember(sel.zone.collection_ids)"
                  [class.btn-primary]="!isMember(sel.zone.collection_ids)"
                  [disabled]="busy()"
                  (click)="toggleZone(sel.zone)"
                >
                  {{ isMember(sel.zone.collection_ids) ? 'Remove from' : 'Add to' }}
                  {{ c.name }}
                </button>
                <div class="form-text">
                  Membership only. The zone stays in the repository either way.
                </div>
              }
            }
          </div>
        }

        <div class="panel-block grow">
          <div class="small text-body-secondary mb-1">
            {{ filteredTowers().length }} tower(s), {{ filteredZones().length }} zone(s)
          </div>
          <ul class="element-list">
            @for (t of filteredTowers(); track t.id) {
              <li
                class="element"
                [class.selected]="selectedTowerId() === t.id"
                [class.member]="isMember(t.collection_ids)"
              >
                <button type="button" class="element-btn" (click)="focusTower(t)">
                  <span class="swatch" [style.background-color]="t.color">
                    <i class="bi" [class]="t.icon"></i>
                  </span>
                  <span class="element-name">{{ t.name }}</span>
                  @if (isMember(t.collection_ids)) {
                    <i class="bi bi-check-lg text-success"></i>
                  }
                </button>
              </li>
            }
            @for (z of filteredZones(); track 'z' + z.id) {
              <li
                class="element"
                [class.selected]="selectedZoneId() === z.id"
                [class.member]="isMember(z.collection_ids)"
              >
                <button type="button" class="element-btn" (click)="focusZone(z)">
                  <span class="swatch square" [style.background-color]="z.color"></span>
                  <span class="element-name">{{ z.name }}</span>
                  @if (isMember(z.collection_ids)) {
                    <i class="bi bi-check-lg text-success"></i>
                  }
                </button>
              </li>
            }
            @if (filteredTowers().length === 0 && filteredZones().length === 0) {
              <li class="text-body-secondary small">Nothing matches.</li>
            }
          </ul>
        </div>
      </aside>
    </div>
  `,
  styleUrl: './library.component.scss',
})
export class LibraryComponent {
  private readonly api = inject(StaffApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly mapContainer = viewChild<ElementRef<HTMLDivElement>>('mapContainer');

  protected readonly feed = signal<LibraryFeed | null>(null);
  protected readonly collectionId = signal<number | null>(null);
  protected readonly search = signal('');
  protected readonly typeFilter = signal<number | null>(null);
  protected readonly selection = signal<Selection>(null);
  protected readonly busy = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly newName = signal('');

  private map: L.Map | null = null;
  private towerLayer: L.LayerGroup | null = null;
  private zoneLayer: L.LayerGroup | null = null;
  private fitted = false;

  protected readonly collections = computed(() => this.feed()?.collections ?? []);
  protected readonly towerTypes = computed(() => this.feed()?.tower_types ?? []);
  protected readonly activeCollection = computed<LibraryCollection | null>(
    () => this.collections().find((c) => c.id === this.collectionId()) ?? null,
  );
  protected readonly selectedTowerId = computed(() => {
    const sel = this.selection();
    return sel?.kind === 'tower' ? sel.tower.id : null;
  });
  protected readonly selectedZoneId = computed(() => {
    const sel = this.selection();
    return sel?.kind === 'zone' ? sel.zone.id : null;
  });

  private matchesSearch(name: string): boolean {
    const needle = this.search().trim().toLowerCase();
    return !needle || name.toLowerCase().includes(needle);
  }

  protected readonly filteredTowers = computed(() => {
    const type = this.typeFilter();
    return (this.feed()?.towers ?? []).filter((t) => {
      if (!this.matchesSearch(t.name)) return false;
      if (type === null) return true;
      // -1 is the explicit "untyped" bucket, which is a real thing to
      // want to see: it is the work not yet classified.
      return type === -1 ? t.tower_type === null : t.tower_type === type;
    });
  });

  protected readonly filteredZones = computed(() =>
    // Zones carry no type, so the type filter narrowing to one kind of
    // tower means zones are not what is being looked for.
    this.typeFilter() === null
      ? (this.feed()?.zones ?? []).filter((z) => this.matchesSearch(z.name))
      : [],
  );

  constructor() {
    this.load();

    effect(() => {
      const host = this.mapContainer()?.nativeElement;
      if (host && !this.map) this.initMap(host);
    });

    effect(() => {
      // Repaint on new data, a different collection, or a new filter.
      this.feed();
      this.collectionId();
      this.filteredTowers();
      this.filteredZones();
      this.selection();
      this.render();
    });

    this.destroyRef.onDestroy(() => {
      this.map?.remove();
      this.map = null;
    });
  }

  private load(): void {
    this.api.library().subscribe({
      next: (feed) => {
        this.feed.set(feed);
        this.loadError.set(null);
        if (!this.fitted) {
          this.fitToContent();
          this.fitted = true;
        }
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected isMember(collectionIds: number[]): boolean {
    const id = this.collectionId();
    return id !== null && collectionIds.includes(id);
  }

  protected membershipNames(collectionIds: number[]): string[] {
    const byId = new Map(this.collections().map((c) => [c.id, c.name]));
    return collectionIds.map((id) => byId.get(id) ?? `#${id}`);
  }

  // ---- membership ---------------------------------------------------------

  protected toggleTower(tower: LibraryTower): void {
    const id = this.collectionId();
    if (id === null || this.busy()) return;
    const member = tower.collection_ids.includes(id);
    this.busy.set(true);
    const request = member
      ? this.api.removeCollectionTowers(id, [tower.id])
      : this.api.addCollectionTowers(id, [tower.id]);
    request.subscribe({
      next: () => this.afterMembershipChange(),
      error: (err) => {
        this.busy.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected toggleZone(zone: LibraryZone): void {
    const id = this.collectionId();
    if (id === null || this.busy()) return;
    const member = zone.collection_ids.includes(id);
    this.busy.set(true);
    const request = member
      ? this.api.removeCollectionZones(id, [zone.id])
      : this.api.addCollectionZones(id, [zone.id]);
    request.subscribe({
      next: () => this.afterMembershipChange(),
      error: (err) => {
        this.busy.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  /** Refetch rather than patch locally: counts, membership and the
      selection all have to agree, and the feed is one request. */
  private afterMembershipChange(): void {
    this.api.library().subscribe({
      next: (feed) => {
        this.feed.set(feed);
        this.busy.set(false);
        // Keep the inspector pointed at the same element, now updated.
        const sel = this.selection();
        if (sel?.kind === 'tower') {
          const fresh = feed.towers.find((t) => t.id === sel.tower.id);
          this.selection.set(fresh ? { kind: 'tower', tower: fresh } : null);
        } else if (sel?.kind === 'zone') {
          const fresh = feed.zones.find((z) => z.id === sel.zone.id);
          this.selection.set(fresh ? { kind: 'zone', zone: fresh } : null);
        }
      },
      error: (err) => {
        this.busy.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected createCollection(): void {
    const name = this.newName().trim();
    if (!name) return;
    this.busy.set(true);
    this.api.createCollection({ name }).subscribe({
      next: (created) => {
        this.creating.set(false);
        this.newName.set('');
        this.busy.set(false);
        this.collectionId.set(created.id);
        this.load();
      },
      error: (err) => {
        this.busy.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  // ---- map ----------------------------------------------------------------

  protected focusTower(tower: LibraryTower): void {
    this.selection.set({ kind: 'tower', tower });
    if (tower.lat !== null && tower.lng !== null) {
      this.map?.setView([tower.lat, tower.lng], Math.max(this.map.getZoom(), 16));
    }
  }

  protected focusZone(zone: LibraryZone): void {
    this.selection.set({ kind: 'zone', zone });
    if (!zone.shape || !this.map) return;
    try {
      const layer = L.geoJSON(JSON.parse(zone.shape) as GeoJSON.GeometryObject);
      this.map.fitBounds(layer.getBounds().pad(0.2));
    } catch {
      /* unparseable geometry just doesn't move the map */
    }
  }

  private initMap(container: HTMLElement): void {
    this.map = L.map(container).setView(FALLBACK_CENTER, FALLBACK_ZOOM);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);
    this.zoneLayer = L.layerGroup().addTo(this.map);
    this.towerLayer = L.layerGroup().addTo(this.map);
    this.render();
    this.fitToContent();
    this.fitted = true;
  }

  private render(): void {
    if (!this.map || !this.towerLayer || !this.zoneLayer) return;
    const curating = this.collectionId() !== null;

    this.zoneLayer.clearLayers();
    for (const zone of this.filteredZones()) {
      if (!zone.shape) continue;
      const member = this.isMember(zone.collection_ids);
      const selected = this.selectedZoneId() === zone.id;
      try {
        L.geoJSON(JSON.parse(zone.shape) as GeoJSON.GeometryObject, {
          style: {
            color: zone.color || '#5F6B7A',
            weight: selected ? 4 : member ? 3 : 1,
            // Not a member while curating reads as background: present,
            // so you can see it is there to add, but not competing.
            opacity: !curating || member ? 1 : 0.45,
            fillOpacity: member ? 0.25 : 0.06,
          },
        })
          .bindTooltip(zone.name)
          .on('click', () => this.focusZone(zone))
          .addTo(this.zoneLayer);
      } catch {
        /* skip a zone rather than lose the map */
      }
    }

    this.towerLayer.clearLayers();
    for (const tower of this.filteredTowers()) {
      if (tower.lat === null || tower.lng === null) continue;
      const member = this.isMember(tower.collection_ids);
      const selected = this.selectedTowerId() === tower.id;
      const classes = [
        'tower-pin',
        curating && !member ? 'muted' : '',
        member ? 'member' : '',
        selected ? 'selected' : '',
      ]
        .filter(Boolean)
        .join(' ');
      L.marker([tower.lat, tower.lng], {
        icon: L.divIcon({
          className: classes,
          html: `<span style="background:${tower.color}"><i class="bi ${tower.icon}"></i></span>`,
          iconSize: [32, 32],
          iconAnchor: [16, 16],
        }),
        zIndexOffset: selected ? 1000 : member ? 500 : 0,
      })
        .bindTooltip(`${tower.name}${member ? ' — in this collection' : ''}`)
        .on('click', () => this.focusTower(tower))
        .addTo(this.towerLayer);
    }
  }

  private fitToContent(): void {
    const feed = this.feed();
    if (!this.map || !feed) return;
    const points: [number, number][] = feed.towers
      .filter((t) => t.lat !== null && t.lng !== null)
      .map((t) => [t.lat as number, t.lng as number]);
    if (!points.length) return;
    this.map.fitBounds(L.latLngBounds(points).pad(0.2));
  }
}
