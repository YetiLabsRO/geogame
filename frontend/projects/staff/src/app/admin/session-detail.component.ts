import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { DatePipe, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { HttpErrorResponse } from '@angular/common/http';

import {
  ActiveMultiplier,
  AdminGame,
  AdminScoreMultiplier,
  AdminSession,
  AdminSessionPayload,
  AdminTower,
  AdminZone,
  ChallengeVisibility,
  ConfirmService,
  ConquestRule,
  DementorEmptyOutcome,
  Discoverability,
  FailCounterInfo,
  FailCounterReset,
  FieldRowComponent,
  GameApiService,
  GameMode,
  InfoHintComponent,
  LocationVisibility,
  OverviewLink,
  PageHeaderComponent,
  PauseHistory,
  Phase10Overrides,
  PresenceRulesOverrides,
  ProximityBucket,
  ScoreMultiplierScope,
  ScoreMultiplierType,
  ScoreTimeUnit,
  SessionScoreboard,
  SessionState,
  SessionTimeline,
  SessionTransitionAction,
  StaffApiService,
  StartReadiness,
  StatusPillComponent,
  TeamBuildResult,
  TeammateVisibilityMode,
  TogethernessMode,
  TowerLockMode,
  TowerVisibilityOverrides,
} from 'shared';

import { extractErrorMessage } from '../auth/form-error';
import { durationToMinutes } from './score-multipliers-panel.component';

const OVERRIDE_FIELDS: (keyof Phase10Overrides)[] = [
  'pause_freezes_floating_score',
  'pause_restores_ownerships_on_resume',
  'pause_rejects_submissions',
  'fail_point_penalty',
  'fail_cooloff_scaling',
  'fail_tower_lockout_minutes',
  'fail_difficulty_rollback',
  'fail_counter_reset',
];

// --- session-control-console: the previously-uncovered OVERRIDABLE_CONFIG_FIELDS
// (organize/models.py) — mode, team rules, tower-locking, live-location,
// realtime/push, NFC, BLE, dementors. Rendered generically via ExtraOverrideDef
// below instead of one hand-written block per field. ---
type ExtraOverrideKey =
  | 'mode'
  | 'min_teams'
  | 'max_teams'
  | 'min_members_per_team'
  | 'max_members_per_team'
  | 'tower_lock_mode'
  | 'tower_lock_finish_minutes'
  | 'location_tracking_enabled'
  | 'location_ping_interval_seconds'
  | 'location_visibility'
  | 'location_retention_days'
  | 'location_consent_text'
  | 'realtime_enabled'
  | 'push_notifications_enabled'
  | 'nfc_secure_mode'
  | 'nfc_require_app'
  | 'nfc_replay_hardening'
  | 'require_ble_capable'
  | 'ble_report_interval_seconds'
  | 'ble_scan_duty_cycle_percent'
  | 'ble_freshness_window_seconds'
  | 'ble_identity_rotation_minutes'
  | 'ble_rssi_very_close_dbm'
  | 'ble_rssi_near_dbm'
  | 'ble_rssi_hysteresis_db'
  | 'dementors_enabled'
  | 'dementor_initial_dementors'
  | 'dementor_starting_energy'
  | 'dementor_drain_per_second'
  | 'dementor_drain_range_bucket'
  | 'dementor_empty_outcome'
  | 'dementor_safety_in_numbers'
  | 'dementor_reverse_group_size'
  | 'dementor_reverse_hold_seconds'
  | 'dementor_conversion_threshold'
  | 'dementor_restore_per_second'
  | 'dementor_wizard_regen_per_second'
  | 'dementor_tick_seconds';

type ExtraOverrides = Pick<AdminSession, ExtraOverrideKey>;

type ExtraFieldType = 'bool' | 'num' | 'select' | 'text';

interface ExtraOverrideDef {
  field: ExtraOverrideKey;
  label: string;
  hint: string;
  type: ExtraFieldType;
  options?: { value: unknown; label: string }[];
  min?: number;
  step?: number;
}

function blankExtraOverrides(): ExtraOverrides {
  return {
    mode: null,
    min_teams: null,
    max_teams: null,
    min_members_per_team: null,
    max_members_per_team: null,
    tower_lock_mode: null,
    tower_lock_finish_minutes: null,
    location_tracking_enabled: null,
    location_ping_interval_seconds: null,
    location_visibility: null,
    location_retention_days: null,
    location_consent_text: null,
    realtime_enabled: null,
    push_notifications_enabled: null,
    nfc_secure_mode: null,
    nfc_require_app: null,
    nfc_replay_hardening: null,
    require_ble_capable: null,
    ble_report_interval_seconds: null,
    ble_scan_duty_cycle_percent: null,
    ble_freshness_window_seconds: null,
    ble_identity_rotation_minutes: null,
    ble_rssi_very_close_dbm: null,
    ble_rssi_near_dbm: null,
    ble_rssi_hysteresis_db: null,
    dementors_enabled: null,
    dementor_initial_dementors: null,
    dementor_starting_energy: null,
    dementor_drain_per_second: null,
    dementor_drain_range_bucket: null,
    dementor_empty_outcome: null,
    dementor_safety_in_numbers: null,
    dementor_reverse_group_size: null,
    dementor_reverse_hold_seconds: null,
    dementor_conversion_threshold: null,
    dementor_restore_per_second: null,
    dementor_wizard_regen_per_second: null,
    dementor_tick_seconds: null,
  };
}

function pickExtraOverrides(s: AdminSession): ExtraOverrides {
  const out = blankExtraOverrides() as unknown as Record<string, unknown>;
  const src = s as unknown as Record<string, unknown>;
  for (const key of Object.keys(out)) {
    out[key] = src[key];
  }
  return out as unknown as ExtraOverrides;
}

type TabKey =
  | 'lifecycle'
  | 'overrides'
  | 'teams'
  | 'boosts'
  | 'scoreboard'
  | 'ownership'
  | 'fails'
  | 'pauses';

interface TabDef {
  key: TabKey;
  label: string;
  icon: string;
}

const TABS: TabDef[] = [
  { key: 'lifecycle', label: 'Lifecycle', icon: 'bi-flag' },
  { key: 'overrides', label: 'Overrides', icon: 'bi-sliders' },
  { key: 'teams', label: 'Teams', icon: 'bi-people' },
  { key: 'boosts', label: 'Boosts', icon: 'bi-lightning-charge' },
  { key: 'scoreboard', label: 'Scoreboard', icon: 'bi-trophy' },
  { key: 'ownership', label: 'Ownership', icon: 'bi-clock-history' },
  { key: 'fails', label: 'Fail counters', icon: 'bi-exclamation-triangle' },
  { key: 'pauses', label: 'Pause history', icon: 'bi-pause-circle' },
];

@Component({
  selector: 'app-staff-session-detail',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [DatePipe, FieldRowComponent, FormsModule, InfoHintComponent, NgTemplateOutlet, PageHeaderComponent, RouterLink, StatusPillComponent],
  template: `
    <a routerLink="/sessions" class="small text-body-secondary">
      &larr; Back to sessions
    </a>

    @if (loadError(); as msg) {
      <div class="alert alert-danger mt-3">{{ msg }}</div>
    } @else if (scoreboard(); as sb) {
      <app-page-header
        [title]="sb.session.name"
        [subtitle]="sb.session.game.name + ' · ' + sb.session.slug"
      >
        @if (session(); as s) {
          <ng-container>
            <app-status-pill actions [status]="s.state" />
            <a actions [routerLink]="['/sessions', sessionId, 'overview']" class="btn btn-sm btn-outline-secondary">
              <i class="bi bi-map"></i> Live overview
            </a>
            <a actions [routerLink]="['/sessions', sessionId, 'replay']" class="btn btn-sm btn-outline-secondary">
              <i class="bi bi-play-btn"></i> Replay
            </a>
            <a actions [routerLink]="['/sessions', s.id, 'discovery']" class="btn btn-sm btn-outline-secondary">
              <i class="bi bi-binoculars"></i> Discovery matrix
            </a>
          </ng-container>
        }
      </app-page-header>

      <!-- In-page tab nav -------------------------------------------------- -->
      <ul class="nav nav-pills gcc-tabs mb-4">
        @for (t of tabs; track t.key) {
          <li class="nav-item">
            <button
              type="button"
              class="nav-link gcc-tab-btn"
              [class.active]="activeTab() === t.key"
              (click)="activeTab.set(t.key)"
            >
              <i class="bi {{ t.icon }} d-none d-sm-inline"></i>
              {{ t.label }}
            </button>
          </li>
        }
      </ul>

      <!-- Lifecycle ---------------------------------------------------------- -->
      <div [hidden]="activeTab() !== 'lifecycle'">
        @if (session(); as s) {
          <div class="card mb-4">
            <div class="card-body">
              <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
                <h2 class="h6 mb-0">
                  State
                  <app-status-pill class="ms-2" [status]="s.state" />
                </h2>
                <div class="d-flex gap-2 flex-wrap">
                  @for (a of s.allowed_transitions; track a) {
                    <button
                      type="button"
                      class="btn btn-sm"
                      [class]="actionButtonClass(a)"
                      [disabled]="lifecycleBusy()"
                      (click)="transition(a)"
                    >
                      @if (lifecycleBusy()) {
                        <span class="spinner-border spinner-border-sm me-1"></span>
                      }
                      {{ actionLabel(a) }}
                    </button>
                  }
                  @if (s.state === 'DRAFT') {
                    <button
                      type="button"
                      class="btn btn-sm btn-success"
                      [disabled]="lifecycleBusy()"
                      (click)="openAndStart()"
                    >
                      @if (lifecycleBusy()) {
                        <span class="spinner-border spinner-border-sm me-1"></span>
                      }
                      Open &amp; start
                    </button>
                  }
                  @if (s.state === 'FINISHED') {
                    <span class="text-body-secondary small align-self-center">
                      Finished sessions are terminal.
                    </span>
                  }
                </div>
              </div>
              <p class="text-body-secondary small mb-0 mt-2">
                DRAFT → OPEN_FOR_PARTICIPANTS → RUNNING ⇄ PAUSED → FINISHED.
                Rosters form while participation is open; finishing closes all
                ownerships and keeps history.
              </p>
              @if (lifecycleError(); as msg) {
                <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
              }
            </div>
          </div>
        }

        @if (readiness(); as r) {
          <div class="card mb-4">
            <div class="card-body">
              <h2 class="h6 mb-0">
                Start readiness
                @if (r.can_start) {
                  <span class="badge text-bg-success ms-2">Ready to start</span>
                } @else {
                  <span class="badge text-bg-warning ms-2">Blocked</span>
                }
              </h2>
              @if (r.blockers.length > 0) {
                <ul class="small text-danger mt-2 mb-2">
                  @for (b of r.blockers; track $index) {
                    <li>{{ b.message }}</li>
                  }
                </ul>
              }
              @if (r.teams.length === 0) {
                <p class="text-body-secondary small mb-0 mt-2">No teams yet.</p>
              } @else {
                <div class="table-responsive mt-2">
                  <table class="table table-sm mb-0">
                    <thead>
                      <tr>
                        <th>Team</th>
                        <th class="text-end">Members</th>
                        <th class="text-end">Required</th>
                        <th>Readiness</th>
                      </tr>
                    </thead>
                    <tbody>
                      @for (t of r.teams; track t.id) {
                        <tr>
                          <td>
                            <span
                              class="d-inline-block me-2"
                              style="width: 0.8rem; height: 0.8rem; border-radius: 50%; vertical-align: middle"
                              [style.background-color]="t.color"
                            ></span>
                            {{ t.name }}
                          </td>
                          <td class="text-end">{{ t.active_member_count }}</td>
                          <td class="text-end">{{ r.min_members_per_team }}</td>
                          <td>
                            @if (t.is_ready) {
                              <span class="badge text-bg-success">ready</span>
                            } @else if (t.members_needed > 0) {
                              <span class="badge text-bg-warning">
                                needs {{ t.members_needed }} more
                              </span>
                            } @else {
                              <span class="badge text-bg-danger">over the cap</span>
                            }
                          </td>
                        </tr>
                      }
                    </tbody>
                  </table>
                </div>
              }
            </div>
          </div>
        }

        <!-- live-overview: screens showing this session ------------------- -->
        <div class="card mb-4">
          <div class="card-body">
            <h2 class="h6 mb-1">
              Big-screen links
              <app-info-hint text="A share link opens this session's live overview on a screen with nobody signed in at it — a projector in the base tent, a TV for parents. It is read-only and reaches this session only. Revoking one stops it immediately, including a screen already showing it." />
            </h2>
            <p class="text-body-secondary small mb-3">
              Player positions follow this session's live-visibility setting rather than your staff
              access, so a session limited to “own team” shows towers and standings but no dots.
            </p>

            @if (linkError(); as msg) {
              <div class="alert alert-danger py-2">{{ msg }}</div>
            }

            <div class="d-flex flex-wrap gap-2 align-items-end mb-3">
              <div>
                <label class="form-label small mb-1" for="overview-link-label">
                  What screen is this?
                </label>
                <input
                  id="overview-link-label"
                  class="form-control form-control-sm"
                  style="min-width: 16rem"
                  placeholder="tent projector"
                  [value]="newLinkLabel()"
                  (input)="newLinkLabel.set($any($event.target).value)"
                />
              </div>
              <button
                type="button"
                class="btn btn-sm btn-primary"
                [disabled]="linkBusy()"
                (click)="createOverviewLink()"
              >
                @if (linkBusy()) {
                  <span class="spinner-border spinner-border-sm me-1"></span>
                }
                Create link
              </button>
            </div>

            @if (overviewLinks().length === 0) {
              <p class="text-body-secondary small mb-0">No share links yet.</p>
            } @else {
              <div class="table-responsive">
                <table class="table table-sm align-middle mb-0">
                  <thead>
                    <tr>
                      <th>Screen</th>
                      <th>Address</th>
                      <th>Status</th>
                      <th class="text-end">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (link of overviewLinks(); track link.id) {
                      <tr [class.opacity-50]="!link.is_usable">
                        <td>{{ link.label || '—' }}</td>
                        <td class="small font-monospace text-truncate" style="max-width: 22rem">
                          {{ link.url }}
                        </td>
                        <td>
                          @if (link.is_usable) {
                            <span class="badge text-bg-success">Active</span>
                          } @else {
                            <span class="badge text-bg-secondary">Revoked</span>
                          }
                        </td>
                        <td class="text-end">
                          @if (link.is_usable) {
                            <button
                              type="button"
                              class="btn btn-sm btn-outline-secondary me-1"
                              (click)="copyOverviewLink(link)"
                            >
                              {{ copiedLinkId() === link.id ? 'Copied' : 'Copy' }}
                            </button>
                            <button
                              type="button"
                              class="btn btn-sm btn-outline-danger"
                              [disabled]="linkBusy()"
                              (click)="revokeOverviewLink(link)"
                            >
                              Revoke
                            </button>
                          }
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            }
          </div>
        </div>

        <!-- Danger zone: destructive ops scoped to THIS session ------------ -->
        <div class="card border-danger mb-4">
          <div class="card-body">
            <h2 class="h6 text-danger mb-1">
              Danger zone
              <app-info-hint text="Towers are shared repository geometry, so 'unassign all' closes ownerships across every session on this Game, not only this one. Reset scores is a global, installation-wide reset — read the confirmation carefully." />
            </h2>
            <p class="text-body-secondary small">
              Acting from <strong>{{ sb.session.name }}</strong>'s console. Before firing either
              action below, this page switches your active session to
              <strong>{{ sb.session.name }}</strong> so the server's game-scoped sweep resolves
              correctly — it no longer depends on whatever session you last picked in the nav
              switcher.
            </p>
            <div class="d-flex flex-wrap gap-2">
              <button
                type="button"
                class="btn btn-outline-warning"
                [disabled]="dangerBusy() !== null"
                (click)="unassignAllForSession()"
              >
                @if (dangerBusy() === 'unassign') {
                  <span class="spinner-border spinner-border-sm me-1"></span>
                }
                Unassign all towers
              </button>
              <button
                type="button"
                class="btn btn-danger"
                [disabled]="dangerBusy() !== null"
                (click)="resetScoresForSession()"
              >
                @if (dangerBusy() === 'reset') {
                  <span class="spinner-border spinner-border-sm me-1"></span>
                }
                Reset all scores
              </button>
            </div>
            @if (dangerNotice(); as msg) {
              <div class="alert alert-success py-2 mt-2 mb-0">{{ msg }}</div>
            }
            @if (dangerError(); as msg) {
              <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
            }
          </div>
        </div>
      </div>

      <!-- Overrides ------------------------------------------------------------ -->
      <div [hidden]="activeTab() !== 'overrides'">
        @if (session(); as s) {
          <p class="text-body-secondary small">
            Leave a field on <em>Inherit</em> (or blank) to use the Game default.
          </p>
          <div class="row g-3">
            <div class="col-md-6">
              @for (b of boolOverrides; track b.field) {
                <div class="mb-2">
                  <label class="form-label small mb-0">{{ b.label }}</label>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="override()[b.field]"
                    (ngModelChange)="setOverride(b.field, $event)"
                  >
                    <option [ngValue]="null">Inherit</option>
                    <option [ngValue]="true">On</option>
                    <option [ngValue]="false">Off</option>
                  </select>
                </div>
              }
              <div class="mb-2">
                <label class="form-label small mb-0">Players may create teams</label>
                <select
                  class="form-select form-select-sm"
                  [ngModel]="teamFormationOverride()"
                  (ngModelChange)="setTeamFormationOverride($event)"
                >
                  <option [ngValue]="null">Inherit</option>
                  <option [ngValue]="true">On</option>
                  <option [ngValue]="false">Off</option>
                </select>
              </div>
            </div>
            <div class="col-md-6">
              @for (n of numOverrides; track n.field) {
                <div class="mb-2">
                  <label class="form-label small mb-0">{{ n.label }}</label>
                  <input
                    class="form-control form-control-sm"
                    type="number"
                    [step]="n.step"
                    [ngModel]="override()[n.field]"
                    (ngModelChange)="setOverride(n.field, $event)"
                    placeholder="Inherit"
                  />
                </div>
              }
              <div class="mb-2">
                <label class="form-label small mb-0">Counter reset</label>
                <select
                  class="form-select form-select-sm"
                  [ngModel]="override().fail_counter_reset"
                  (ngModelChange)="setOverride('fail_counter_reset', $event)"
                >
                  <option [ngValue]="null">Inherit</option>
                  @for (o of resetOptions; track o.value) {
                    <option [ngValue]="o.value">{{ o.label }}</option>
                  }
                </select>
              </div>
              <div class="mb-2">
                <label class="form-label small mb-0">Zone conquest rule</label>
                <select
                  class="form-select form-select-sm"
                  [ngModel]="conquestOverride()"
                  (ngModelChange)="setConquestOverride($event)"
                >
                  <option [ngValue]="null">Inherit</option>
                  @for (o of conquestRuleOptions; track o.value) {
                    <option [ngValue]="o.value">{{ o.label }}</option>
                  }
                </select>
                <div class="form-text">
                  Effective rule: <strong>{{ effectiveConquestRule() }}</strong>
                  (zones with their own override win over this).
                </div>
              </div>
              <div class="mb-2">
                <label class="form-label small mb-0">Score time unit</label>
                <select
                  class="form-select form-select-sm"
                  [ngModel]="timeUnitOverride()"
                  (ngModelChange)="setTimeUnitOverride($event)"
                >
                  <option [ngValue]="null">Inherit</option>
                  @for (o of timeUnitOptions; track o.value) {
                    <option [ngValue]="o.value">{{ o.label }}</option>
                  }
                </select>
                <div class="form-text">
                  Effective unit: <strong>{{ effectiveTimeUnit() }}</strong>
                </div>
              </div>
            </div>
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">Presence rules (presence-rules)</div>
              <div class="row g-2">
                <div class="col-md-3">
                  <label class="form-label small mb-0">Togetherness</label>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="presenceOverride().togetherness_mode"
                    (ngModelChange)="setPresenceOverride('togetherness_mode', $event)"
                  >
                    <option [ngValue]="null">Inherit</option>
                    @for (o of togethernessOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </div>
                <div class="col-md-3">
                  <label class="form-label small mb-0">Teammate map visibility</label>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="presenceOverride().teammate_visibility_mode"
                    (ngModelChange)="setPresenceOverride('teammate_visibility_mode', $event)"
                  >
                    <option [ngValue]="null">Inherit</option>
                    @for (o of teammateVisibilityOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </div>
                <div class="col-md-3">
                  <label class="form-label small mb-0">Nearest N</label>
                  <input
                    class="form-control form-control-sm"
                    type="number"
                    min="0"
                    placeholder="Inherit"
                    [ngModel]="presenceOverride().teammate_visibility_count"
                    (ngModelChange)="setPresenceOverride('teammate_visibility_count', $event)"
                  />
                </div>
                <div class="col-md-3">
                  <label class="form-label small mb-0">Presence window (s)</label>
                  <input
                    class="form-control form-control-sm"
                    type="number"
                    min="0"
                    placeholder="Inherit"
                    [ngModel]="presenceOverride().presence_window_seconds"
                    (ngModelChange)="setPresenceOverride('presence_window_seconds', $event)"
                  />
                </div>
              </div>
            </div>
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">Tower visibility (tower-visibility)</div>
              <div class="row g-2">
                <div class="col-md-3">
                  <label class="form-label small mb-0">Discoverability default</label>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="visibilityOverride().tower_discoverability_default"
                    (ngModelChange)="setVisibilityOverride('tower_discoverability_default', $event)"
                  >
                    <option [ngValue]="null">Inherit</option>
                    @for (o of discoverabilityOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </div>
                <div class="col-md-3">
                  <label class="form-label small mb-0">Challenge visibility default</label>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="visibilityOverride().challenge_visibility_default"
                    (ngModelChange)="setVisibilityOverride('challenge_visibility_default', $event)"
                  >
                    <option [ngValue]="null">Inherit</option>
                    @for (o of challengeVisibilityOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </div>
                <div class="col-md-3">
                  <label class="form-label small mb-0">Fog reveal coverage (%)</label>
                  <input
                    class="form-control form-control-sm"
                    type="number"
                    min="0"
                    max="100"
                    placeholder="Inherit"
                    [ngModel]="visibilityOverride().fog_reveal_coverage_pct_default"
                    (ngModelChange)="setVisibilityOverride('fog_reveal_coverage_pct_default', $event)"
                  />
                </div>
                <div class="col-md-3">
                  <label class="form-label small mb-0">Reveal other teams' ownership</label>
                  <select
                    class="form-select form-select-sm"
                    [ngModel]="visibilityOverride().reveal_other_teams_ownership"
                    (ngModelChange)="setVisibilityOverride('reveal_other_teams_ownership', $event)"
                  >
                    <option [ngValue]="null">Inherit</option>
                    <option [ngValue]="true">Show all teams' control</option>
                    <option [ngValue]="false">Only own control</option>
                  </select>
                </div>
              </div>
            </div>

            <!-- session-control-console: extended override coverage --------- -->
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">Mode</div>
              <div class="row g-2">
                @for (f of modeOverrideFields; track f.field) {
                  <div class="col-md-6">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'ov-' + f.field">
                      <ng-container *ngTemplateOutlet="extraControl; context: { f: f }" />
                      <div class="form-text">Effective: <strong>{{ extraEffectiveLabel(f) }}</strong></div>
                    </app-field-row>
                  </div>
                }
              </div>
            </div>
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">Team rules</div>
              <div class="row g-2">
                @for (f of teamRuleOverrideFields; track f.field) {
                  <div class="col-6 col-md-3">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'ov-' + f.field">
                      <ng-container *ngTemplateOutlet="extraControl; context: { f: f }" />
                    </app-field-row>
                  </div>
                }
              </div>
            </div>
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">Tower locking</div>
              <div class="row g-2">
                @for (f of towerLockOverrideFields; track f.field) {
                  <div class="col-md-4">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'ov-' + f.field">
                      <ng-container *ngTemplateOutlet="extraControl; context: { f: f }" />
                      <div class="form-text">Effective: <strong>{{ extraEffectiveLabel(f) }}</strong></div>
                    </app-field-row>
                  </div>
                }
              </div>
            </div>
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">Live location</div>
              <div class="row g-2">
                @for (f of locationOverrideFields; track f.field) {
                  <div class="col-md-4">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'ov-' + f.field">
                      <ng-container *ngTemplateOutlet="extraControl; context: { f: f }" />
                    </app-field-row>
                  </div>
                }
              </div>
            </div>
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">Realtime &amp; push</div>
              <div class="row g-2">
                @for (f of realtimeOverrideFields; track f.field) {
                  <div class="col-md-4">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'ov-' + f.field">
                      <ng-container *ngTemplateOutlet="extraControl; context: { f: f }" />
                    </app-field-row>
                  </div>
                }
              </div>
            </div>
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">NFC</div>
              <div class="row g-2">
                @for (f of nfcOverrideFields; track f.field) {
                  <div class="col-md-4">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'ov-' + f.field">
                      <ng-container *ngTemplateOutlet="extraControl; context: { f: f }" />
                    </app-field-row>
                  </div>
                }
              </div>
            </div>
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">BLE proximity</div>
              <div class="row g-2">
                @for (f of bleOverrideFields; track f.field) {
                  <div class="col-6 col-md-3">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'ov-' + f.field">
                      <ng-container *ngTemplateOutlet="extraControl; context: { f: f }" />
                    </app-field-row>
                  </div>
                }
              </div>
            </div>
            <div class="col-12">
              <div class="fw-semibold small mb-2 mt-2">Dementors</div>
              <div class="row g-2">
                @for (f of dementorOverrideFields; track f.field) {
                  <div class="col-6 col-md-3">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'ov-' + f.field">
                      <ng-container *ngTemplateOutlet="extraControl; context: { f: f }" />
                    </app-field-row>
                  </div>
                }
              </div>
            </div>
          </div>
          <button
            type="button"
            class="btn btn-primary btn-sm mt-3"
            [disabled]="!overrideDirty() || overrideSaving()"
            (click)="saveOverrides(s.id)"
          >
            @if (overrideSaving()) {
              <span class="spinner-border spinner-border-sm me-1"></span>
            }
            Save overrides
          </button>
          @if (overrideError(); as msg) {
            <div class="small text-danger mt-1">{{ msg }}</div>
          }
        }
      </div>

      <!-- Generic Inherit/On/Off/value control for the "extra" overrides -->
      <ng-template #extraControl let-f="f">
        @switch (f.type) {
          @case ('bool') {
            <select
              class="form-select form-select-sm"
              [id]="'ov-' + f.field"
              [ngModel]="extraValue(f.field)"
              (ngModelChange)="setExtraOverride(f.field, $event)"
            >
              <option [ngValue]="null">Inherit</option>
              <option [ngValue]="true">On</option>
              <option [ngValue]="false">Off</option>
            </select>
          }
          @case ('select') {
            <select
              class="form-select form-select-sm"
              [id]="'ov-' + f.field"
              [ngModel]="extraValue(f.field)"
              (ngModelChange)="setExtraOverride(f.field, $event)"
            >
              <option [ngValue]="null">Inherit</option>
              @for (o of f.options; track o.value) {
                <option [ngValue]="o.value">{{ o.label }}</option>
              }
            </select>
          }
          @case ('text') {
            <input
              class="form-control form-control-sm"
              type="text"
              [id]="'ov-' + f.field"
              placeholder="Inherit"
              [ngModel]="extraValue(f.field)"
              (ngModelChange)="setExtraOverride(f.field, $event)"
            />
          }
          @default {
            <input
              class="form-control form-control-sm"
              type="number"
              [id]="'ov-' + f.field"
              [step]="f.step ?? 1"
              [min]="f.min ?? null"
              placeholder="Inherit"
              [ngModel]="extraValue(f.field)"
              (ngModelChange)="setExtraOverrideNum(f.field, $event)"
            />
          }
        }
      </ng-template>

      <!-- Teams -------------------------------------------------------------- -->
      <div [hidden]="activeTab() !== 'teams'">
        <div class="card mb-4">
          <div class="card-body">
            <p class="text-body-secondary small">
              Distribute unassigned players (players in this session without a
              team) into new teams. Best-effort — edit the result on the
              <a routerLink="/teams">Teams</a> page before the session starts.
            </p>
            <div class="row g-2 align-items-end">
              <div class="col-auto">
                <label class="form-label small mb-0" for="team-count">Number of teams</label>
                <input
                  id="team-count"
                  class="form-control form-control-sm"
                  type="number"
                  min="1"
                  [ngModel]="buildCount()"
                  (ngModelChange)="buildCount.set($event)"
                />
              </div>
              <div class="col-auto">
                <button
                  type="button"
                  class="btn btn-sm btn-outline-primary"
                  [disabled]="buildBusy() || !buildCount()"
                  (click)="shuffleTeams()"
                >
                  <i class="bi bi-shuffle"></i> Random shuffle
                </button>
              </div>
              <div class="col-auto">
                <label class="form-label small mb-0" for="balance-keys">
                  Balance by attribute keys (comma-separated)
                </label>
                <input
                  id="balance-keys"
                  class="form-control form-control-sm"
                  type="text"
                  placeholder="e.g. age_group, experience"
                  [ngModel]="buildKeys()"
                  (ngModelChange)="buildKeys.set($event)"
                />
              </div>
              <div class="col-auto">
                <button
                  type="button"
                  class="btn btn-sm btn-outline-primary"
                  [disabled]="buildBusy() || !buildCount() || !buildKeys().trim()"
                  (click)="balanceTeams()"
                >
                  <i class="bi bi-sliders"></i> Balanced build
                </button>
              </div>
            </div>
            @if (buildError(); as msg) {
              <div class="alert alert-danger py-2 mt-2 mb-0">{{ msg }}</div>
            }
            @if (buildResult(); as res) {
              <div class="alert alert-success py-2 mt-2 mb-2">
                Assigned {{ res.assigned }} player(s) into {{ res.teams.length }} team(s).
              </div>
              <ul class="list-group">
                @for (t of res.teams; track t.id) {
                  <li class="list-group-item py-1 small">
                    <span class="fw-semibold">{{ t.name }}</span>:
                    {{ t.members.join(', ') || '—' }}
                  </li>
                }
              </ul>
            }
          </div>
        </div>
      </div>

      <!-- Boosts / multipliers ------------------------------------------------ -->
      <div [hidden]="activeTab() !== 'boosts'">
        <div class="card mb-4">
          <div class="card-body">
            <h2 class="h6 mb-2">
              Score boosts
              @for (b of activeBoosts(); track b.id) {
                <span class="badge text-bg-warning ms-2">
                  <i class="bi bi-lightning-charge-fill"></i>
                  &times;{{ b.factor }} {{ boostTarget(b) }}
                </span>
              }
              @if (activeBoosts().length === 0) {
                <span class="badge text-bg-light border ms-2">none in effect</span>
              }
            </h2>
            <p class="text-body-secondary small mb-2">
              Factors multiply into floating zone points and tower capture
              bonuses from this instant forward — locked history is never
              rewritten. Overlapping boosts stack multiplicatively.
            </p>

            @if (multipliers().length > 0) {
              <div class="table-responsive">
                <table class="table table-sm align-middle mb-2">
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>Scope</th>
                      <th class="text-end">Factor</th>
                      <th>Window</th>
                      <th>Owner</th>
                      <th>Enabled</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    @for (m of multipliers(); track m.id) {
                      <tr>
                        <td>
                          <span class="badge" [class]="typeBadgeClass(m.multiplier_type)">
                            {{ m.multiplier_type }}
                          </span>
                          @if (m.label) {
                            <div class="small text-body-secondary">{{ m.label }}</div>
                          }
                        </td>
                        <td class="small">{{ multiplierScope(m) }}</td>
                        <td class="text-end fw-semibold">&times;{{ m.factor }}</td>
                        <td class="small">{{ multiplierWindow(m) }}</td>
                        <td class="small">
                          @if (m.session !== null) {
                            <span class="badge text-bg-info">this session</span>
                          } @else {
                            <span class="badge text-bg-light border">game template</span>
                          }
                        </td>
                        <td>
                          @if (m.is_active) {
                            <span class="badge text-bg-success">on</span>
                          } @else {
                            <span class="badge text-bg-secondary">off</span>
                          }
                        </td>
                        <td class="text-end">
                          <button
                            type="button"
                            class="btn btn-sm"
                            [class]="m.is_active ? 'btn-outline-warning' : 'btn-outline-success'"
                            [disabled]="togglingId() === m.id"
                            (click)="toggleMultiplier(m)"
                          >
                            @if (togglingId() === m.id) {
                              <span class="spinner-border spinner-border-sm me-1"></span>
                            }
                            {{ m.is_active ? 'Deactivate' : 'Activate' }}
                          </button>
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
              </div>
            } @else {
              <div class="small text-body-secondary mb-2">
                No multipliers configured — scoring runs at the normal 1&times;.
              </div>
            }

            <form class="row g-2 align-items-end" (ngSubmit)="dropBoost()">
              <div class="col-md-2">
                <label class="form-label small mb-0" for="boost-type">Type</label>
                <select
                  id="boost-type"
                  class="form-select form-select-sm"
                  [ngModel]="boostType()"
                  (ngModelChange)="boostType.set($event)"
                  name="boost_type"
                >
                  <option ngValue="RANDOM_BONUS">Random bonus</option>
                  <option ngValue="MANUAL">Manual toggle</option>
                </select>
              </div>
              <div class="col-md-2">
                <label class="form-label small mb-0" for="boost-scope">Scope</label>
                <select
                  id="boost-scope"
                  class="form-select form-select-sm"
                  [ngModel]="boostScope()"
                  (ngModelChange)="boostScope.set($event)"
                  name="boost_scope"
                >
                  <option ngValue="GLOBAL">Everywhere</option>
                  <option ngValue="TOWER">One tower</option>
                  <option ngValue="ZONE">One zone</option>
                </select>
              </div>
              @if (boostScope() === 'TOWER') {
                <div class="col-md-2">
                  <label class="form-label small mb-0" for="boost-tower">Tower</label>
                  <select
                    id="boost-tower"
                    class="form-select form-select-sm"
                    [ngModel]="boostTower()"
                    (ngModelChange)="boostTower.set($event)"
                    name="boost_tower"
                  >
                    <option [ngValue]="null">—</option>
                    @for (t of gameTowers(); track t.id) {
                      <option [ngValue]="t.id">{{ t.name }}</option>
                    }
                  </select>
                </div>
              }
              @if (boostScope() === 'ZONE') {
                <div class="col-md-2">
                  <label class="form-label small mb-0" for="boost-zone">Zone</label>
                  <select
                    id="boost-zone"
                    class="form-select form-select-sm"
                    [ngModel]="boostZone()"
                    (ngModelChange)="boostZone.set($event)"
                    name="boost_zone"
                  >
                    <option [ngValue]="null">—</option>
                    @for (z of gameZones(); track z.id) {
                      <option [ngValue]="z.id">{{ z.name }}</option>
                    }
                  </select>
                </div>
              }
              <div class="col-md-2">
                <label class="form-label small mb-0" for="boost-factor">Factor (&gt; 0)</label>
                <input
                  id="boost-factor"
                  class="form-control form-control-sm"
                  type="number"
                  min="0.1"
                  step="0.1"
                  [ngModel]="boostFactor()"
                  (ngModelChange)="boostFactor.set($event)"
                  name="boost_factor"
                  required
                />
              </div>
              <div class="col-md-2">
                <label class="form-label small mb-0" for="boost-minutes">
                  Duration (min)
                </label>
                <input
                  id="boost-minutes"
                  class="form-control form-control-sm"
                  type="number"
                  min="1"
                  placeholder="blank = until toggled"
                  [ngModel]="boostMinutes()"
                  (ngModelChange)="boostMinutes.set($event)"
                  name="boost_minutes"
                />
              </div>
              <div class="col-md-2">
                <label class="form-label small mb-0" for="boost-label">Label</label>
                <input
                  id="boost-label"
                  class="form-control form-control-sm"
                  type="text"
                  placeholder="shown to players"
                  [ngModel]="boostLabel()"
                  (ngModelChange)="boostLabel.set($event)"
                  name="boost_label"
                />
              </div>
              <div class="col-auto">
                <button
                  type="submit"
                  class="btn btn-sm btn-warning"
                  [disabled]="boostBusy() || !canDropBoost()"
                >
                  @if (boostBusy()) {
                    <span class="spinner-border spinner-border-sm me-1"></span>
                  }
                  <i class="bi bi-lightning-charge"></i> Drop boost
                </button>
              </div>
              @if (boostError(); as msg) {
                <div class="col-12"><div class="small text-danger">{{ msg }}</div></div>
              }
            </form>
          </div>
        </div>
      </div>

      <!-- Scoreboard ----------------------------------------------------------- -->
      <div [hidden]="activeTab() !== 'scoreboard'">
        <div class="table-responsive">
          <table class="table">
            <thead>
              <tr>
                <th style="width: 3rem">#</th>
                <th>Team</th>
                <th>Group</th>
                <th class="text-end">Locked</th>
                <th class="text-end">Floating</th>
                <th class="text-end">Score</th>
              </tr>
            </thead>
            <tbody>
              @for (e of sb.entries; track e.team_id; let i = $index) {
                <tr>
                  <td class="fw-semibold">{{ i + 1 }}</td>
                  <td>
                    <span
                      class="d-inline-block me-2"
                      style="width: 0.9rem; height: 0.9rem; border-radius: 50%; vertical-align: middle"
                      [style.background-color]="e.team_color"
                    ></span>
                    <span class="fw-semibold">{{ e.team_name }}</span>
                  </td>
                  <td class="small text-body-secondary">
                    {{ e.group_name || '—' }}
                  </td>
                  <td class="text-end">{{ e.locked_score }}</td>
                  <td class="text-end">{{ e.floating_score }}</td>
                  <td class="text-end fw-semibold">{{ e.current_score }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </div>

      <!-- Ownership timeline ----------------------------------------------- -->
      <div [hidden]="activeTab() !== 'ownership'">
        @if (timeline(); as tl) {
          @if (tl.events.length === 0) {
            <div class="alert alert-info">No tower captures recorded.</div>
          } @else {
            <div class="table-responsive">
              <table class="table">
                <thead>
                  <tr>
                    <th>Team</th>
                    <th>Tower</th>
                    <th>Captured</th>
                    <th>Released</th>
                  </tr>
                </thead>
                <tbody>
                  @for (ev of tl.events; track ev.id) {
                    <tr>
                      <td>
                        <span
                          class="d-inline-block me-2"
                          style="width: 0.8rem; height: 0.8rem; border-radius: 50%; vertical-align: middle"
                          [style.background-color]="ev.team_color"
                        ></span>
                        {{ ev.team_name }}
                      </td>
                      <td>{{ ev.tower_name }}</td>
                      <td class="small text-body-secondary">
                        {{ ev.timestamp_start | date: 'medium' }}
                      </td>
                      <td class="small text-body-secondary">
                        @if (ev.timestamp_end; as ended) {
                          {{ ended | date: 'medium' }}
                        } @else {
                          <em>still held</em>
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

      <!-- Failure lockouts --------------------------------------------------- -->
      <div [hidden]="activeTab() !== 'fails'">
        @if (failCounters().length === 0) {
          <div class="alert alert-info">No active fail counters.</div>
        } @else {
          <div class="table-responsive">
            <table class="table">
              <thead>
                <tr>
                  <th>Team</th>
                  <th>Tower</th>
                  <th class="text-end">Consecutive fails</th>
                  <th>Locked until</th>
                </tr>
              </thead>
              <tbody>
                @for (c of failCounters(); track c.team_id + '-' + c.tower_id) {
                  <tr>
                    <td>
                      <span
                        class="d-inline-block me-2"
                        style="width: 0.8rem; height: 0.8rem; border-radius: 50%; vertical-align: middle"
                        [style.background-color]="c.team_color"
                      ></span>
                      {{ c.team_name }}
                    </td>
                    <td>{{ c.tower_name }}</td>
                    <td class="text-end fw-semibold">{{ c.consecutive_fails }}</td>
                    <td class="small">
                      @if (c.is_locked && c.locked_until) {
                        <span class="badge text-bg-danger me-1">locked</span>
                        {{ c.locked_until | date: 'medium' }}
                      } @else {
                        <span class="text-body-secondary">—</span>
                      }
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        }
      </div>

      <!-- Pause history -------------------------------------------------------- -->
      <div [hidden]="activeTab() !== 'pauses'">
        @if (pauseHistory(); as ph) {
          @if (ph.windows.length === 0) {
            <p class="text-body-secondary small mb-0 mt-2">No pauses yet.</p>
          } @else {
            <div class="table-responsive mt-2">
              <table class="table table-sm mb-0">
                <thead>
                  <tr><th>Started</th><th>Ended</th><th>Restores on resume</th></tr>
                </thead>
                <tbody>
                  @for (w of ph.windows; track w.id) {
                    <tr>
                      <td class="small">{{ w.started_at | date: 'medium' }}</td>
                      <td class="small">
                        @if (w.ended_at; as e) {
                          {{ e | date: 'medium' }}
                        } @else {
                          <span class="badge text-bg-warning">open</span>
                        }
                      </td>
                      <td class="small">{{ w.restore_on_resume ? 'yes' : 'no' }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          }
        }
      </div>
    } @else {
      <div class="d-flex align-items-center text-body-secondary mt-3">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading session…
      </div>
    }
  `,
  styles: `
    .gcc-tabs {
      flex-wrap: wrap;
      gap: var(--space-1);
    }

    .gcc-tab-btn {
      min-height: 44px;
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
    }

    @media (max-width: 640px) {
      .gcc-tabs {
        flex-direction: column;
        align-items: stretch;
      }
    }
  `,
})
export class StaffSessionDetailComponent {
  private readonly route = inject(ActivatedRoute);
  private readonly api = inject(GameApiService);
  private readonly staff = inject(StaffApiService);
  private readonly confirmService = inject(ConfirmService);

  protected readonly tabs = TABS;
  protected readonly activeTab = signal<TabKey>('lifecycle');

  protected readonly scoreboard = signal<SessionScoreboard | null>(null);
  protected readonly timeline = signal<SessionTimeline | null>(null);
  protected readonly session = signal<AdminSession | null>(null);
  protected readonly pauseHistory = signal<PauseHistory | null>(null);
  protected readonly failCounters = signal<FailCounterInfo[]>([]);
  protected readonly loadError = signal<string | null>(null);

  protected readonly lifecycleBusy = signal(false);
  protected readonly lifecycleError = signal<string | null>(null);

  // live-overview: share links pointing screens at this session.
  protected readonly overviewLinks = signal<OverviewLink[]>([]);
  protected readonly linkBusy = signal(false);
  protected readonly linkError = signal<string | null>(null);
  protected readonly newLinkLabel = signal('');
  protected readonly copiedLinkId = signal<number | null>(null);

  // Start readiness (team rules) — read-only; the lifecycle `start`
  // transition enforces these blockers server-side.
  protected readonly readiness = signal<StartReadiness | null>(null);

  protected readonly override = signal<Phase10Overrides>(blankOverrides());
  protected readonly teamFormationOverride = signal<boolean | null>(null);
  protected readonly presenceOverride = signal<PresenceRulesOverrides>(
    blankPresenceOverrides(),
  );
  // Tower-visibility overrides (null = inherit the Game default).
  protected readonly visibilityOverride = signal<TowerVisibilityOverrides>(
    blankVisibilityOverrides(),
  );
  // Conquest & scoring overrides (null = inherit the Game default).
  protected readonly conquestOverride = signal<ConquestRule | null>(null);
  protected readonly timeUnitOverride = signal<ScoreTimeUnit | null>(null);
  // Extended coverage: mode, team rules, tower-locking, live-location,
  // realtime/push, NFC, BLE, dementors (session-control-console).
  protected readonly extraOverrides = signal<ExtraOverrides>(blankExtraOverrides());
  // The Session's Game — fetched for the effective-value readout.
  protected readonly game = signal<AdminGame | null>(null);

  protected readonly buildCount = signal<number | null>(null);
  protected readonly buildKeys = signal('');
  protected readonly buildBusy = signal(false);
  protected readonly buildError = signal<string | null>(null);
  protected readonly buildResult = signal<TeamBuildResult | null>(null);

  // ---- Big-screen share links (live-overview) ------------------------------

  private refreshOverviewLinks(): void {
    this.staff.overviewLinks(this.sessionId).subscribe({
      next: (list) => this.overviewLinks.set(list),
      error: () => {},
    });
  }

  protected createOverviewLink(): void {
    this.linkBusy.set(true);
    this.linkError.set(null);
    this.staff
      .createOverviewLink(this.sessionId, { label: this.newLinkLabel().trim() })
      .subscribe({
        next: (link) => {
          this.overviewLinks.set([link, ...this.overviewLinks()]);
          this.newLinkLabel.set('');
          this.linkBusy.set(false);
        },
        error: (err) => {
          this.linkBusy.set(false);
          this.linkError.set(extractErrorMessage(err));
        },
      });
  }

  protected async revokeOverviewLink(link: OverviewLink): Promise<void> {
    // Confirmed because it is not undoable and it reaches outward: the
    // screen it kills is one somebody else is watching.
    const ok = await this.confirmService.confirm({
      title: 'Revoke this link?',
      message:
        `“${link.label || link.token.slice(0, 8)}” stops working immediately, including any ` +
        'screen already showing it. This cannot be undone — issue a new link instead.',
      confirmLabel: 'Revoke',
      danger: true,
    });
    if (!ok) return;
    this.linkBusy.set(true);
    this.linkError.set(null);
    this.staff.revokeOverviewLink(link.id).subscribe({
      next: (updated) => {
        this.overviewLinks.set(
          this.overviewLinks().map((row) => (row.id === updated.id ? updated : row)),
        );
        this.linkBusy.set(false);
      },
      error: (err) => {
        this.linkBusy.set(false);
        this.linkError.set(extractErrorMessage(err));
      },
    });
  }

  protected copyOverviewLink(link: OverviewLink): void {
    navigator.clipboard?.writeText(link.url).then(
      () => {
        this.copiedLinkId.set(link.id);
        setTimeout(() => this.copiedLinkId.set(null), 2000);
      },
      () => this.linkError.set('Could not copy — select the address and copy it manually.'),
    );
  }

  // ---- Score boosts (score-multipliers) -----------------------------------
  protected readonly multipliers = signal<AdminScoreMultiplier[]>([]);
  protected readonly activeBoosts = signal<ActiveMultiplier[]>([]);
  protected readonly togglingId = signal<number | null>(null);
  protected readonly boostType = signal<ScoreMultiplierType>('RANDOM_BONUS');
  protected readonly boostScope = signal<ScoreMultiplierScope>('GLOBAL');
  protected readonly boostTower = signal<number | null>(null);
  protected readonly boostZone = signal<number | null>(null);
  protected readonly boostFactor = signal<number | null>(2);
  protected readonly boostMinutes = signal<number | null>(null);
  protected readonly boostLabel = signal('');
  protected readonly boostBusy = signal(false);
  protected readonly boostError = signal<string | null>(null);

  // ---- Danger zone: destructive ops scoped to this session -----------------
  protected readonly dangerBusy = signal<'unassign' | 'reset' | null>(null);
  protected readonly dangerNotice = signal<string | null>(null);
  protected readonly dangerError = signal<string | null>(null);

  private readonly allTowers = signal<AdminTower[]>([]);
  private readonly allZones = signal<AdminZone[]>([]);

  /** Geometry usable by this session's game (repository usage refs). */
  protected readonly gameTowers = computed(() => {
    const gameId = this.session()?.game;
    if (!gameId) return [];
    return this.allTowers().filter((t) => t.games.some((g) => g.id === gameId));
  });
  protected readonly gameZones = computed(() => {
    const gameId = this.session()?.game;
    if (!gameId) return [];
    return this.allZones().filter((z) => z.games.some((g) => g.id === gameId));
  });

  protected readonly canDropBoost = computed(() => {
    const factor = this.boostFactor();
    if (factor === null || factor <= 0) return false;
    if (this.boostScope() === 'TOWER' && this.boostTower() === null) return false;
    if (this.boostScope() === 'ZONE' && this.boostZone() === null) return false;
    return true;
  });
  protected readonly overrideDirty = signal(false);
  protected readonly overrideSaving = signal(false);
  protected readonly overrideError = signal<string | null>(null);

  protected readonly boolOverrides: { field: keyof Phase10Overrides; label: string }[] = [
    { field: 'pause_freezes_floating_score', label: 'Freeze floating score while paused' },
    { field: 'pause_restores_ownerships_on_resume', label: 'Restore ownerships on resume' },
    { field: 'pause_rejects_submissions', label: 'Reject submissions while paused' },
    { field: 'fail_difficulty_rollback', label: 'Difficulty rollback after failure' },
  ];

  protected readonly numOverrides: { field: keyof Phase10Overrides; label: string; step: number }[] = [
    { field: 'fail_point_penalty', label: 'Point penalty', step: 1 },
    { field: 'fail_cooloff_scaling', label: 'Cooloff scaling (≥1)', step: 0.1 },
    { field: 'fail_tower_lockout_minutes', label: 'Tower lockout (min)', step: 1 },
  ];

  protected readonly resetOptions: { value: FailCounterReset; label: string }[] = [
    { value: 'TOWER_SUCCESS_ONLY', label: 'Reset only on success at the same tower' },
    { value: 'ANY_SUCCESS_ELSEWHERE', label: 'Reset on any confirmed submission' },
    { value: 'ANY_ATTEMPT_ELSEWHERE', label: 'Reset on any submission anywhere' },
  ];

  protected readonly togethernessOptions: { value: TogethernessMode; label: string }[] = [
    { value: 'SPLIT_ALLOWED', label: 'Members may split up' },
    { value: 'WHOLE_TEAM_TOGETHER', label: 'Whole team together' },
  ];

  protected readonly discoverabilityOptions: { value: Discoverability; label: string }[] = [
    { value: 'VISIBLE', label: 'Visible (default)' },
    { value: 'HIDDEN', label: 'Hidden — pops up on approach' },
    { value: 'FOG_REVEAL', label: 'Fog reveal — uncover the zone' },
  ];

  protected readonly challengeVisibilityOptions: {
    value: ChallengeVisibility;
    label: string;
  }[] = [
    { value: 'VISIBLE_ANYWHERE', label: 'Visible anywhere (default)' },
    { value: 'HIDDEN_UNTIL_ARRIVAL', label: 'Hidden until arrival' },
  ];

  protected readonly teammateVisibilityOptions: {
    value: TeammateVisibilityMode;
    label: string;
  }[] = [
    { value: 'OWN_TEAM', label: 'Own team only' },
    { value: 'EVERYONE', label: 'Everyone' },
    { value: 'SELECT_COUNT', label: 'Nearest N players' },
  ];

  protected readonly conquestRuleOptions: { value: ConquestRule; label: string }[] = [
    { value: 'MAJORITY', label: 'Majority of towers (default)' },
    { value: 'ALL', label: 'All towers — hold every active tower' },
    { value: 'ANY', label: 'Any tower — most towers, latest capture breaks ties' },
  ];

  protected readonly timeUnitOptions: { value: ScoreTimeUnit; label: string }[] = [
    { value: 'SECOND', label: 'Seconds' },
    { value: 'MINUTE', label: 'Minutes (default)' },
    { value: 'HOUR', label: 'Hours' },
  ];

  // ---- Extended override field metadata (session-control-console) ----------

  protected readonly modeOverrideFields: ExtraOverrideDef[] = [
    {
      field: 'mode',
      label: 'Game mode',
      hint: 'Domination vs Trail. Rarely overridden per-session, but available for a one-off variant run.',
      type: 'select',
      options: [
        { value: 'DOMINATION', label: 'Domination' },
        { value: 'TRAIL', label: 'Trail / discovery' },
      ] as { value: GameMode; label: string }[],
    },
  ];

  protected readonly teamRuleOverrideFields: ExtraOverrideDef[] = [
    { field: 'min_teams', label: 'Min teams', hint: 'Overrides the Game default for this run only.', type: 'num', min: 1 },
    { field: 'max_teams', label: 'Max teams', hint: '0 means no cap.', type: 'num', min: 0 },
    { field: 'min_members_per_team', label: 'Min members/team', hint: 'Overrides the Game default for this run only.', type: 'num', min: 1 },
    { field: 'max_members_per_team', label: 'Max members/team', hint: '0 means no cap.', type: 'num', min: 0 },
  ];

  protected readonly towerLockOverrideFields: ExtraOverrideDef[] = [
    {
      field: 'tower_lock_mode',
      label: 'Lock mode',
      hint: 'Free for all vs an exclusive finish window for the initiating team.',
      type: 'select',
      options: [
        { value: 'FREE_FOR_ALL', label: 'Free for all' },
        { value: 'LOCK_ON_INITIATE', label: 'Lock on initiate' },
      ] as { value: TowerLockMode; label: string }[],
    },
    { field: 'tower_lock_finish_minutes', label: 'Finish window (min)', hint: 'Only used in Lock on initiate.', type: 'num', min: 1 },
  ];

  protected readonly locationOverrideFields: ExtraOverrideDef[] = [
    { field: 'location_tracking_enabled', label: 'Track player locations', hint: 'Off by default game-wide; enable just for this run.', type: 'bool' },
    { field: 'location_ping_interval_seconds', label: 'Ping interval (s)', hint: 'How often a phone reports its position.', type: 'num', min: 5 },
    {
      field: 'location_visibility',
      label: 'Visibility',
      hint: 'Who sees live positions.',
      type: 'select',
      options: [
        { value: 'NONE', label: 'Stored only' },
        { value: 'OWN_TEAM', label: 'Own team' },
        { value: 'EVERYONE', label: 'Everyone' },
      ] as { value: LocationVisibility; label: string }[],
    },
    { field: 'location_retention_days', label: 'Retention (days)', hint: 'How long raw pings are kept.', type: 'num', min: 1 },
    { field: 'location_consent_text', label: 'Consent text', hint: 'Shown to players before tracking starts.', type: 'text' },
  ];

  protected readonly realtimeOverrideFields: ExtraOverrideDef[] = [
    { field: 'realtime_enabled', label: 'Realtime updates', hint: 'Live map/scoreboard over WebSocket, with polling fallback.', type: 'bool' },
    { field: 'push_notifications_enabled', label: 'Push notifications', hint: "Send push notifications to players' devices.", type: 'bool' },
  ];

  protected readonly nfcOverrideFields: ExtraOverrideDef[] = [
    { field: 'nfc_secure_mode', label: 'Secure token mode', hint: 'Secure NFC token flow instead of legacy forwardable URLs.', type: 'bool' },
    { field: 'nfc_require_app', label: 'Require the player app', hint: 'Scans must open inside the app.', type: 'bool' },
    { field: 'nfc_replay_hardening', label: 'Replay hardening', hint: 'Reject a repeat scan of the same token in quick succession.', type: 'bool' },
  ];

  protected readonly bleOverrideFields: ExtraOverrideDef[] = [
    { field: 'require_ble_capable', label: 'Require BLE-capable device', hint: 'Gate BLE-only proximity challenges.', type: 'bool' },
    { field: 'ble_report_interval_seconds', label: 'Report interval (s)', hint: 'How often a phone reports nearby beacons.', type: 'num' },
    { field: 'ble_scan_duty_cycle_percent', label: 'Scan duty cycle (%)', hint: 'Share of each interval spent scanning.', type: 'num' },
    { field: 'ble_freshness_window_seconds', label: 'Freshness window (s)', hint: 'A sighting older than this is stale.', type: 'num' },
    { field: 'ble_identity_rotation_minutes', label: 'Identity rotation (min)', hint: "How often a beacon's identity rotates.", type: 'num' },
    { field: 'ble_rssi_very_close_dbm', label: 'RSSI very close (dBm)', hint: 'Threshold for the "very close" bucket.', type: 'num' },
    { field: 'ble_rssi_near_dbm', label: 'RSSI near (dBm)', hint: 'Threshold for the "near" bucket.', type: 'num' },
    { field: 'ble_rssi_hysteresis_db', label: 'RSSI hysteresis (dB)', hint: 'Buffer before flipping between buckets.', type: 'num' },
  ];

  protected readonly dementorOverrideFields: ExtraOverrideDef[] = [
    { field: 'dementors_enabled', label: 'Dementors enabled', hint: 'Turns the mini-mode on for this run only.', type: 'bool' },
    { field: 'dementor_initial_dementors', label: 'Initial dementors', hint: 'How many start active.', type: 'num', min: 0 },
    { field: 'dementor_starting_energy', label: 'Starting energy', hint: "Each wizard's starting energy.", type: 'num', step: 0.1 },
    { field: 'dementor_drain_per_second', label: 'Drain / second', hint: 'Energy drained per second in range.', type: 'num', step: 0.1 },
    {
      field: 'dementor_drain_range_bucket',
      label: 'Drain range',
      hint: 'BLE proximity bucket required to drain.',
      type: 'select',
      options: [
        { value: 'VERY_CLOSE', label: 'Very close' },
        { value: 'NEAR', label: 'Near' },
        { value: 'FAR', label: 'Far' },
      ] as { value: ProximityBucket; label: string }[],
    },
    {
      field: 'dementor_empty_outcome',
      label: 'On empty',
      hint: 'What happens to a drained wizard.',
      type: 'select',
      options: [
        { value: 'FLIP', label: 'Flip to dementor' },
        { value: 'DIE', label: 'Out of play' },
      ] as { value: DementorEmptyOutcome; label: string }[],
    },
    { field: 'dementor_safety_in_numbers', label: 'Safety in numbers', hint: 'Groups drain slower / resist better.', type: 'bool' },
    { field: 'dementor_reverse_group_size', label: 'Reverse group size', hint: 'Wizards needed to banish a dementor.', type: 'num', min: 1 },
    { field: 'dementor_reverse_hold_seconds', label: 'Reverse hold (s)', hint: 'Hold time required to complete a reversal.', type: 'num', min: 0 },
    { field: 'dementor_conversion_threshold', label: 'Conversion threshold', hint: 'Energy needed for a dementor to convert/spawn.', type: 'num', step: 0.1 },
    { field: 'dementor_restore_per_second', label: 'Restore / second', hint: 'Regen once out of range.', type: 'num', step: 0.1 },
    { field: 'dementor_wizard_regen_per_second', label: 'Passive regen / second', hint: '0 = none.', type: 'num', step: 0.1 },
    { field: 'dementor_tick_seconds', label: 'Simulation tick (s)', hint: 'How often the sim ticks.', type: 'num', min: 1 },
  ];

  protected readonly sessionId = Number(this.route.snapshot.paramMap.get('id'));

  constructor() {
    if (!this.sessionId) {
      this.loadError.set('Invalid session.');
      return;
    }
    forkJoin({
      scoreboard: this.api.sessionScoreboard(this.sessionId),
      timeline: this.api.sessionTimeline(this.sessionId),
      session: this.staff.getSession(this.sessionId),
      pauseHistory: this.staff.sessionPauseHistory(this.sessionId),
      failCounters: this.staff.sessionFailCounters(this.sessionId),
    }).subscribe({
      next: (r) => {
        this.scoreboard.set(r.scoreboard);
        this.timeline.set(r.timeline);
        this.setSession(r.session);
        this.pauseHistory.set(r.pauseHistory);
        this.failCounters.set(r.failCounters);
      },
      error: (err) => this.loadError.set(extractErrorMessage(err)),
    });
    this.refreshMultipliers();
    this.refreshOverviewLinks();
    forkJoin({
      towers: this.staff.listTowers(),
      zones: this.staff.listZones(),
    }).subscribe({
      next: ({ towers, zones }) => {
        this.allTowers.set(towers);
        this.allZones.set(zones);
      },
      error: () => {},
    });
  }

  // ---- Score boosts (score-multipliers) -----------------------------------

  private refreshMultipliers(): void {
    this.staff.listSessionMultipliers(this.sessionId).subscribe({
      next: (list) => this.multipliers.set(list),
      error: () => {},
    });
    this.api.sessionActiveMultipliers(this.sessionId).subscribe({
      next: (list) => this.activeBoosts.set(list),
      error: () => {},
    });
  }

  protected boostTarget(b: ActiveMultiplier): string {
    if (b.label) return b.label;
    if (b.scope === 'TOWER') return `at ${b.tower_name}`;
    if (b.scope === 'ZONE') return `in ${b.zone_name}`;
    return 'everywhere';
  }

  protected multiplierScope(m: AdminScoreMultiplier): string {
    if (m.scope === 'TOWER') return `Tower: ${m.tower_name ?? m.tower}`;
    if (m.scope === 'ZONE') return `Zone: ${m.zone_name ?? m.zone}`;
    return 'Everywhere';
  }

  protected multiplierWindow(m: AdminScoreMultiplier): string {
    if (m.multiplier_type === 'SCHEDULED') {
      const start = durationToMinutes(m.window_start_offset);
      const end = durationToMinutes(m.window_end_offset);
      if (start === null && end === null) return 'whole session';
      return `min ${start ?? 0} → ${end ?? 'open'} after start`;
    }
    const fmt = (iso: string | null) =>
      iso ? new Date(iso).toLocaleTimeString() : null;
    const start = fmt(m.starts_at);
    const end = fmt(m.ends_at);
    if (!start && !end) return 'open (gated by the toggle)';
    return `${start ?? 'now'} → ${end ?? 'open'}`;
  }

  protected typeBadgeClass(t: ScoreMultiplierType): string {
    if (t === 'SCHEDULED') return 'text-bg-secondary';
    if (t === 'RANDOM_BONUS') return 'text-bg-warning';
    return 'text-bg-primary';
  }

  protected toggleMultiplier(m: AdminScoreMultiplier): void {
    if (this.togglingId() !== null) return;
    this.togglingId.set(m.id);
    this.boostError.set(null);
    this.staff.setMultiplierActive(this.sessionId, m.id, !m.is_active).subscribe({
      next: () => {
        this.togglingId.set(null);
        this.refreshMultipliers();
      },
      error: (err) => {
        this.togglingId.set(null);
        this.boostError.set(extractErrorMessage(err));
      },
    });
  }

  protected dropBoost(): void {
    if (this.boostBusy() || !this.canDropBoost()) return;
    this.boostBusy.set(true);
    this.boostError.set(null);
    const scope = this.boostScope();
    const minutes = this.boostMinutes();
    this.staff
      .createSessionMultiplier(this.sessionId, {
        scope,
        multiplier_type: this.boostType(),
        factor: this.boostFactor() ?? 1,
        tower: scope === 'TOWER' ? this.boostTower() : null,
        zone: scope === 'ZONE' ? this.boostZone() : null,
        ends_at:
          minutes !== null && minutes > 0
            ? new Date(Date.now() + minutes * 60_000).toISOString()
            : null,
        label: this.boostLabel(),
      })
      .subscribe({
        next: () => {
          this.boostBusy.set(false);
          this.boostLabel.set('');
          this.boostMinutes.set(null);
          this.refreshMultipliers();
        },
        error: (err) => {
          this.boostBusy.set(false);
          this.boostError.set(extractErrorMessage(err));
        },
      });
  }

  private setSession(s: AdminSession): void {
    this.session.set(s);
    this.override.set(pickOverrides(s));
    this.teamFormationOverride.set(s.allow_player_team_creation);
    this.presenceOverride.set(pickPresenceOverrides(s));
    this.visibilityOverride.set(pickVisibilityOverrides(s));
    this.conquestOverride.set(s.zone_conquest_rule);
    this.timeUnitOverride.set(s.score_time_unit);
    this.extraOverrides.set(pickExtraOverrides(s));
    this.overrideDirty.set(false);
    this.refreshReadiness();
    if (this.game()?.id !== s.game) {
      this.staff.getGame(s.game).subscribe({
        next: (g) => this.game.set(g),
        error: () => this.game.set(null),
      });
    }
  }

  /** Session override when set, else the Game default (readout only). */
  protected effectiveConquestRule(): string {
    return this.conquestOverride() ?? this.game()?.zone_conquest_rule ?? 'MAJORITY';
  }

  protected effectiveTimeUnit(): string {
    return this.timeUnitOverride() ?? this.game()?.score_time_unit ?? 'MINUTE';
  }

  protected setConquestOverride(value: ConquestRule | null): void {
    this.conquestOverride.set(value);
    this.overrideDirty.set(true);
  }

  protected setTimeUnitOverride(value: ScoreTimeUnit | null): void {
    this.timeUnitOverride.set(value);
    this.overrideDirty.set(true);
  }

  // ---- Extended overrides (session-control-console) -------------------------

  protected setExtraOverride<K extends keyof ExtraOverrides>(field: K, value: ExtraOverrides[K]): void {
    this.extraOverrides.update((o) => ({ ...o, [field]: value }));
    this.overrideDirty.set(true);
  }

  protected setExtraOverrideNum(field: keyof ExtraOverrides, raw: string | number | null): void {
    const value = raw === '' || raw === null ? null : Number(raw);
    this.setExtraOverride(field, value as ExtraOverrides[typeof field]);
  }

  /** Template accessor for the generic #extraControl renderer — avoids
   * indexing the strongly-typed ExtraOverrides record with the `any`
   * field key that comes out of the ng-template context. */
  protected extraValue(field: ExtraOverrideKey): unknown {
    return (this.extraOverrides() as unknown as Record<string, unknown>)[field];
  }

  protected extraEffectiveLabel(f: ExtraOverrideDef): string {
    const override = (this.extraOverrides() as Record<string, unknown>)[f.field];
    const value = override ?? (this.game() as unknown as Record<string, unknown> | null)?.[f.field] ?? '—';
    if (typeof value === 'boolean') return value ? 'On' : 'Off';
    const opt = f.options?.find((o) => o.value === value);
    return opt ? opt.label : String(value);
  }

  private refreshReadiness(): void {
    this.staff.sessionStartBlockers(this.sessionId).subscribe({
      next: (r) => this.readiness.set(r),
      error: () => this.readiness.set(null),
    });
  }

  // ---- Lifecycle controls (session-lifecycle) -----------------------------



  protected actionLabel(action: SessionTransitionAction): string {
    return ACTION_LABELS[action] ?? action;
  }

  protected actionButtonClass(action: SessionTransitionAction): string {
    return ACTION_BUTTONS[action] ?? 'btn-outline-secondary';
  }

  protected async transition(action: SessionTransitionAction, override = false): Promise<void> {
    if (this.lifecycleBusy()) return;
    if (action === 'finish' && !override) {
      const ok = await this.confirmService.confirm({
        title: 'Finish this session?',
        message:
          'All open tower/zone ownerships will be closed and the session becomes ' +
          'terminal (history is kept). This cannot be undone.',
        confirmLabel: 'Finish session',
        danger: true,
      });
      if (!ok) return;
    }
    this.lifecycleBusy.set(true);
    this.lifecycleError.set(null);
    this.staff.transitionSession(this.sessionId, action, override).subscribe({
      next: (s) => {
        this.setSession(s);
        this.reloadState();
      },
      error: async (err) => {
        this.lifecycleBusy.set(false);
        // Out-of-window open_participation: offer the staff override.
        if (
          action === 'open_participation' &&
          !override &&
          err instanceof HttpErrorResponse &&
          err.status === 409 &&
          err.error?.requires_override
        ) {
          const ok = await this.confirmService.confirm({
            title: 'Open participation early?',
            message:
              'The participation window is outside the allowed range (7 days to 1 hour ' +
              'before the scheduled start). Open anyway?',
            confirmLabel: 'Open anyway',
          });
          if (ok) {
            this.transition(action, true);
            return;
          }
        }
        this.lifecycleError.set(extractErrorMessage(err));
      },
    });
  }

  /** DRAFT fast path: chain open_participation then start. */
  protected openAndStart(): void {
    if (this.lifecycleBusy()) return;
    this.lifecycleBusy.set(true);
    this.lifecycleError.set(null);
    this.staff.transitionSession(this.sessionId, 'open_participation').subscribe({
      next: () => {
        this.staff.transitionSession(this.sessionId, 'start').subscribe({
          next: (s) => {
            this.setSession(s);
            this.reloadState();
          },
          error: (err) => {
            this.lifecycleBusy.set(false);
            this.lifecycleError.set(extractErrorMessage(err));
            this.refreshSession();
          },
        });
      },
      error: (err) => {
        this.lifecycleBusy.set(false);
        this.lifecycleError.set(extractErrorMessage(err));
      },
    });
  }

  private refreshSession(): void {
    this.staff.getSession(this.sessionId).subscribe({
      next: (s) => this.setSession(s),
    });
  }

  private reloadState(): void {
    this.refreshMultipliers();
    forkJoin({
      scoreboard: this.api.sessionScoreboard(this.sessionId),
      timeline: this.api.sessionTimeline(this.sessionId),
      pauseHistory: this.staff.sessionPauseHistory(this.sessionId),
      failCounters: this.staff.sessionFailCounters(this.sessionId),
    }).subscribe({
      next: (r) => {
        this.scoreboard.set(r.scoreboard);
        this.timeline.set(r.timeline);
        this.pauseHistory.set(r.pauseHistory);
        this.failCounters.set(r.failCounters);
        this.lifecycleBusy.set(false);
      },
      error: (err) => {
        this.lifecycleBusy.set(false);
        this.lifecycleError.set(extractErrorMessage(err));
      },
    });
  }

  protected setOverride<K extends keyof Phase10Overrides>(
    field: K,
    value: Phase10Overrides[K],
  ): void {
    this.override.update((o) => ({ ...o, [field]: value }));
    this.overrideDirty.set(true);
  }

  protected setTeamFormationOverride(value: boolean | null): void {
    this.teamFormationOverride.set(value);
    this.overrideDirty.set(true);
  }

  protected setPresenceOverride<K extends keyof PresenceRulesOverrides>(
    field: K,
    value: PresenceRulesOverrides[K],
  ): void {
    // Empty number inputs come through as '' or null — both mean Inherit.
    const normalized = (value as unknown) === '' ? null : value;
    this.presenceOverride.update((o) => ({ ...o, [field]: normalized }));
    this.overrideDirty.set(true);
  }

  protected setVisibilityOverride<K extends keyof TowerVisibilityOverrides>(
    field: K,
    value: TowerVisibilityOverrides[K],
  ): void {
    const normalized = (value as unknown) === '' ? null : value;
    this.visibilityOverride.update((o) => ({ ...o, [field]: normalized }));
    this.overrideDirty.set(true);
  }

  protected shuffleTeams(): void {
    this.runBuild(this.staff.shuffleTeams(this.sessionId, this.buildCount() ?? 0));
  }

  protected balanceTeams(): void {
    const keys = this.buildKeys()
      .split(',')
      .map((k) => k.trim())
      .filter((k) => k.length > 0);
    this.runBuild(this.staff.balanceTeams(this.sessionId, this.buildCount() ?? 0, keys));
  }

  private runBuild(call: ReturnType<StaffApiService['shuffleTeams']>): void {
    this.buildBusy.set(true);
    this.buildError.set(null);
    this.buildResult.set(null);
    call.subscribe({
      next: (res) => {
        this.buildBusy.set(false);
        this.buildResult.set(res);
        this.reloadState();
      },
      error: (err) => {
        this.buildBusy.set(false);
        this.buildError.set(extractErrorMessage(err));
      },
    });
  }

  protected saveOverrides(id: number): void {
    if (!this.overrideDirty() || this.overrideSaving()) return;
    this.overrideSaving.set(true);
    this.overrideError.set(null);
    const payload: AdminSessionPayload = {
      ...this.override(),
      ...this.presenceOverride(),
      ...this.visibilityOverride(),
      ...this.extraOverrides(),
      allow_player_team_creation: this.teamFormationOverride(),
      zone_conquest_rule: this.conquestOverride(),
      score_time_unit: this.timeUnitOverride(),
    };
    this.staff.updateSession(id, payload).subscribe({
      next: (s) => {
        this.overrideSaving.set(false);
        this.setSession(s);
      },
      error: (err) => {
        this.overrideSaving.set(false);
        this.overrideError.set(extractErrorMessage(err));
      },
    });
  }

  // ---- Danger zone: destructive ops scoped to THIS session ------------------
  //
  // Backend note: `unassign_all` resolves its Game scope from the staff
  // user's implicit `profile.current_session` (game/admin_api.py), and
  // `reset-scores` (game/admin_api.py ResetScoresView) has NO session
  // scoping at all — it zeroes every Team's score and closes every open
  // ownership in the whole installation. Neither endpoint accepts a
  // session id. Both are Django/DRF views outside this change's file
  // ownership, so they can't be re-scoped here. What this console DOES
  // do, entirely on the frontend: (1) sync the implicit current-session to
  // THIS session right before firing, so the game-scoped sweep in
  // unassign_all resolves correctly instead of depending on whatever
  // session staff last picked in the nav switcher: and (2) say the real
  // blast radius plainly in the confirmation instead of implying either
  // action is limited to this session.

  protected async unassignAllForSession(): Promise<void> {
    if (this.dangerBusy() !== null) return;
    const s = this.session();
    if (!s) return;
    const ok = await this.confirmService.confirm({
      title: 'Unassign all towers?',
      message:
        `This closes every open tower ownership across every session of ` +
        `"${s.game_name}" (towers are shared repository geometry), including ` +
        `"${s.name}". Team scores are preserved. This cannot be undone.`,
      confirmLabel: 'Unassign all towers',
      danger: true,
    });
    if (!ok) return;
    this.dangerBusy.set('unassign');
    this.dangerError.set(null);
    this.dangerNotice.set(null);
    this.api.setCurrentSession(this.sessionId).subscribe({
      next: () => {
        this.staff.unassignAllTowers().subscribe({
          next: (res) => {
            this.dangerBusy.set(null);
            this.dangerNotice.set(`${res.unassigned.length} tower(s) unassigned.`);
            this.reloadState();
          },
          error: (err) => {
            this.dangerBusy.set(null);
            this.dangerError.set(extractErrorMessage(err));
          },
        });
      },
      error: (err) => {
        this.dangerBusy.set(null);
        this.dangerError.set(extractErrorMessage(err));
      },
    });
  }

  protected async resetScoresForSession(): Promise<void> {
    if (this.dangerBusy() !== null) return;
    const s = this.session();
    if (!s) return;
    const ok = await this.confirmService.confirm({
      title: 'Reset scores for this session?',
      message:
        `This zeroes every team's cumulative score and closes every open ` +
        `tower/zone ownership in "${s.name}". Other games and sessions are ` +
        `not affected. This cannot be undone.`,
      confirmLabel: 'Reset scores',
      danger: true,
      requireTyping: s.slug,
    });
    if (!ok) return;
    this.dangerBusy.set('reset');
    this.dangerError.set(null);
    this.dangerNotice.set(null);
    // Session-scoped server-side — no need to set the nav "current session".
    this.staff.resetScores(this.sessionId).subscribe({
      next: (res) => {
        this.dangerBusy.set(null);
        this.dangerNotice.set(`Scores reset for ${res.teams_reset} team(s).`);
        this.reloadState();
      },
      error: (err) => {
        this.dangerBusy.set(null);
        this.dangerError.set(extractErrorMessage(err));
      },
    });
  }
}



const ACTION_LABELS: Record<SessionTransitionAction, string> = {
  open_participation: 'Open participation',
  close_participation: 'Close participation',
  start: 'Start',
  pause: 'Pause',
  resume: 'Resume',
  finish: 'Finish',
};

const ACTION_BUTTONS: Record<SessionTransitionAction, string> = {
  open_participation: 'btn-outline-primary',
  close_participation: 'btn-outline-secondary',
  start: 'btn-success',
  pause: 'btn-warning',
  resume: 'btn-success',
  finish: 'btn-outline-danger',
};

function blankOverrides(): Phase10Overrides {
  return {
    pause_freezes_floating_score: null,
    pause_restores_ownerships_on_resume: null,
    pause_rejects_submissions: null,
    fail_point_penalty: null,
    fail_cooloff_scaling: null,
    fail_tower_lockout_minutes: null,
    fail_difficulty_rollback: null,
    fail_counter_reset: null,
  };
}

function pickOverrides(s: AdminSession): Phase10Overrides {
  const out = blankOverrides();
  for (const field of OVERRIDE_FIELDS) {
    (out[field] as Phase10Overrides[typeof field]) = s[field];
  }
  return out;
}

function blankPresenceOverrides(): PresenceRulesOverrides {
  return {
    togetherness_mode: null,
    teammate_visibility_mode: null,
    teammate_visibility_count: null,
    presence_window_seconds: null,
  };
}

function pickPresenceOverrides(s: AdminSession): PresenceRulesOverrides {
  return {
    togetherness_mode: s.togetherness_mode,
    teammate_visibility_mode: s.teammate_visibility_mode,
    teammate_visibility_count: s.teammate_visibility_count,
    presence_window_seconds: s.presence_window_seconds,
  };
}

function blankVisibilityOverrides(): TowerVisibilityOverrides {
  return {
    tower_discoverability_default: null,
    challenge_visibility_default: null,
    fog_reveal_coverage_pct_default: null,
    reveal_other_teams_ownership: null,
  };
}

function pickVisibilityOverrides(s: AdminSession): TowerVisibilityOverrides {
  return {
    tower_discoverability_default: s.tower_discoverability_default,
    challenge_visibility_default: s.challenge_visibility_default,
    fog_reveal_coverage_pct_default: s.fog_reveal_coverage_pct_default,
    reveal_other_teams_ownership: s.reveal_other_teams_ownership,
  };
}
