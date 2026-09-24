import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  AdminTowerType,
  ConfirmService,
  InfoHintComponent,
  PageHeaderComponent,
  StaffApiService,
  TowerTypePayload,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/**
 * A working set of Bootstrap Icons for places a scouting game visits.
 *
 * Offered rather than imposed: the field is a free class name, so any
 * `bi-*` works. These are the ones that come up, ordered roughly by how
 * often — a curator outdoors should find "fountain" without scrolling.
 */
const ICON_SUGGESTIONS = [
  'bi-geo-alt-fill', 'bi-droplet-fill', 'bi-building', 'bi-tree-fill',
  'bi-bank', 'bi-shop', 'bi-signpost-2-fill', 'bi-bricks',
  'bi-house-door-fill', 'bi-flag-fill', 'bi-cone-striped', 'bi-water',
  'bi-mountain', 'bi-bridge', 'bi-door-open-fill', 'bi-lamp-fill',
  'bi-camera-fill', 'bi-book-fill', 'bi-hospital', 'bi-train-front-fill',
  'bi-car-front-fill', 'bi-bicycle', 'bi-cup-hot-fill', 'bi-star-fill',
];

interface Draft {
  name: string;
  slug: string;
  icon: string;
  color: string;
  proximity_meters: number | null;
  description: string;
}

function emptyDraft(): Draft {
  return {
    name: '',
    slug: '',
    icon: 'bi-geo-alt-fill',
    color: '#5F6B7A',
    proximity_meters: null,
    description: '',
  };
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80);
}

/**
 * Tower types (tower-types capability).
 *
 * A curator describes a kind of place once — icon, colour, and the
 * capture radius that kind implies — and then applies it with one tap
 * in the field. Every row renders as it will appear on a map rather
 * than as its icon's name, because `bi-droplet-fill` tells you nothing
 * about whether you picked the right icon.
 */
@Component({
  selector: 'app-tower-types',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, PageHeaderComponent, InfoHintComponent],
  template: `
    <app-page-header
      title="Tower types"
      subtitle="A kind of place, described once: icon, colour, and the capture radius it implies."
    />

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    <div class="card mb-4">
      <div class="card-body">
        <h2 class="h6 mb-3">
          {{ editing() ? 'Edit type' : 'New type' }}
          <app-info-hint
            text="Types carry defaults; any single tower can override its icon or colour without leaving the type. A blank capture radius means the type has no opinion and the Game default applies."
          />
        </h2>

        @if (formError(); as msg) {
          <div class="alert alert-danger py-2">{{ msg }}</div>
        }

        <div class="row g-3">
          <div class="col-md-4">
            <label class="form-label small mb-1" for="tt-name">Name</label>
            <input
              id="tt-name"
              class="form-control"
              placeholder="Fountain"
              [ngModel]="draft().name"
              (ngModelChange)="setName($event)"
            />
          </div>
          <div class="col-md-3">
            <label class="form-label small mb-1" for="tt-slug">Slug</label>
            <input
              id="tt-slug"
              class="form-control font-monospace"
              placeholder="fountain"
              [ngModel]="draft().slug"
              (ngModelChange)="patch({ slug: $event })"
            />
          </div>
          <div class="col-md-2">
            <label class="form-label small mb-1" for="tt-color">Colour</label>
            <input
              id="tt-color"
              type="color"
              class="form-control form-control-color w-100"
              [ngModel]="draft().color"
              (ngModelChange)="patch({ color: $event })"
            />
          </div>
          <div class="col-md-3">
            <label class="form-label small mb-1" for="tt-radius">
              Capture radius (m)
            </label>
            <input
              id="tt-radius"
              type="number"
              min="1"
              class="form-control"
              placeholder="Game default"
              [ngModel]="draft().proximity_meters"
              (ngModelChange)="patch({ proximity_meters: $event === null || $event === '' ? null : +$event })"
            />
          </div>

          <div class="col-12">
            <label class="form-label small mb-1">Icon</label>
            <div class="d-flex align-items-center gap-2 mb-2">
              <span class="icon-preview" [style.background-color]="draft().color">
                <i class="bi" [class]="draft().icon"></i>
              </span>
              <input
                class="form-control font-monospace"
                style="max-width: 18rem"
                [ngModel]="draft().icon"
                (ngModelChange)="patch({ icon: $event })"
                aria-label="Icon class name"
              />
              <input
                class="form-control"
                style="max-width: 14rem"
                placeholder="Filter icons…"
                [ngModel]="iconFilter()"
                (ngModelChange)="iconFilter.set($event)"
                aria-label="Filter icons"
              />
            </div>
            <div class="icon-grid">
              @for (icon of filteredIcons(); track icon) {
                <button
                  type="button"
                  class="icon-choice"
                  [class.selected]="draft().icon === icon"
                  [title]="icon"
                  [attr.aria-label]="icon"
                  [attr.aria-pressed]="draft().icon === icon"
                  (click)="patch({ icon })"
                >
                  <i class="bi" [class]="icon"></i>
                </button>
              } @empty {
                <span class="text-body-secondary small">
                  No suggestion matches — any <code>bi-*</code> class name works in the field above.
                </span>
              }
            </div>
          </div>

          <div class="col-12">
            <label class="form-label small mb-1" for="tt-desc">Notes (optional)</label>
            <input
              id="tt-desc"
              class="form-control"
              placeholder="Public drinking fountains and wells"
              [ngModel]="draft().description"
              (ngModelChange)="patch({ description: $event })"
            />
          </div>
        </div>

        <div class="d-flex gap-2 mt-3">
          <button
            type="button"
            class="btn btn-primary"
            [disabled]="busy() || !draft().name.trim()"
            (click)="save()"
          >
            @if (busy()) {
              <span class="spinner-border spinner-border-sm me-1"></span>
            }
            {{ editing() ? 'Save changes' : 'Create type' }}
          </button>
          @if (editing()) {
            <button type="button" class="btn btn-outline-secondary" (click)="cancelEdit()">
              Cancel
            </button>
          }
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-body">
        <h2 class="h6 mb-3">{{ types().length }} type(s)</h2>
        @if (types().length === 0) {
          <p class="text-body-secondary small mb-0">
            No types yet. Towers without a type render in the neutral default.
          </p>
        } @else {
          <div class="table-responsive">
            <table class="table table-sm align-middle mb-0">
              <thead>
                <tr>
                  <th style="width: 3rem"></th>
                  <th>Name</th>
                  <th>Slug</th>
                  <th class="text-end">Radius</th>
                  <th class="text-end">Towers</th>
                  <th>Notes</th>
                  <th class="text-end">Actions</th>
                </tr>
              </thead>
              <tbody>
                @for (t of types(); track t.id) {
                  <tr>
                    <td>
                      <!-- Rendered as it will appear on a map: the icon's
                           class name says nothing about whether it is right. -->
                      <span class="icon-preview" [style.background-color]="t.color">
                        <i class="bi" [class]="t.icon"></i>
                      </span>
                    </td>
                    <td class="fw-semibold">{{ t.name }}</td>
                    <td class="small font-monospace text-body-secondary">{{ t.slug }}</td>
                    <td class="text-end small">
                      {{ t.proximity_meters === null ? 'Game default' : t.proximity_meters + ' m' }}
                    </td>
                    <td class="text-end">{{ t.tower_count }}</td>
                    <td class="small text-body-secondary">{{ t.description || '—' }}</td>
                    <td class="text-end">
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-secondary me-1"
                        (click)="startEdit(t)"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-danger"
                        [disabled]="busy()"
                        (click)="remove(t)"
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </div>
    </div>
  `,
  styles: [
    `
      .icon-preview {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 2rem;
        height: 2rem;
        border-radius: 50%;
        color: #fff;
        /* A ring, so a pale type colour still reads against the panel. */
        box-shadow: inset 0 0 0 1px rgb(0 0 0 / 25%);
      }

      .icon-grid {
        display: flex;
        flex-wrap: wrap;
        gap: 0.25rem;
      }

      .icon-choice {
        width: 2.25rem;
        height: 2.25rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid var(--border);
        border-radius: var(--radius-sm);
        background: var(--panel);
        color: var(--ink);
      }

      .icon-choice:hover {
        background: var(--panel-sunken);
      }

      .icon-choice.selected {
        border-color: var(--primary);
        box-shadow: inset 0 0 0 1px var(--primary);
        color: var(--primary-strong);
      }
    `,
  ],
})
export class TowerTypesComponent {
  private readonly api = inject(StaffApiService);
  private readonly confirmService = inject(ConfirmService);

  protected readonly types = signal<AdminTowerType[]>([]);
  protected readonly draft = signal<Draft>(emptyDraft());
  protected readonly editing = signal<AdminTowerType | null>(null);
  protected readonly busy = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly formError = signal<string | null>(null);
  protected readonly iconFilter = signal('');

  protected readonly filteredIcons = computed(() => {
    const needle = this.iconFilter().trim().toLowerCase();
    if (!needle) return ICON_SUGGESTIONS;
    return ICON_SUGGESTIONS.filter((icon) => icon.includes(needle));
  });

  constructor() {
    this.refresh();
  }

  private refresh(): void {
    this.api.listTowerTypes().subscribe({
      next: (list) => this.types.set(list),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  protected patch(part: Partial<Draft>): void {
    this.draft.update((d) => ({ ...d, ...part }));
  }

  protected setName(name: string): void {
    // Only autofill the slug while it is still following the name, so
    // editing a slug by hand is never undone by a later name tweak.
    const current = this.draft();
    const following = current.slug === '' || current.slug === slugify(current.name);
    this.draft.set({
      ...current,
      name,
      slug: following ? slugify(name) : current.slug,
    });
  }

  protected startEdit(type: AdminTowerType): void {
    this.editing.set(type);
    this.formError.set(null);
    this.draft.set({
      name: type.name,
      slug: type.slug,
      icon: type.icon,
      color: type.color,
      proximity_meters: type.proximity_meters,
      description: type.description,
    });
  }

  protected cancelEdit(): void {
    this.editing.set(null);
    this.draft.set(emptyDraft());
    this.formError.set(null);
  }

  protected save(): void {
    const d = this.draft();
    const body: TowerTypePayload = {
      name: d.name.trim(),
      slug: d.slug.trim() || slugify(d.name),
      icon: d.icon.trim() || 'bi-geo-alt-fill',
      color: d.color,
      proximity_meters: d.proximity_meters,
      description: d.description.trim(),
    };
    this.busy.set(true);
    this.formError.set(null);
    const existing = this.editing();
    const request = existing
      ? this.api.updateTowerType(existing.id, body)
      : this.api.createTowerType(body);
    request.subscribe({
      next: () => {
        this.busy.set(false);
        this.cancelEdit();
        this.refresh();
      },
      error: (err) => {
        this.busy.set(false);
        this.formError.set(extractErrorMessage(err));
      },
    });
  }

  protected async remove(type: AdminTowerType): Promise<void> {
    const inUse = type.tower_count > 0;
    const ok = await this.confirmService.confirm({
      title: `Delete “${type.name}”?`,
      message: inUse
        ? `${type.tower_count} tower(s) use this type. They will survive and fall back to the ` +
          'neutral default styling and the Game capture radius — nothing is deleted with it.'
        : 'This type is not in use.',
      confirmLabel: 'Delete',
      danger: true,
    });
    if (!ok) return;
    this.busy.set(true);
    this.api.deleteTowerType(type.id).subscribe({
      next: () => {
        this.busy.set(false);
        if (this.editing()?.id === type.id) this.cancelEdit();
        this.refresh();
      },
      error: (err) => {
        this.busy.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }
}
