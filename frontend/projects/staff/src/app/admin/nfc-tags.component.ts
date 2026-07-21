import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { NfcNdefPayload, NfcTagInfo, QrCodeComponent, StaffApiService, TagScanInfo } from 'shared';

/**
 * nfc-native-and-secure-links: staff tag provisioning (wireframe).
 * Mint tokens, bind to a tower/challenge, set the hidden-location hint,
 * export the NDEF payload, show a printable QR sheet, and audit scans.
 */
@Component({
  selector: 'app-nfc-tags',
  standalone: true,
  imports: [FormsModule, QrCodeComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="container py-3">
      <h4><i class="bi bi-broadcast-pin"></i> Tag-uri NFC / QR</h4>

      <form class="card card-body mb-3" (ngSubmit)="create()">
        <div class="row g-2 align-items-end">
          <div class="col-md-2">
            <label class="form-label">Mod</label>
            <select class="form-select" name="mode" [(ngModel)]="form.mode">
              <option value="SECURE_TOKEN">SECURE_TOKEN</option>
              <option value="LEGACY_URL">LEGACY_URL</option>
            </select>
          </div>
          <div class="col-md-2">
            <label class="form-label">Tower ID</label>
            <input class="form-control" name="tower" type="number" [(ngModel)]="form.tower" />
          </div>
          <div class="col-md-2">
            <label class="form-label">Challenge ID</label>
            <input class="form-control" name="challenge" type="number" [(ngModel)]="form.challenge" />
          </div>
          <div class="col-md-2">
            <label class="form-label">Etichetă</label>
            <input class="form-control" name="label" [(ngModel)]="form.label" />
          </div>
          <div class="col-md-3">
            <label class="form-label">Unde este ascuns</label>
            <input class="form-control" name="hint" [(ngModel)]="form.hidden_hint" />
          </div>
          <div class="col-md-1">
            <button class="btn btn-primary w-100" type="submit">Emite</button>
          </div>
        </div>
        @if (error(); as err) {
          <div class="text-danger small mt-2">{{ err }}</div>
        }
      </form>

      <table class="table table-sm align-middle">
        <thead>
          <tr>
            <th>Token</th><th>Mod</th><th>Țintă</th><th>Etichetă / ascuns</th>
            <th>Scanări</th><th>Activ</th><th></th>
          </tr>
        </thead>
        <tbody>
          @for (tag of tags(); track tag.id) {
            <tr>
              <td><code>{{ tag.token }}</code></td>
              <td><span class="badge text-bg-secondary">{{ tag.mode }}</span></td>
              <td>
                @if (tag.target_summary; as target) {
                  {{ target.kind }} #{{ target.id }} {{ target.name }}
                }
              </td>
              <td>{{ tag.label }} <span class="text-muted small">{{ tag.hidden_hint }}</span></td>
              <td>{{ tag.scan_count }}</td>
              <td>
                @if (tag.is_active) {
                  <i class="bi bi-check-circle text-success"></i>
                } @else {
                  <i class="bi bi-slash-circle text-muted"></i>
                }
              </td>
              <td class="text-nowrap">
                <button class="btn btn-sm btn-outline-secondary me-1" (click)="showNdef(tag)">
                  NDEF
                </button>
                <button class="btn btn-sm btn-outline-secondary me-1" (click)="toggleQr(tag)">
                  QR
                </button>
                <button
                  class="btn btn-sm btn-outline-danger"
                  (click)="deactivate(tag)"
                  [disabled]="!tag.is_active"
                >
                  Dezactivează
                </button>
              </td>
            </tr>
            @if (qrTag()?.id === tag.id) {
              <tr>
                <td colspan="7" class="text-center">
                  <div class="p-2 d-inline-block bg-white">
                    <lib-qr-code [value]="tag.app_link" [size]="220" />
                    <div class="small text-muted">{{ tag.app_link }}</div>
                    <button class="btn btn-sm btn-outline-secondary mt-1" onclick="window.print()">
                      <i class="bi bi-printer"></i> Printează
                    </button>
                  </div>
                </td>
              </tr>
            }
            @if (ndef()?.token === tag.token) {
              <tr>
                <td colspan="7"><pre class="small mb-0">{{ ndefJson() }}</pre></td>
              </tr>
            }
          } @empty {
            <tr><td colspan="7" class="text-muted">Niciun tag încă.</td></tr>
          }
        </tbody>
      </table>

      <h5 class="mt-4">Audit scanări</h5>
      <table class="table table-sm">
        <thead>
          <tr><th>Când</th><th>Tag</th><th>Jucător</th><th>Rezultat</th><th>Counter</th></tr>
        </thead>
        <tbody>
          @for (scan of scans(); track scan.id) {
            <tr>
              <td>{{ scan.timestamp }}</td>
              <td>{{ scan.tag_label }}</td>
              <td>{{ scan.player_username }}</td>
              <td>
                <span
                  class="badge"
                  [class.text-bg-success]="scan.outcome === 'CONFIRMED'"
                  [class.text-bg-warning]="scan.outcome === 'PENDING'"
                  [class.text-bg-danger]="scan.outcome.startsWith('REJECTED')"
                >
                  {{ scan.outcome }}
                </span>
              </td>
              <td>{{ scan.counter }}</td>
            </tr>
          } @empty {
            <tr><td colspan="5" class="text-muted">Nicio scanare încă.</td></tr>
          }
        </tbody>
      </table>
    </div>
  `,
})
export class NfcTagsComponent implements OnInit {
  private readonly api = inject(StaffApiService);

  readonly tags = signal<NfcTagInfo[]>([]);
  readonly scans = signal<TagScanInfo[]>([]);
  readonly qrTag = signal<NfcTagInfo | null>(null);
  readonly ndef = signal<NfcNdefPayload | null>(null);
  readonly error = signal<string | null>(null);

  form: { mode: 'SECURE_TOKEN' | 'LEGACY_URL'; tower: number | null; challenge: number | null; label: string; hidden_hint: string } = {
    mode: 'SECURE_TOKEN',
    tower: null,
    challenge: null,
    label: '',
    hidden_hint: '',
  };

  ngOnInit(): void {
    this.reload();
  }

  reload(): void {
    this.api.nfcTags().subscribe((tags) => this.tags.set(tags));
    this.api.nfcScanAudit().subscribe((scans) => this.scans.set(scans));
  }

  create(): void {
    this.error.set(null);
    this.api.createNfcTag(this.form).subscribe({
      next: () => {
        this.form = { mode: 'SECURE_TOKEN', tower: null, challenge: null, label: '', hidden_hint: '' };
        this.reload();
      },
      error: (err) => this.error.set(JSON.stringify(err?.error ?? 'Eroare')),
    });
  }

  deactivate(tag: NfcTagInfo): void {
    this.api.updateNfcTag(tag.id, { is_active: false }).subscribe(() => this.reload());
  }

  showNdef(tag: NfcTagInfo): void {
    this.api.nfcTagNdef(tag.id).subscribe((payload) => this.ndef.set(payload));
  }

  ndefJson(): string {
    return JSON.stringify(this.ndef(), null, 2);
  }

  toggleQr(tag: NfcTagInfo): void {
    this.qrTag.set(this.qrTag()?.id === tag.id ? null : tag);
  }
}
