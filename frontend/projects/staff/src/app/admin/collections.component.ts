import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormBuilder, FormsModule, ReactiveFormsModule, Validators } from '@angular/forms';

import {
  AdminCollection,
  AdminTower,
  AdminZone,
  StaffApiService,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

@Component({
  selector: 'app-admin-collections',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, FormsModule],
  template: `
    <h1 class="h3 mb-3">Collections</h1>
    <p class="text-body-secondary small">
      The points repository groups reusable Towers and Zones into named
      Collections — the "maps" that Games link to. The same tower can appear in
      several collections; removing it from a collection never deletes it.
    </p>

    <div class="card mb-4">
      <div class="card-body">
        <h2 class="h6 mb-3">Create collection</h2>
        <form [formGroup]="createForm" (ngSubmit)="create()" novalidate>
          <div class="row g-2">
            <div class="col-md-4">
              <input
                class="form-control"
                type="text"
                placeholder="Name"
                formControlName="name"
              />
            </div>
            <div class="col-md-3">
              <input
                class="form-control"
                type="text"
                placeholder="Slug (optional)"
                formControlName="slug"
              />
            </div>
            <div class="col-md-5">
              <input
                class="form-control"
                type="text"
                placeholder="Description (optional)"
                formControlName="description"
              />
            </div>
          </div>
          @if (createError(); as msg) {
            <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
          }
          <button
            type="submit"
            class="btn btn-primary mt-3"
            [disabled]="createForm.invalid || creating()"
          >
            @if (creating()) {
              <span class="spinner-border spinner-border-sm me-1"></span>
            }
            Create collection
          </button>
        </form>
      </div>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading() && collections().length === 0) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (collections().length === 0) {
      <div class="alert alert-info">No collections yet.</div>
    } @else {
      <div class="table-responsive">
        <table class="table align-middle">
          <thead>
            <tr>
              <th>Name</th>
              <th>Slug</th>
              <th>Towers</th>
              <th>Zones</th>
              <th>Used by games</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            @for (c of collections(); track c.id) {
              <tr>
                <td>{{ c.name }}</td>
                <td><code>{{ c.slug }}</code></td>
                <td>{{ c.towers.length }}</td>
                <td>{{ c.zones.length }}</td>
                <td>
                  @if (c.games.length === 0) {
                    <span class="text-body-secondary">—</span>
                  } @else {
                    @for (g of c.games; track g.id) {
                      <span class="badge text-bg-secondary me-1">{{ g.name }}</span>
                    }
                  }
                </td>
                <td class="text-end">
                  <div class="d-flex gap-2 justify-content-end">
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary"
                      (click)="select(c)"
                    >
                      {{ selectedId() === c.id ? 'Close' : 'Curate' }}
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-danger"
                      (click)="remove(c)"
                    >
                      Delete
                    </button>
                  </div>
                </td>
              </tr>
            }
          </tbody>
        </table>
      </div>

      @if (selected(); as c) {
        <div class="card mb-4">
          <div class="card-body">
            <h2 class="h6 mb-1">Curate “{{ c.name }}”</h2>
            <p class="text-body-secondary small mb-3">
              Adding or removing members only changes this collection —
              towers and zones stay in the repository either way.
            </p>
            @if (actionError(); as msg) {
              <div class="alert alert-danger py-2">{{ msg }}</div>
            }
            <div class="row g-4">
              <div class="col-md-6">
                <div class="fw-semibold small mb-2">
                  Towers ({{ c.towers.length }})
                </div>
                <ul class="list-group list-group-flush mb-2">
                  @for (t of memberTowers(); track t.id) {
                    <li class="list-group-item d-flex justify-content-between align-items-center px-0 py-1">
                      <span>{{ t.name }}</span>
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-danger"
                        (click)="removeTower(t.id)"
                      >
                        Remove
                      </button>
                    </li>
                  } @empty {
                    <li class="list-group-item px-0 py-1 text-body-secondary">
                      No towers in this collection.
                    </li>
                  }
                </ul>
                <div class="d-flex gap-2">
                  <select class="form-select form-select-sm" [(ngModel)]="towerToAdd">
                    <option [ngValue]="null">Add tower from repository…</option>
                    @for (t of addableTowers(); track t.id) {
                      <option [ngValue]="t.id">{{ t.name }}</option>
                    }
                  </select>
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-primary"
                    [disabled]="towerToAdd === null"
                    (click)="addTower()"
                  >
                    Add
                  </button>
                </div>
              </div>
              <div class="col-md-6">
                <div class="fw-semibold small mb-2">
                  Zones ({{ c.zones.length }})
                </div>
                <ul class="list-group list-group-flush mb-2">
                  @for (z of memberZones(); track z.id) {
                    <li class="list-group-item d-flex justify-content-between align-items-center px-0 py-1">
                      <span>{{ z.name }}</span>
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-danger"
                        (click)="removeZone(z.id)"
                      >
                        Remove
                      </button>
                    </li>
                  } @empty {
                    <li class="list-group-item px-0 py-1 text-body-secondary">
                      No zones in this collection.
                    </li>
                  }
                </ul>
                <div class="d-flex gap-2">
                  <select class="form-select form-select-sm" [(ngModel)]="zoneToAdd">
                    <option [ngValue]="null">Add zone from repository…</option>
                    @for (z of addableZones(); track z.id) {
                      <option [ngValue]="z.id">{{ z.name }}</option>
                    }
                  </select>
                  <button
                    type="button"
                    class="btn btn-sm btn-outline-primary"
                    [disabled]="zoneToAdd === null"
                    (click)="addZone()"
                  >
                    Add
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      }
    }
  `,
})
export class CollectionsComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly api = inject(StaffApiService);

  protected readonly collections = signal<AdminCollection[]>([]);
  protected readonly allTowers = signal<AdminTower[]>([]);
  protected readonly allZones = signal<AdminZone[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);
  protected readonly actionError = signal<string | null>(null);
  protected readonly selectedId = signal<number | null>(null);

  protected towerToAdd: number | null = null;
  protected zoneToAdd: number | null = null;

  protected readonly selected = computed(() => {
    const id = this.selectedId();
    return id === null
      ? null
      : (this.collections().find((c) => c.id === id) ?? null);
  });

  protected readonly memberTowers = computed(() => {
    const c = this.selected();
    if (!c) return [];
    return this.allTowers().filter((t) => c.towers.includes(t.id));
  });

  protected readonly memberZones = computed(() => {
    const c = this.selected();
    if (!c) return [];
    return this.allZones().filter((z) => c.zones.includes(z.id));
  });

  protected readonly addableTowers = computed(() => {
    const c = this.selected();
    if (!c) return [];
    return this.allTowers().filter((t) => !c.towers.includes(t.id));
  });

  protected readonly addableZones = computed(() => {
    const c = this.selected();
    if (!c) return [];
    return this.allZones().filter((z) => !c.zones.includes(z.id));
  });

  protected readonly createForm = this.fb.group({
    name: ['', [Validators.required]],
    slug: [''],
    description: [''],
  });

  constructor() {
    this.refresh();
    this.api.listTowers().subscribe({
      next: (list) => this.allTowers.set(list),
      error: () => {},
    });
    this.api.listZones().subscribe({
      next: (list) => this.allZones.set(list),
      error: () => {},
    });
  }

  private refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listCollections().subscribe({
      next: (list) => {
        this.collections.set(list);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected select(c: AdminCollection): void {
    this.actionError.set(null);
    this.towerToAdd = null;
    this.zoneToAdd = null;
    this.selectedId.update((id) => (id === c.id ? null : c.id));
  }

  protected create(): void {
    if (this.createForm.invalid || this.creating()) return;
    this.creating.set(true);
    this.createError.set(null);
    const raw = this.createForm.getRawValue();
    this.api
      .createCollection({
        name: raw.name,
        slug: raw.slug || undefined,
        description: raw.description,
      })
      .subscribe({
        next: () => {
          this.creating.set(false);
          this.createForm.reset({ name: '', slug: '', description: '' });
          this.refresh();
        },
        error: (err) => {
          this.creating.set(false);
          this.createError.set(extractErrorMessage(err));
        },
      });
  }

  protected remove(c: AdminCollection): void {
    const inUse = c.games.length
      ? ` It is used by ${c.games.length} game(s).`
      : '';
    if (
      !confirm(
        `Delete collection "${c.name}"?${inUse} Towers and zones stay in the repository.`,
      )
    ) {
      return;
    }
    this.api.deleteCollection(c.id).subscribe({
      next: () => {
        if (this.selectedId() === c.id) this.selectedId.set(null);
        this.refresh();
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  private applyUpdated(updated: AdminCollection): void {
    this.collections.update((list) =>
      list.map((c) => (c.id === updated.id ? updated : c)),
    );
  }

  protected addTower(): void {
    const c = this.selected();
    if (!c || this.towerToAdd === null) return;
    this.actionError.set(null);
    this.api.addCollectionTowers(c.id, [this.towerToAdd]).subscribe({
      next: (updated) => {
        this.towerToAdd = null;
        this.applyUpdated(updated);
      },
      error: (err) => this.actionError.set(extractErrorMessage(err)),
    });
  }

  protected removeTower(towerId: number): void {
    const c = this.selected();
    if (!c) return;
    this.actionError.set(null);
    this.api.removeCollectionTowers(c.id, [towerId]).subscribe({
      next: (updated) => this.applyUpdated(updated),
      error: (err) => this.actionError.set(extractErrorMessage(err)),
    });
  }

  protected addZone(): void {
    const c = this.selected();
    if (!c || this.zoneToAdd === null) return;
    this.actionError.set(null);
    this.api.addCollectionZones(c.id, [this.zoneToAdd]).subscribe({
      next: (updated) => {
        this.zoneToAdd = null;
        this.applyUpdated(updated);
      },
      error: (err) => this.actionError.set(extractErrorMessage(err)),
    });
  }

  protected removeZone(zoneId: number): void {
    const c = this.selected();
    if (!c) return;
    this.actionError.set(null);
    this.api.removeCollectionZones(c.id, [zoneId]).subscribe({
      next: (updated) => this.applyUpdated(updated),
      error: (err) => this.actionError.set(extractErrorMessage(err)),
    });
  }
}
