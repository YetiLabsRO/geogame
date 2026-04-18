import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';

import {
  GameApiService,
  Invite,
  InviteStatus,
  InvitesService,
  QrCodeComponent,
  TeamSummary,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

type TabKey = InviteStatus | 'all';

@Component({
  selector: 'app-invites',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [ReactiveFormsModule, DatePipe, QrCodeComponent],
  template: `
    <h1 class="h3 mb-3">Invites</h1>

    <div class="row g-4">
      <div class="col-lg-5">
        <div class="card">
          <div class="card-body">
            <h2 class="h6 mb-3">Create invite</h2>
            <form [formGroup]="form" (ngSubmit)="create()" novalidate>
              <div class="mb-3">
                <label class="form-label" for="team">Team</label>
                <select id="team" class="form-select" formControlName="team">
                  <option [ngValue]="null" disabled>Pick a team…</option>
                  @for (t of teams(); track t.code) {
                    <option [ngValue]="t.id">{{ t.name }} ({{ t.code }})</option>
                  }
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label" for="email">Email (optional)</label>
                <input
                  id="email"
                  type="email"
                  class="form-control"
                  formControlName="email"
                  placeholder="Send the invite by email…"
                />
                <div class="form-text">
                  If provided, the invite is emailed. Otherwise, share the QR or URL directly.
                </div>
              </div>

              @if (createError(); as msg) {
                <div class="alert alert-danger py-2">{{ msg }}</div>
              }

              <button
                type="submit"
                class="btn btn-primary w-100"
                [disabled]="form.invalid || creating()"
              >
                @if (creating()) {
                  <span class="spinner-border spinner-border-sm me-2"></span>
                }
                Create invite
              </button>
            </form>
          </div>
        </div>
      </div>

      <div class="col-lg-7">
        <ul class="nav nav-pills mb-3">
          @for (t of tabs; track t.key) {
            <li class="nav-item">
              <button
                type="button"
                class="nav-link"
                [class.active]="activeTab() === t.key"
                (click)="setTab(t.key)"
              >
                {{ t.label }}
              </button>
            </li>
          }
        </ul>

        @if (loadError(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }

        @if (loading() && invites().length === 0) {
          <div class="d-flex align-items-center text-body-secondary">
            <span class="spinner-border spinner-border-sm me-2"></span>
            Loading…
          </div>
        } @else if (invites().length === 0) {
          <div class="alert alert-info">No invites in this bucket.</div>
        } @else {
          <div class="list-group">
            @for (i of invites(); track i.id) {
              <div class="list-group-item">
                <div class="d-flex justify-content-between align-items-start flex-wrap gap-2">
                  <div>
                    <div class="fw-semibold">{{ i.team_name }}</div>
                    <div class="small text-body-secondary">
                      {{ i.email || 'No email' }}
                    </div>
                    <div class="small text-body-secondary">
                      Expires {{ i.expires_at | date: 'medium' }}
                    </div>
                  </div>
                  <span class="badge" [class]="badgeClass(i.status)">{{ i.status }}</span>
                </div>

                @if (i.status === 'pending') {
                  <div class="mt-2">
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-secondary me-2"
                      (click)="toggleQr(i.id)"
                    >
                      {{ openQrId() === i.id ? 'Hide QR' : 'Show QR' }}
                    </button>
                    @if (i.email) {
                      <button
                        type="button"
                        class="btn btn-sm btn-outline-secondary me-2"
                        [disabled]="actingId() !== null"
                        (click)="resend(i)"
                      >
                        @if (actingId() === i.id && actingKind() === 'resend') {
                          <span class="spinner-border spinner-border-sm me-1"></span>
                        }
                        Resend email
                      </button>
                    }
                    <button
                      type="button"
                      class="btn btn-sm btn-outline-danger"
                      [disabled]="actingId() !== null"
                      (click)="revoke(i)"
                    >
                      @if (actingId() === i.id && actingKind() === 'revoke') {
                        <span class="spinner-border spinner-border-sm me-1"></span>
                      }
                      Revoke
                    </button>
                  </div>

                  @if (openQrId() === i.id) {
                    <div class="mt-3 d-flex flex-wrap gap-3 align-items-start">
                      <lib-qr-code [value]="inviteUrl(i)" [size]="192" />
                      <div class="small" style="word-break: break-all">
                        <div class="fw-semibold mb-1">Invite URL</div>
                        <code>{{ inviteUrl(i) }}</code>
                      </div>
                    </div>
                  }
                }

                @if (actionError()?.id === i.id) {
                  <div class="alert alert-danger py-2 mt-2 mb-0">
                    {{ actionError()?.message }}
                  </div>
                }
              </div>
            }
          </div>
        }
      </div>
    </div>
  `,
})
export class InvitesComponent {
  private readonly fb = inject(FormBuilder).nonNullable;
  private readonly invitesApi = inject(InvitesService);
  private readonly gameApi = inject(GameApiService);

  protected readonly tabs: { key: TabKey; label: string }[] = [
    { key: 'pending', label: 'Pending' },
    { key: 'accepted', label: 'Accepted' },
    { key: 'revoked', label: 'Revoked' },
    { key: 'expired', label: 'Expired' },
    { key: 'all', label: 'All' },
  ];

  protected readonly activeTab = signal<TabKey>('pending');
  protected readonly invites = signal<Invite[]>([]);
  protected readonly teams = signal<TeamSummary[]>([]);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly creating = signal(false);
  protected readonly createError = signal<string | null>(null);
  protected readonly actingId = signal<number | null>(null);
  protected readonly actingKind = signal<'revoke' | 'resend' | null>(null);
  protected readonly actionError = signal<{ id: number; message: string } | null>(null);
  protected readonly openQrId = signal<number | null>(null);

  protected readonly form = this.fb.group({
    team: [null as number | null, [Validators.required]],
    email: [''],
  });

  protected readonly hasTeams = computed(() => this.teams().length > 0);

  constructor() {
    this.refresh();
    this.gameApi.teams().subscribe({
      next: (list) => this.teams.set(list),
      error: () => {},
    });
  }

  protected setTab(tab: TabKey): void {
    this.activeTab.set(tab);
    this.openQrId.set(null);
    this.refresh();
  }

  protected refresh(): void {
    this.loading.set(true);
    this.loadError.set(null);
    const status = this.activeTab();
    this.invitesApi.list(status === 'all' ? undefined : status).subscribe({
      next: (list) => {
        this.invites.set(list);
        this.loading.set(false);
      },
      error: (err) => {
        this.loading.set(false);
        this.loadError.set(extractErrorMessage(err));
      },
    });
  }

  protected create(): void {
    if (this.form.invalid || this.creating()) return;
    this.creating.set(true);
    this.createError.set(null);
    const raw = this.form.getRawValue();
    this.invitesApi
      .create({ team: raw.team as number, email: raw.email || undefined })
      .subscribe({
        next: () => {
          this.creating.set(false);
          this.form.reset({ team: null, email: '' });
          this.activeTab.set('pending');
          this.refresh();
        },
        error: (err) => {
          this.creating.set(false);
          this.createError.set(extractErrorMessage(err));
        },
      });
  }

  protected revoke(i: Invite): void {
    if (this.actingId() !== null) return;
    this.actingId.set(i.id);
    this.actingKind.set('revoke');
    this.actionError.set(null);
    this.invitesApi.revoke(i.id).subscribe({
      next: () => this.afterAction(i.id),
      error: (err) => this.handleActionError(i.id, err),
    });
  }

  protected resend(i: Invite): void {
    if (this.actingId() !== null) return;
    this.actingId.set(i.id);
    this.actingKind.set('resend');
    this.actionError.set(null);
    this.invitesApi.resend(i.id).subscribe({
      next: () => {
        this.actingId.set(null);
        this.actingKind.set(null);
      },
      error: (err) => this.handleActionError(i.id, err),
    });
  }

  protected toggleQr(id: number): void {
    this.openQrId.set(this.openQrId() === id ? null : id);
  }

  protected inviteUrl(i: Invite): string {
    return `${window.location.origin}/invite/${i.token}`;
  }

  protected badgeClass(status: InviteStatus): string {
    switch (status) {
      case 'pending':
        return 'text-bg-info';
      case 'accepted':
        return 'text-bg-success';
      case 'revoked':
        return 'text-bg-secondary';
      case 'expired':
        return 'text-bg-warning';
    }
  }

  private afterAction(id: number): void {
    this.actingId.set(null);
    this.actingKind.set(null);
    this.refresh();
  }

  private handleActionError(id: number, err: unknown): void {
    this.actingId.set(null);
    this.actingKind.set(null);
    this.actionError.set({ id, message: extractErrorMessage(err) });
  }
}
