import { ChangeDetectionStrategy, Component, Pipe, PipeTransform, computed, input } from '@angular/core';

/**
 * The colour a status carries. `neutral` is the quiet default and `muted`
 * the settled/archived one, so a finished run never competes with a live
 * one for attention. The fill and ink for each are derived from the theme
 * palette by `theme/_pill.scss` — see there for why the ink is white.
 */
export type StatusTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'muted';

/** How a status is drawn: what it should read as, and in what colour. */
interface StatusStyle {
  label: string;
  tone: StatusTone;
}

/**
 * Every status the apps show, as language rather than as the constant the
 * database stores. One map so the same status reads the same way on every
 * screen — `OPEN_FOR_PARTICIPANTS` is `Open for participants` in the
 * session list, on the session page, in the switcher and in the overview.
 *
 * A status that is not here is humanised rather than printed raw, so a new
 * one added on the server never surfaces as `SOME_NEW_STATE`.
 */
const STATUSES: Record<string, StatusStyle> = {
  // Session lifecycle (session-lifecycle).
  DRAFT: { label: 'Draft', tone: 'neutral' },
  OPEN_FOR_PARTICIPANTS: { label: 'Open for participants', tone: 'info' },
  RUNNING: { label: 'Running', tone: 'success' },
  PAUSED: { label: 'Paused', tone: 'warning' },
  FINISHED: { label: 'Finished', tone: 'muted' },

  // Invites (team-invites).
  PENDING: { label: 'Pending', tone: 'warning' },
  ACCEPTED: { label: 'Accepted', tone: 'success' },
  DECLINED: { label: 'Declined', tone: 'danger' },
  REVOKED: { label: 'Revoked', tone: 'muted' },
  EXPIRED: { label: 'Expired', tone: 'muted' },

  // Authoring proposals and their operations (mcp-authoring).
  DRAFTED: { label: 'Drafted', tone: 'neutral' },
  SUBMITTED: { label: 'Submitted', tone: 'info' },
  APPROVED: { label: 'Approved', tone: 'success' },
  REJECTED: { label: 'Rejected', tone: 'danger' },
  APPLIED: { label: 'Applied', tone: 'success' },
  PARTIALLY_APPLIED: { label: 'Partially applied', tone: 'warning' },
  SKIPPED: { label: 'Skipped', tone: 'muted' },

  // Simulation runs (simulator).
  QUEUED: { label: 'Queued', tone: 'neutral' },
  COMPLETED: { label: 'Completed', tone: 'success' },
  FAILED: { label: 'Failed', tone: 'danger' },
  CANCELLED: { label: 'Cancelled', tone: 'muted' },

  // Trail steps (mode-trail-discovery).
  HIDDEN: { label: 'Hidden', tone: 'muted' },
  LOCKED: { label: 'Locked', tone: 'muted' },
  REVEALED: { label: 'Revealed', tone: 'info' },
  UNLOCKED: { label: 'Unlocked', tone: 'success' },
  ARRIVED: { label: 'Arrived', tone: 'warning' },
  ACTIVE: { label: 'Active', tone: 'success' },
  DONE: { label: 'Done', tone: 'success' },

  // Wearable badges (wearable-badge-hardware).
  AVAILABLE: { label: 'Available', tone: 'success' },
  ASSIGNED: { label: 'Assigned', tone: 'info' },
  LOST: { label: 'Lost', tone: 'danger' },
  RETIRED: { label: 'Retired', tone: 'muted' },

  // Submissions (challenge-submission).
  CONFIRMED: { label: 'Confirmed', tone: 'success' },
  AWAITING_REVIEW: { label: 'Awaiting review', tone: 'warning' },
};

/**
 * Turn a constant into something a person would write: underscores and
 * dashes become spaces, and the result is sentence-cased. `IN_PROGRESS`
 * reads `In progress`.
 */
export function humaniseStatus(status: string): string {
  const words = status.trim().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');
  if (words.length === 0) return '';
  const lower = words.toLowerCase();
  return lower.charAt(0).toUpperCase() + lower.slice(1);
}

/** How a status should read and what colour it carries. */
export function statusStyle(status: string): StatusStyle {
  return (
    STATUSES[status?.toUpperCase?.() ?? ''] ?? {
      label: humaniseStatus(status ?? ''),
      tone: 'neutral' as StatusTone,
    }
  );
}

/**
 * `{{ step.state | statusLabel }}` — the shared label map, for surfaces that
 * draw their own pill. The player app's `ui-chip` is its own design system's
 * component, but a status should read the same there as it does in the staff
 * console, so both take their words from here.
 */
@Pipe({ name: 'statusLabel', standalone: true, pure: true })
export class StatusLabelPipe implements PipeTransform {
  transform(status: string | null | undefined): string {
    return status ? statusStyle(status).label : '';
  }
}

/**
 * A status, shown as language in a pill that can be read.
 *
 * ```html
 * <app-status-pill [status]="session.state" />
 * <app-status-pill [status]="run.status" tone="info" />
 * ```
 *
 * The label and tone come from the shared map unless `tone` overrides it.
 * Fill and ink come from theme tokens derived by luminance, and the text is
 * centred — Bootstrap's `.badge` is `line-height: 1`, which leaves
 * descender space under all-caps labels that nothing above them balances.
 */
@Component({
  selector: 'app-status-pill',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `<span class="status-pill" [attr.data-tone]="tone()">{{ label() }}</span>`,
  styles: `
    :host {
      display: inline-block;
    }

    .status-pill {
      /* A flex box centres the label on both axes for all-caps, mixed-case
         and descender-bearing labels alike. */
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 1.5rem;
      padding: 0.15em 0.65em;
      border-radius: 10rem;
      background: var(--pill-secondary-bg);
      color: var(--pill-secondary-ink);
      font-size: 0.75rem;
      font-weight: 600;
      line-height: 1.35;
      letter-spacing: 0.01em;
      white-space: nowrap;
      vertical-align: middle;
    }

    .status-pill[data-tone='info'] {
      background: var(--pill-info-bg);
      color: var(--pill-info-ink);
    }

    .status-pill[data-tone='success'] {
      background: var(--pill-success-bg);
      color: var(--pill-success-ink);
    }

    .status-pill[data-tone='warning'] {
      background: var(--pill-warning-bg);
      color: var(--pill-warning-ink);
    }

    .status-pill[data-tone='danger'] {
      background: var(--pill-danger-bg);
      color: var(--pill-danger-ink);
    }

    .status-pill[data-tone='muted'] {
      background: var(--pill-dark-bg);
      color: var(--pill-dark-ink);
    }
  `,
})
export class StatusPillComponent {
  /** The status constant as the server sends it, e.g. `OPEN_FOR_PARTICIPANTS`. */
  readonly status = input.required<string>();
  /** Override the tone the shared map would choose. */
  readonly toneOverride = input<StatusTone | null>(null, { alias: 'tone' });
  /** Override the label the shared map would choose. */
  readonly labelOverride = input<string | null>(null, { alias: 'label' });

  protected readonly label = computed(
    () => this.labelOverride() ?? statusStyle(this.status()).label,
  );
  protected readonly tone = computed(() => this.toneOverride() ?? statusStyle(this.status()).tone);
}
