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

  constructor() {
    this.refresh();
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
