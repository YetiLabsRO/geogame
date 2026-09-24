import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe, JsonPipe } from '@angular/common';
import { FormsModule } from '@angular/forms';

import {
  AuthoringProposal,
  AuthoringProposalDetail,
  McpCredential,
  ProposedOperation,
  StaffApiService,
  StatusPillComponent,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';

/**
 * mcp-authoring: the staff "AI authoring review" inbox. A creator reviews
 * what their LLM (over the MCP server) proposed — per-operation rationale
 * and diff — then approves/rejects/applies. Also issues/revokes the
 * creator-scoped MCP credentials the LLM authenticates with.
 */
@Component({
  selector: 'app-authoring-review',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FormsModule, JsonPipe, StatusPillComponent],
  template: `
    <h1 class="h3 mb-1">AI authoring review</h1>
    <p class="text-body-secondary small">
      An LLM connected over the MCP server can read the authoring surface and
      <strong>stage</strong> proposals — it never writes live content. You
      review each operation's rationale and diff here, then approve and apply.
    </p>

    @if (error(); as msg) {
      <div class="alert alert-danger py-2">{{ msg }}</div>
    }

    <div class="row">
      <!-- Inbox -->
      <div class="col-lg-5">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <h2 class="h6 mb-0">Proposals</h2>
          <button class="btn btn-sm btn-outline-secondary" (click)="reload()">Refresh</button>
        </div>
        @if (proposals().length === 0) {
          <p class="text-body-secondary small">No proposals yet.</p>
        }
        <div class="list-group">
          @for (p of proposals(); track p.id) {
            <button
              class="list-group-item list-group-item-action"
              [class.active]="selectedId() === p.id"
              (click)="select(p.id)"
            >
              <div class="d-flex justify-content-between">
                <span class="fw-semibold">#{{ p.id }} · {{ p.summary || 'Untitled' }}</span>
                <app-status-pill [status]="p.status" />
              </div>
              <div class="small text-body-secondary">
                {{ p.operation_count }} operation(s)
                @if (p.llm_model) { · {{ p.llm_model }} }
                · {{ p.created_at | date: 'short' }}
              </div>
            </button>
          }
        </div>
      </div>

      <!-- Detail -->
      <div class="col-lg-7">
        @if (detail(); as d) {
          <div class="card">
            <div class="card-body">
              <div class="d-flex justify-content-between align-items-start">
                <h2 class="h6 mb-2">
                  Proposal #{{ d.id }}
                  <app-status-pill [status]="d.status" />
                </h2>
                <span class="small text-body-secondary">
                  {{ d.atomic ? 'atomic' : 'per-op' }}
                </span>
              </div>
              @if (d.summary) { <p class="mb-2">{{ d.summary }}</p> }

              @for (op of d.operations; track op.id) {
                <div class="border rounded p-2 mb-2">
                  <div class="d-flex justify-content-between">
                    <span class="fw-semibold">
                      {{ op.action }} {{ op.entity_type }}
                      @if (op.temp_ref) { <code class="small">&#64;new:{{ op.temp_ref }}</code> }
                    </span>
                    <app-status-pill [status]="op.status" />
                  </div>
                  @if (op.rationale) {
                    <div class="small fst-italic text-body-secondary mb-1">
                      “{{ op.rationale }}”
                    </div>
                  }
                  <pre class="small bg-body-tertiary p-2 mb-1 rounded">{{ op.payload | json }}</pre>
                  @if (op.action === 'CREATE' && op.entity_type === 'SESSION') {
                    <div class="small text-body-secondary mb-1">
                      Created in DRAFT — open participation and start it from the
                      session runner.
                    </div>
                  }
                  @if (op.action === 'CREATE' && op.entity_type === 'TEAM') {
                    <div class="small text-body-secondary mb-1">
                      Empty shell — players join through an invite or the join code.
                    </div>
                  }
                  @if (op.current) {
                    <div class="small text-body-secondary">Current: {{ op.current | json }}</div>
                  }
                  @if (op.error) {
                    <div class="small text-danger">Error: {{ op.error }}</div>
                  }
                  @if (canDecideOps(d)) {
                    <div class="mt-1">
                      <button class="btn btn-sm btn-outline-success me-1"
                        (click)="decideOp(d.id, op.id, 'approve')">Approve op</button>
                      <button class="btn btn-sm btn-outline-danger"
                        (click)="decideOp(d.id, op.id, 'reject')">Reject op</button>
                    </div>
                  }
                </div>
              }

              <div class="mt-3 d-flex gap-2 flex-wrap">
                @if (canDecideOps(d)) {
                  <button class="btn btn-sm btn-success" [disabled]="busy()"
                    (click)="decide(d.id, 'approve')">Approve all</button>
                  <button class="btn btn-sm btn-danger" [disabled]="busy()"
                    (click)="decide(d.id, 'reject')">Reject</button>
                }
                @if (d.status === 'APPROVED') {
                  <button class="btn btn-sm btn-primary" [disabled]="busy()"
                    (click)="decide(d.id, 'apply')">Apply</button>
                }
                <button class="btn btn-sm btn-outline-secondary" [disabled]="busy()"
                  (click)="decide(d.id, 'withdraw')">Withdraw</button>
              </div>
            </div>
          </div>
        } @else {
          <p class="text-body-secondary small">Select a proposal to review it.</p>
        }
      </div>
    </div>

    <!-- MCP credentials -->
    <hr class="my-4" />
    <h2 class="h6">MCP credentials</h2>
    <p class="text-body-secondary small">
      Issue a token for an LLM client to connect to the MCP authoring server.
      The token is shown once — copy it now.
    </p>
    <div class="row g-2 align-items-center mb-2" style="max-width: 32rem;">
      <div class="col">
        <input class="form-control form-control-sm" [(ngModel)]="newLabel"
          placeholder="Label (e.g. Claude Desktop)" />
      </div>
      <div class="col-auto">
        <button class="btn btn-sm btn-outline-primary" [disabled]="busy()"
          (click)="issue()">Issue token</button>
      </div>
    </div>
    @if (issuedToken(); as token) {
      <div class="alert alert-success py-2">
        <div class="small mb-1">New token (copy now — not shown again):</div>
        <code class="user-select-all">{{ token }}</code>
      </div>
    }
    <ul class="list-group" style="max-width: 32rem;">
      @for (c of credentials(); track c.id) {
        <li class="list-group-item d-flex justify-content-between align-items-center">
          <span>
            {{ c.label || 'Unlabelled' }}
            <span class="badge {{ c.is_active ? 'text-bg-success' : 'text-bg-secondary' }}">
              {{ c.is_active ? 'active' : 'revoked' }}
            </span>
          </span>
          @if (c.is_active) {
            <button class="btn btn-sm btn-outline-danger" (click)="revoke(c.id)">Revoke</button>
          }
        </li>
      }
    </ul>
  `,
})
export class AuthoringReviewComponent {
  private readonly api = inject(StaffApiService);

  protected readonly proposals = signal<AuthoringProposal[]>([]);
  protected readonly detail = signal<AuthoringProposalDetail | null>(null);
  protected readonly credentials = signal<McpCredential[]>([]);
  protected readonly error = signal<string | null>(null);
  protected readonly busy = signal(false);
  protected readonly issuedToken = signal<string | null>(null);
  protected newLabel = '';

  protected readonly selectedId = computed(() => this.detail()?.id ?? null);

  constructor() {
    this.reload();
    this.loadCredentials();
  }

  reload(): void {
    this.api.authoringProposals().subscribe({
      next: (rows) => this.proposals.set(rows),
      error: (err) => this.error.set(extractErrorMessage(err)),
    });
  }

  loadCredentials(): void {
    this.api.mcpCredentials().subscribe({
      next: (rows) => this.credentials.set(rows),
      error: () => {},
    });
  }

  select(id: number): void {
    this.api.authoringProposal(id).subscribe({
      next: (d) => this.detail.set(d),
      error: (err) => this.error.set(extractErrorMessage(err)),
    });
  }

  canDecideOps(d: AuthoringProposalDetail): boolean {
    return ['DRAFT', 'PENDING', 'APPROVED'].includes(d.status);
  }

  decide(id: number, action: 'approve' | 'reject' | 'apply' | 'withdraw'): void {
    this.busy.set(true);
    this.error.set(null);
    this.api.authoringDecision(id, action).subscribe({
      next: (d) => {
        this.detail.set(d);
        this.busy.set(false);
        this.reload();
      },
      error: (err) => {
        this.error.set(extractErrorMessage(err));
        this.busy.set(false);
      },
    });
  }

  decideOp(proposalId: number, opId: number, action: 'approve' | 'reject'): void {
    this.api.authoringOperationDecision(proposalId, opId, action).subscribe({
      next: (d) => this.detail.set(d),
      error: (err) => this.error.set(extractErrorMessage(err)),
    });
  }

  issue(): void {
    if (!this.newLabel.trim()) return;
    this.busy.set(true);
    this.api.issueMcpCredential(this.newLabel.trim()).subscribe({
      next: (c) => {
        this.issuedToken.set(c.token);
        this.newLabel = '';
        this.busy.set(false);
        this.loadCredentials();
      },
      error: (err) => {
        this.error.set(extractErrorMessage(err));
        this.busy.set(false);
      },
    });
  }

  revoke(id: number): void {
    this.api.revokeMcpCredential(id).subscribe({
      next: () => this.loadCredentials(),
      error: (err) => this.error.set(extractErrorMessage(err)),
    });
  }


}
