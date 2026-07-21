import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import { StaffApiService, StaffSubmission } from 'shared';

import { extractErrorMessage } from '../auth/form-error';
import { ActiveLocksComponent } from './active-locks.component';

@Component({
  selector: 'app-pending-queue',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FormsModule, ActiveLocksComponent],
  template: `
    <div class="d-flex justify-content-between align-items-center mb-3">
      <h1 class="h3 mb-0">Review queue</h1>
      <button
        type="button"
        class="btn btn-sm btn-outline-secondary"
        [disabled]="loading()"
        (click)="refresh()"
      >
        <i class="bi bi-arrow-clockwise"></i> Refresh
      </button>
    </div>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading() && submissions().length === 0) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading…
      </div>
    } @else if (submissions().length === 0) {
      <div class="alert alert-info">Nothing waiting for review.</div>
    } @else {
      <div class="row g-3">
        @for (s of submissions(); track s.id) {
          <div class="col-md-6">
            <div class="card h-100">
              <div class="card-body">
                <div class="d-flex justify-content-between align-items-start">
                  <div>
                    <span class="badge" [style.background-color]="s.team_color">
                      {{ s.team_name }}
                    </span>
                    <div class="fw-semibold mt-1">{{ s.tower_name }}</div>
                  </div>
                  <div class="small text-body-secondary text-end">
                    {{ s.timestamp_submitted | date: 'short' }}
                    @if (s.submitted_by_username; as u) {
                      <div>by {{ u }}</div>
                    }
                  </div>
                </div>

                @if (s.challenge_type; as type) {
                  <span class="badge text-bg-light border mt-2">{{ typeLabel(type) }}</span>
                }
                @if (s.challenge_text; as text) {
                  <p class="mt-2 mb-1 fst-italic" style="white-space: pre-line">{{ text }}</p>
                  @if (s.challenge_difficulty !== null) {
                    <div class="small text-body-secondary">
                      Difficulty {{ s.challenge_difficulty }}
                    </div>
                  }
                } @else {
                  <p class="mt-2 mb-1 text-body-secondary">RFID capture (no challenge text)</p>
                }

                @if (s.submitted_code; as code) {
                  <div class="small mt-1">
                    Scanned code: <code>{{ code }}</code>
                  </div>
                }

                @if (s.photo_url; as photo) {
                  <a [href]="photo" target="_blank" rel="noopener">
                    <img
                      [src]="photo"
                      [alt]="'Submission ' + s.id + ' photo'"
                      class="img-fluid rounded mt-2"
                      style="max-height: 280px"
                    />
                  </a>
                } @else {
                  <div class="small text-body-secondary mt-2">No photo attached.</div>
                }

                @if (s.presence_check; as pc) {
                  <div class="border rounded p-2 mt-2 small">
                    <div class="fw-semibold mb-1">
                      <i class="bi bi-people"></i> Presence evidence
                    </div>
                    <div>
                      Present:
                      <span
                        class="badge"
                        [class.text-bg-success]="pc.present_count >= pc.required_count"
                        [class.text-bg-warning]="pc.present_count < pc.required_count"
                      >
                        {{ pc.present_count }} / {{ pc.required_count }}
                      </span>
                      · Method: <code>{{ pc.method }}</code>
                      @if (pc.window_seconds > 0) {
                        · Window ({{ pc.window_seconds }}s):
                        @if (pc.window_satisfied === true) {
                          <span class="badge text-bg-success">held</span>
                        } @else if (pc.window_satisfied === false) {
                          <span class="badge text-bg-danger">not held</span>
                        } @else {
                          <span class="badge text-bg-secondary">not evaluated</span>
                        }
                      }
                    </div>
                    @if (pc.method === 'PHOTO') {
                      <div class="text-warning mt-1">
                        <i class="bi bi-exclamation-triangle"></i>
                        Photo evidence is the weakest tier (easily AI-edited) —
                        confirm the required people are actually in the photo.
                      </div>
                    }
                    @if (pc.verified_member_ids.length > 0) {
                      <div class="text-body-secondary mt-1">
                        Verified member ids: {{ pc.verified_member_ids.join(', ') }}
                      </div>
                    }
                  </div>
                }

                @if (rejectingId() === s.id) {
                  <div class="mt-3">
                    <label class="form-label small" [attr.for]="'reject-reason-' + s.id">
                      Reason (optional)
                    </label>
                    <textarea
                      [id]="'reject-reason-' + s.id"
                      class="form-control mb-2"
                      rows="2"
                      [(ngModel)]="rejectReason"
                    ></textarea>
                    <div class="d-flex gap-2">
                      <button
                        type="button"
                        class="btn btn-sm btn-danger"
                        [disabled]="reviewingId() !== null"
                        (click)="reject(s)"
                      >
                        @if (reviewingId() === s.id) {
                          <span class="spinner-border spinner-border-sm me-1"></span>
                        }
                        Confirm reject
                      </button>
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-secondary"
                        (click)="cancelReject()"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                } @else {
                  <div class="d-flex gap-2 mt-3">
                    <button
                      type="button"
                      class="btn btn-sm btn-success"
                      [disabled]="reviewingId() !== null"
                      (click)="confirm(s)"
                    >
                      @if (reviewingId() === s.id) {
                        <span class="spinner-border spinner-border-sm me-1"></span>
                      }
                      <i class="bi bi-check-lg"></i> Confirm
                    </button>
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-danger"
                      [disabled]="reviewingId() !== null"
                      (click)="startReject(s)"
                    >
                      <i class="bi bi-x-lg"></i> Reject
                    </button>
                  </div>
                }

                @if (reviewError()?.id === s.id) {
                  <div class="alert alert-danger py-2 mt-2 mb-0">
                    {{ reviewError()?.message }}
                  </div>
                }
              </div>
            </div>
          </div>
        }
      </div>
    }

    <!-- challenge-type-system: auto-resolved outcomes as read-only audit -->
    <div class="mt-4">
      <button
        type="button"
        class="btn btn-sm btn-outline-secondary"
        (click)="toggleAudit()"
      >
        <i class="bi bi-clipboard-data"></i>
        {{ auditVisible() ? 'Hide' : 'Show' }} auto-validated audit
      </button>

      @if (auditVisible()) {
        @if (auditLoading()) {
          <div class="d-flex align-items-center text-body-secondary mt-3">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading audit…
          </div>
        } @else if (auditRows().length === 0) {
          <div class="alert alert-info mt-3">No auto-validated submissions yet.</div>
        } @else {
          <div class="table-responsive mt-3">
            <table class="table table-sm align-middle">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Team</th>
                  <th>Tower</th>
                  <th>Type</th>
                  <th>Scanned code</th>
                  <th>Outcome</th>
                </tr>
              </thead>
              <tbody>
                @for (s of auditRows(); track s.id) {
                  <tr>
                    <td class="small">{{ s.timestamp_verified | date: 'short' }}</td>
                    <td>
                      <span class="badge" [style.background-color]="s.team_color">
                        {{ s.team_name }}
                      </span>
                    </td>
                    <td>{{ s.tower_name }}</td>
                    <td>{{ typeLabel(s.challenge_type) }}</td>
                    <td><code>{{ s.submitted_code ?? '—' }}</code></td>
                    <td>
                      @if (s.outcome === 1) {
                        <span class="badge text-bg-success">Confirmed</span>
                      } @else {
                        <span class="badge text-bg-danger">Rejected</span>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      }
    </div>

    <hr class="my-4" />
    <app-active-locks />
  `,
})
export class PendingQueueComponent {
  private readonly api = inject(StaffApiService);

  protected readonly submissions = signal<StaffSubmission[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly reviewingId = signal<number | null>(null);
  protected readonly reviewError = signal<{ id: number; message: string } | null>(null);
  protected readonly rejectingId = signal<number | null>(null);
  protected rejectReason = '';

  // challenge-type-system: read-only audit of auto-resolved outcomes.
  protected readonly auditVisible = signal(false);
  protected readonly auditLoading = signal(false);
  protected readonly auditRows = signal<StaffSubmission[]>([]);

  constructor() {
    this.refresh();
  }

  protected typeLabel(type: string | null): string {
    switch (type) {
      case 'TEXT':
        return 'Text';
      case 'PHOTO':
        return 'Photo';
      case 'NFC_QR':
        return 'NFC/QR code';
      case 'RFID':
        return 'RFID tag';
      default:
        return type ?? '—';
    }
  }

  protected toggleAudit(): void {
    this.auditVisible.update((v) => !v);
    if (!this.auditVisible()) return;
    this.auditLoading.set(true);
    this.api.listSubmissions('all').subscribe({
      next: (list) => {
        this.auditRows.set(list.filter((s) => s.auto_resolved));
        this.auditLoading.set(false);
      },
      error: () => {
        this.auditRows.set([]);
        this.auditLoading.set(false);
      },
    });
  }

  protected refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    this.api.listSubmissions('pending').subscribe({
      next: (list) => {
        this.submissions.set(list);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected confirm(s: StaffSubmission): void {
    if (this.reviewingId() !== null) return;
    this.reviewingId.set(s.id);
    this.reviewError.set(null);
    this.api.confirmSubmission(s.id).subscribe({
      next: () => this.afterReview(s.id),
      error: (err) => this.handleReviewError(s.id, err),
    });
  }

  protected startReject(s: StaffSubmission): void {
    this.rejectingId.set(s.id);
    this.rejectReason = '';
    this.reviewError.set(null);
  }

  protected cancelReject(): void {
    this.rejectingId.set(null);
    this.rejectReason = '';
  }

  protected reject(s: StaffSubmission): void {
    if (this.reviewingId() !== null) return;
    this.reviewingId.set(s.id);
    this.reviewError.set(null);
    this.api.rejectSubmission(s.id, this.rejectReason).subscribe({
      next: () => {
        this.rejectingId.set(null);
        this.rejectReason = '';
        this.afterReview(s.id);
      },
      error: (err) => this.handleReviewError(s.id, err),
    });
  }

  private afterReview(id: number): void {
    this.reviewingId.set(null);
    this.submissions.update((list) => list.filter((s) => s.id !== id));
  }

  private handleReviewError(id: number, err: unknown): void {
    this.reviewingId.set(null);
    this.reviewError.set({ id, message: extractErrorMessage(err) });
  }
}
