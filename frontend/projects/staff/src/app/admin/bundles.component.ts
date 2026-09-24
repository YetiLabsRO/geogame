import { HttpErrorResponse, HttpResponse } from '@angular/common/http';
import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import {
  AdminCollection,
  AdminGame,
  BundleImportMode,
  BundleImportReport,
  BundleInspection,
  InfoHintComponent,
  PageHeaderComponent,
  StaffApiService,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/**
 * Content bundles (content-portability capability).
 *
 * Two directions on one page. Exporting is a selection and a download.
 * Importing deliberately has a step in the middle: a bundle arrives from
 * somewhere else, and the page shows what is in it and what would change
 * before offering the button. Import stays disabled until an inspection
 * has come back, because "drop a zip, hit import" is how someone
 * overwrites the map twelve people are standing on.
 */
@Component({
  selector: 'app-bundles',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [FormsModule, PageHeaderComponent, InfoHintComponent],
  template: `
    <app-page-header
      title="Content bundles"
      subtitle="Move maps and game templates between installs. Sessions, teams and scores stay behind."
    />

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    <!-- ---------------------------------------------------------------- -->
    <div class="card mb-4">
      <div class="card-body">
        <h2 class="h6 mb-1">
          Export
          <app-info-hint
            text="A game already brings the collections it links, and those bring their towers, zones, types and reference media. Pick a collection on its own to send a map without a game's rules or challenges."
          />
        </h2>
        <p class="text-body-secondary small mb-3">
          Choose what to send. The bundle carries authored content only — no
          sessions, teams, players, ownerships, submissions or scores.
        </p>

        <div class="row g-4">
          <div class="col-md-6">
            <div class="fw-semibold small mb-2">Games</div>
            <ul class="list-group list-group-flush">
              @for (g of games(); track g.id) {
                <li class="list-group-item px-0 py-1">
                  <div class="form-check mb-0">
                    <input
                      class="form-check-input"
                      type="checkbox"
                      [id]="'bundle-game-' + g.id"
                      [checked]="selectedGames().has(g.id)"
                      (change)="toggleGame(g.id)"
                    />
                    <label class="form-check-label" [attr.for]="'bundle-game-' + g.id">
                      {{ g.name }}
                      <code class="ms-1 small">{{ g.slug }}</code>
                    </label>
                  </div>
                </li>
              } @empty {
                <li class="list-group-item px-0 py-1 text-body-secondary">
                  No games yet.
                </li>
              }
            </ul>
          </div>

          <div class="col-md-6">
            <div class="fw-semibold small mb-2">Collections</div>
            <ul class="list-group list-group-flush">
              @for (c of collections(); track c.id) {
                <li class="list-group-item px-0 py-1">
                  <div class="form-check mb-0">
                    <input
                      class="form-check-input"
                      type="checkbox"
                      [id]="'bundle-collection-' + c.id"
                      [checked]="selectedCollections().has(c.id)"
                      [disabled]="impliedCollections().has(c.id)"
                      (change)="toggleCollection(c.id)"
                    />
                    <label
                      class="form-check-label"
                      [attr.for]="'bundle-collection-' + c.id"
                    >
                      {{ c.name }}
                      <span class="text-body-secondary small">
                        — {{ c.towers.length }} towers, {{ c.zones.length }} zones
                      </span>
                      @if (impliedCollections().has(c.id)) {
                        <span class="badge text-bg-secondary ms-1">
                          included by a selected game
                        </span>
                      }
                    </label>
                  </div>
                </li>
              } @empty {
                <li class="list-group-item px-0 py-1 text-body-secondary">
                  No collections yet.
                </li>
              }
            </ul>
          </div>
        </div>

        @if (exportError(); as msg) {
          <div class="alert alert-danger py-2 mt-3 mb-0">{{ msg }}</div>
        }

        <div class="d-flex align-items-center gap-3 mt-3">
          <button
            type="button"
            class="btn btn-primary"
            [disabled]="!hasSelection() || exporting()"
            (click)="downloadBundle()"
          >
            {{ exporting() ? 'Preparing…' : 'Download bundle' }}
          </button>
          <span class="text-body-secondary small">{{ selectionSummary() }}</span>
        </div>
      </div>
    </div>

    <!-- ---------------------------------------------------------------- -->
    <div class="card">
      <div class="card-body">
        <h2 class="h6 mb-1">Import</h2>
        <p class="text-body-secondary small mb-3">
          Choose a bundle to see what it holds. Nothing changes until you
          import.
        </p>

        <div class="row g-3 align-items-end mb-3">
          <div class="col-md-6">
            <label class="form-label small fw-semibold" for="bundle-file">
              Bundle file
            </label>
            <input
              id="bundle-file"
              class="form-control"
              type="file"
              accept=".zip,application/zip"
              (change)="chooseFile($event)"
            />
          </div>
          <div class="col-md-6">
            <div class="fw-semibold small mb-2">
              What to do with content already here
              <app-info-hint
                text="Sync treats the bundle as the newer version of content this install already has and updates it in place. Copy leaves everything here alone and lands an independent second copy with its own identities and suffixed slugs."
              />
            </div>
            <div class="form-check form-check-inline">
              <input
                class="form-check-input"
                type="radio"
                id="bundle-mode-sync"
                name="bundle-mode"
                value="sync"
                [checked]="mode() === 'sync'"
                (change)="setMode('sync')"
              />
              <label class="form-check-label" for="bundle-mode-sync">
                Update what is here
              </label>
            </div>
            <div class="form-check form-check-inline">
              <input
                class="form-check-input"
                type="radio"
                id="bundle-mode-copy"
                name="bundle-mode"
                value="copy"
                [checked]="mode() === 'copy'"
                (change)="setMode('copy')"
              />
              <label class="form-check-label" for="bundle-mode-copy">
                Land a separate copy
              </label>
            </div>
          </div>
        </div>

        @if (inspectError(); as msg) {
          <div class="alert alert-danger py-2">{{ msg }}</div>
        }

        @if (inspecting()) {
          <p class="text-body-secondary small mb-0">Reading the bundle…</p>
        }

        @if (inspection(); as found) {
          <div class="border rounded p-3 mb-3">
            <div class="small text-body-secondary mb-2">
              Written {{ found.exported_at }} · format version
              {{ found.format_version }}
              @if (found.media_files) {
                · {{ found.media_files }} media file(s)
              }
            </div>
            <div class="table-responsive">
              <table class="table table-sm align-middle mb-0">
                <thead>
                  <tr>
                    <th>Content</th>
                    <th class="text-end">In bundle</th>
                    <th class="text-end">Already here</th>
                    <th class="text-end">Would create</th>
                    <th class="text-end">Would update</th>
                  </tr>
                </thead>
                <tbody>
                  @for (kind of found.kinds; track kind.kind) {
                    <tr>
                      <td>{{ kind.label }}</td>
                      <td class="text-end">{{ kind.in_bundle }}</td>
                      <td class="text-end">{{ kind.already_here }}</td>
                      <td class="text-end">{{ kind.would_create }}</td>
                      <td class="text-end">{{ kind.would_update }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>

            @if (found.slug_collisions.length) {
              <div class="alert alert-warning py-2 mt-3 mb-0">
                <div class="fw-semibold">
                  Names already taken by different content here
                </div>
                <ul class="mb-1 ps-3">
                  @for (clash of found.slug_collisions; track clash.incoming_uuid) {
                    <li>
                      <code>{{ clash.slug }}</code> is held by
                      “{{ clash.name }}”
                    </li>
                  }
                </ul>
                Updating in place would refuse this bundle. Land a separate
                copy instead, or rename what is here.
              </div>
            }
          </div>
        }

        @if (importError(); as msg) {
          <div class="alert alert-danger py-2">{{ msg }}</div>
        }

        @if (report(); as done) {
          <div class="alert alert-success py-2">
            <div class="fw-semibold">
              Imported: {{ done.total_created }} created,
              {{ done.total_updated }} updated
              @if (done.media) {
                , {{ done.media }} media file(s)
              }
            </div>
            @if (done.conflicts.length) {
              <ul class="mb-0 ps-3">
                @for (conflict of done.conflicts; track conflict.message) {
                  <li>{{ conflict.kind }}: {{ conflict.message }}</li>
                }
              </ul>
            }
          </div>
        }

        <button
          type="button"
          class="btn btn-primary"
          [disabled]="!inspection() || importing()"
          (click)="runImport()"
        >
          {{ importing() ? 'Importing…' : importLabel() }}
        </button>
        @if (!inspection()) {
          <span class="text-body-secondary small ms-3">
            Choose a bundle first.
          </span>
        }
      </div>
    </div>
  `,
})
export class BundlesComponent {
  private readonly api = inject(StaffApiService);

  protected readonly games = signal<AdminGame[]>([]);
  protected readonly collections = signal<AdminCollection[]>([]);
  protected readonly loadError = signal<string | null>(null);

  protected readonly selectedGames = signal<ReadonlySet<number>>(new Set());
  protected readonly selectedCollections = signal<ReadonlySet<number>>(new Set());
  protected readonly exporting = signal(false);
  protected readonly exportError = signal<string | null>(null);

  protected readonly file = signal<File | null>(null);
  protected readonly mode = signal<BundleImportMode>('sync');
  protected readonly inspection = signal<BundleInspection | null>(null);
  protected readonly inspecting = signal(false);
  protected readonly inspectError = signal<string | null>(null);
  protected readonly importing = signal(false);
  protected readonly importError = signal<string | null>(null);
  protected readonly report = signal<BundleImportReport | null>(null);

  /** Collections a selected game already carries, so they read as included. */
  protected readonly impliedCollections = computed(() => {
    const picked = this.selectedGames();
    const implied = new Set<number>();
    for (const game of this.games()) {
      if (picked.has(game.id)) {
        for (const id of game.collections) implied.add(id);
      }
    }
    return implied;
  });

  protected readonly hasSelection = computed(
    () => this.selectedGames().size > 0 || this.selectedCollections().size > 0,
  );

  protected readonly selectionSummary = computed(() => {
    const games = this.selectedGames().size;
    const explicit = [...this.selectedCollections()].filter(
      (id) => !this.impliedCollections().has(id),
    ).length;
    const implied = this.impliedCollections().size;
    if (!games && !explicit) return 'Nothing selected yet.';
    const parts: string[] = [];
    if (games) parts.push(`${games} game${games === 1 ? '' : 's'}`);
    const total = explicit + implied;
    if (total) parts.push(`${total} collection${total === 1 ? '' : 's'}`);
    return `Sending ${parts.join(' and ')}.`;
  });

  protected readonly importLabel = computed(() =>
    this.mode() === 'copy' ? 'Import as a separate copy' : 'Import and update',
  );

  constructor() {
    this.api.listGames().subscribe({
      next: (list) => this.games.set(list),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
    this.api.listCollections().subscribe({
      next: (list) => this.collections.set(list),
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
  }

  // -- export ---------------------------------------------------------

  protected toggleGame(id: number): void {
    this.selectedGames.update((current) => toggled(current, id));
    this.exportError.set(null);
  }

  protected toggleCollection(id: number): void {
    this.selectedCollections.update((current) => toggled(current, id));
    this.exportError.set(null);
  }

  protected downloadBundle(): void {
    if (!this.hasSelection() || this.exporting()) return;
    this.exporting.set(true);
    this.exportError.set(null);
    // Implied collections are left out of the request: the server derives
    // them from the games anyway, and sending both would claim the user
    // picked something they only saw ticked.
    const collectionIds = [...this.selectedCollections()].filter(
      (id) => !this.impliedCollections().has(id),
    );
    this.api.exportBundle([...this.selectedGames()], collectionIds).subscribe({
      next: (response) => {
        this.exporting.set(false);
        saveResponse(response);
      },
      error: async (err) => {
        this.exporting.set(false);
        this.exportError.set(await blobErrorMessage(err));
      },
    });
  }

  // -- import ---------------------------------------------------------

  protected chooseFile(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.file.set(input.files?.[0] ?? null);
    this.report.set(null);
    this.importError.set(null);
    this.inspect();
  }

  protected setMode(mode: BundleImportMode): void {
    this.mode.set(mode);
    this.report.set(null);
    this.importError.set(null);
    // What an import would do depends on the mode, so the preview is
    // re-read rather than left showing the other mode's numbers.
    this.inspect();
  }

  private inspect(): void {
    const file = this.file();
    this.inspection.set(null);
    this.inspectError.set(null);
    if (!file) return;
    this.inspecting.set(true);
    this.api.inspectBundle(file, this.mode()).subscribe({
      next: (found) => {
        this.inspecting.set(false);
        this.inspection.set(found);
      },
      error: (err) => {
        this.inspecting.set(false);
        this.inspectError.set(extractErrorMessage(err));
      },
    });
  }

  protected runImport(): void {
    const file = this.file();
    if (!file || !this.inspection() || this.importing()) return;
    this.importing.set(true);
    this.importError.set(null);
    this.report.set(null);
    this.api.importBundle(file, this.mode()).subscribe({
      next: (done) => {
        this.importing.set(false);
        this.report.set(done);
        // What is here has changed, so the export lists have too.
        this.api.listGames().subscribe({ next: (l) => this.games.set(l) });
        this.api.listCollections().subscribe({
          next: (l) => this.collections.set(l),
        });
        this.inspect();
      },
      error: (err) => {
        this.importing.set(false);
        this.importError.set(extractErrorMessage(err));
      },
    });
  }
}

function toggled(current: ReadonlySet<number>, id: number): ReadonlySet<number> {
  const next = new Set(current);
  if (!next.delete(id)) next.add(id);
  return next;
}

/** Filename from the server's Content-Disposition, else a sensible default. */
function filenameFrom(response: HttpResponse<Blob>): string {
  const header = response.headers.get('Content-Disposition') ?? '';
  const match = /filename="?([^";]+)"?/.exec(header);
  return match ? match[1] : 'bundle.zip';
}

function saveResponse(response: HttpResponse<Blob>): void {
  const blob = response.body;
  if (!blob) return;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filenameFrom(response);
  link.click();
  URL.revokeObjectURL(url);
}

/**
 * An error from a blob-typed request arrives as a Blob, not as JSON, so
 * the usual extractor would only ever say "Error 400".
 */
async function blobErrorMessage(err: unknown): Promise<string> {
  if (err instanceof HttpErrorResponse && err.error instanceof Blob) {
    try {
      const body = JSON.parse(await err.error.text());
      if (typeof body?.detail === 'string') return body.detail;
    } catch {
      // Fall through to the generic message below.
    }
  }
  return extractErrorMessage(err);
}
