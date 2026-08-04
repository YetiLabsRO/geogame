import {
  ChangeDetectionStrategy,
  Component,
  ElementRef,
  afterNextRender,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import * as L from 'leaflet';

import {
  AdminCollection,
  AdminGame,
  AdminGamePayload,
  ChallengeVisibility,
  ConquestRule,
  DementorEmptyOutcome,
  Discoverability,
  FailCounterReset,
  GameMode,
  LocationVisibility,
  ProximityBucket,
  ScoreTimeUnit,
  StaffApiService,
  TeamJoinConfirmation,
  TeammateVisibilityMode,
  TogethernessMode,
  TowerLockMode,
  FieldRowComponent,
  InfoHintComponent,
  PageHeaderComponent,
} from 'shared';

import { extractErrorMessage } from '../../auth/form-error';
import { GameRolesPanelComponent } from '../game-roles-panel.component';
import { ScoreMultipliersPanelComponent } from '../score-multipliers-panel.component';

/** Fallback map center/zoom (matches player/src/app/map/map.component.ts). */
const FALLBACK_CENTER: [number, number] = [46.068374, 23.571797];
const FALLBACK_ZOOM = 15;
/** Mirrors --danger (light) from THEME.md; Leaflet's SVG renderer sets raw
 * path attributes, not `style`, so a CSS custom property can't be used here. */
const MARKER_STYLE: L.CircleMarkerOptions = {
  radius: 10,
  color: '#C0453B',
  weight: 2,
  fillColor: '#C0453B',
  fillOpacity: 0.55,
};

/** Flat, always-populated draft of every Game config field the wizard edits. */
export interface GameWizardDraft {
  name: string;
  slug: string;
  mode: GameMode;
  base_lat: number | null;
  base_lng: number | null;
  base_zoom_level: number;
  collections: number[];
  proximity_meters: number;
  cooloff_minutes: number;
  initial_bonus_default: number;
  zone_conquest_rule: ConquestRule;
  score_time_unit: ScoreTimeUnit;
  min_teams: number;
  max_teams: number;
  min_members_per_team: number;
  max_members_per_team: number;
  allow_player_team_creation: boolean;
  team_join_confirmation: TeamJoinConfirmation;
  tower_lock_mode: TowerLockMode;
  tower_lock_finish_minutes: number;
  tower_discoverability_default: Discoverability;
  challenge_visibility_default: ChallengeVisibility;
  fog_reveal_coverage_pct_default: number;
  reveal_other_teams_ownership: boolean;
  togetherness_mode: TogethernessMode;
  teammate_visibility_mode: TeammateVisibilityMode;
  teammate_visibility_count: number;
  presence_window_seconds: number;
  location_tracking_enabled: boolean;
  location_ping_interval_seconds: number;
  location_visibility: LocationVisibility;
  location_retention_days: number;
  location_consent_text: string;
  realtime_enabled: boolean;
  push_notifications_enabled: boolean;
  nfc_secure_mode: boolean;
  nfc_require_app: boolean;
  nfc_replay_hardening: boolean;
  require_ble_capable: boolean;
  ble_report_interval_seconds: number;
  ble_scan_duty_cycle_percent: number;
  ble_freshness_window_seconds: number;
  ble_identity_rotation_minutes: number;
  ble_rssi_very_close_dbm: number;
  ble_rssi_near_dbm: number;
  ble_rssi_hysteresis_db: number;
  dementors_enabled: boolean;
  dementor_initial_dementors: number;
  dementor_starting_energy: number;
  dementor_drain_per_second: number;
  dementor_drain_range_bucket: ProximityBucket;
  dementor_empty_outcome: DementorEmptyOutcome;
  dementor_safety_in_numbers: boolean;
  dementor_reverse_group_size: number;
  dementor_reverse_hold_seconds: number;
  dementor_conversion_threshold: number;
  dementor_restore_per_second: number;
  dementor_wizard_regen_per_second: number;
  dementor_tick_seconds: number;
  fail_point_penalty: number;
  fail_cooloff_scaling: number;
  fail_tower_lockout_minutes: number;
  fail_difficulty_rollback: boolean;
  fail_counter_reset: FailCounterReset;
  pause_freezes_floating_score: boolean;
  pause_restores_ownerships_on_resume: boolean;
  pause_rejects_submissions: boolean;
}

/** Matches the organize.models.Game field defaults exactly. */
function defaultDraft(): GameWizardDraft {
  return {
    name: '',
    slug: '',
    mode: 'DOMINATION',
    base_lat: null,
    base_lng: null,
    base_zoom_level: 15,
    collections: [],
    proximity_meters: 50,
    cooloff_minutes: 5,
    initial_bonus_default: 0,
    zone_conquest_rule: 'MAJORITY',
    score_time_unit: 'MINUTE',
    min_teams: 1,
    max_teams: 0,
    min_members_per_team: 1,
    max_members_per_team: 0,
    allow_player_team_creation: false,
    team_join_confirmation: 'AUTO_APPROVE',
    tower_lock_mode: 'FREE_FOR_ALL',
    tower_lock_finish_minutes: 15,
    tower_discoverability_default: 'VISIBLE',
    challenge_visibility_default: 'VISIBLE_ANYWHERE',
    fog_reveal_coverage_pct_default: 60,
    reveal_other_teams_ownership: true,
    togetherness_mode: 'SPLIT_ALLOWED',
    teammate_visibility_mode: 'OWN_TEAM',
    teammate_visibility_count: 0,
    presence_window_seconds: 0,
    location_tracking_enabled: false,
    location_ping_interval_seconds: 30,
    location_visibility: 'OWN_TEAM',
    location_retention_days: 30,
    location_consent_text: '',
    realtime_enabled: true,
    push_notifications_enabled: false,
    nfc_secure_mode: false,
    nfc_require_app: false,
    nfc_replay_hardening: false,
    require_ble_capable: false,
    ble_report_interval_seconds: 10,
    ble_scan_duty_cycle_percent: 100,
    ble_freshness_window_seconds: 30,
    ble_identity_rotation_minutes: 15,
    ble_rssi_very_close_dbm: -55,
    ble_rssi_near_dbm: -75,
    ble_rssi_hysteresis_db: 5,
    dementors_enabled: false,
    dementor_initial_dementors: 1,
    dementor_starting_energy: 100,
    dementor_drain_per_second: 1,
    dementor_drain_range_bucket: 'NEAR',
    dementor_empty_outcome: 'FLIP',
    dementor_safety_in_numbers: true,
    dementor_reverse_group_size: 3,
    dementor_reverse_hold_seconds: 30,
    dementor_conversion_threshold: 100,
    dementor_restore_per_second: 1,
    dementor_wizard_regen_per_second: 0,
    dementor_tick_seconds: 5,
    fail_point_penalty: 0,
    fail_cooloff_scaling: 1,
    fail_tower_lockout_minutes: 0,
    fail_difficulty_rollback: false,
    fail_counter_reset: 'TOWER_SUCCESS_ONLY',
    pause_freezes_floating_score: true,
    pause_restores_ownerships_on_resume: true,
    pause_rejects_submissions: true,
  };
}

function draftFromGame(g: AdminGame): GameWizardDraft {
  return {
    name: g.name,
    slug: g.slug,
    mode: g.mode,
    base_lat: g.base_point ? g.base_point.coordinates[1] : null,
    base_lng: g.base_point ? g.base_point.coordinates[0] : null,
    base_zoom_level: g.base_zoom_level,
    collections: [...g.collections],
    proximity_meters: g.proximity_meters,
    cooloff_minutes: g.cooloff_minutes,
    initial_bonus_default: g.initial_bonus_default,
    zone_conquest_rule: g.zone_conquest_rule,
    score_time_unit: g.score_time_unit,
    min_teams: g.min_teams,
    max_teams: g.max_teams,
    min_members_per_team: g.min_members_per_team,
    max_members_per_team: g.max_members_per_team,
    allow_player_team_creation: g.allow_player_team_creation,
    team_join_confirmation: g.team_join_confirmation,
    tower_lock_mode: g.tower_lock_mode,
    tower_lock_finish_minutes: g.tower_lock_finish_minutes,
    tower_discoverability_default: g.tower_discoverability_default,
    challenge_visibility_default: g.challenge_visibility_default,
    fog_reveal_coverage_pct_default: g.fog_reveal_coverage_pct_default,
    reveal_other_teams_ownership: g.reveal_other_teams_ownership,
    togetherness_mode: g.togetherness_mode,
    teammate_visibility_mode: g.teammate_visibility_mode,
    teammate_visibility_count: g.teammate_visibility_count,
    presence_window_seconds: g.presence_window_seconds,
    location_tracking_enabled: g.location_tracking_enabled,
    location_ping_interval_seconds: g.location_ping_interval_seconds,
    location_visibility: g.location_visibility,
    location_retention_days: g.location_retention_days,
    location_consent_text: g.location_consent_text,
    realtime_enabled: g.realtime_enabled,
    push_notifications_enabled: g.push_notifications_enabled,
    nfc_secure_mode: g.nfc_secure_mode,
    nfc_require_app: g.nfc_require_app,
    nfc_replay_hardening: g.nfc_replay_hardening,
    require_ble_capable: g.require_ble_capable,
    ble_report_interval_seconds: g.ble_report_interval_seconds,
    ble_scan_duty_cycle_percent: g.ble_scan_duty_cycle_percent,
    ble_freshness_window_seconds: g.ble_freshness_window_seconds,
    ble_identity_rotation_minutes: g.ble_identity_rotation_minutes,
    ble_rssi_very_close_dbm: g.ble_rssi_very_close_dbm,
    ble_rssi_near_dbm: g.ble_rssi_near_dbm,
    ble_rssi_hysteresis_db: g.ble_rssi_hysteresis_db,
    dementors_enabled: g.dementors_enabled,
    dementor_initial_dementors: g.dementor_initial_dementors,
    dementor_starting_energy: g.dementor_starting_energy,
    dementor_drain_per_second: g.dementor_drain_per_second,
    dementor_drain_range_bucket: g.dementor_drain_range_bucket,
    dementor_empty_outcome: g.dementor_empty_outcome,
    dementor_safety_in_numbers: g.dementor_safety_in_numbers,
    dementor_reverse_group_size: g.dementor_reverse_group_size,
    dementor_reverse_hold_seconds: g.dementor_reverse_hold_seconds,
    dementor_conversion_threshold: g.dementor_conversion_threshold,
    dementor_restore_per_second: g.dementor_restore_per_second,
    dementor_wizard_regen_per_second: g.dementor_wizard_regen_per_second,
    dementor_tick_seconds: g.dementor_tick_seconds,
    fail_point_penalty: g.fail_point_penalty,
    fail_cooloff_scaling: g.fail_cooloff_scaling,
    fail_tower_lockout_minutes: g.fail_tower_lockout_minutes,
    fail_difficulty_rollback: g.fail_difficulty_rollback,
    fail_counter_reset: g.fail_counter_reset,
    pause_freezes_floating_score: g.pause_freezes_floating_score,
    pause_restores_ownerships_on_resume: g.pause_restores_ownerships_on_resume,
    pause_rejects_submissions: g.pause_rejects_submissions,
  };
}

function slugify(value: string): string {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 64);
}

const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/;

interface StepDef {
  label: string;
  icon: string;
}

const STEPS: StepDef[] = [
  { label: 'Basics', icon: 'bi-info-circle' },
  { label: 'Core rules', icon: 'bi-sliders' },
  { label: 'Teams', icon: 'bi-people' },
  { label: 'Modes & mechanics', icon: 'bi-gear' },
  { label: 'Dementors', icon: 'bi-lightning-charge' },
  { label: 'Failure & pausing', icon: 'bi-pause-circle' },
  { label: 'Review & create', icon: 'bi-check2-circle' },
];

@Component({
  selector: 'app-game-wizard',
  standalone: true,
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [
    FormsModule,
    RouterLink,
    FieldRowComponent,
    InfoHintComponent,
    PageHeaderComponent,
    GameRolesPanelComponent,
    ScoreMultipliersPanelComponent,
  ],
  template: `
    <app-page-header
      [title]="gameId() ? 'Edit game' : 'New game'"
      [subtitle]="
        gameId()
          ? draft().name || 'Untitled game'
          : 'Reusable event configuration — map, rules, and the challenge bank.'
      "
    >
      <a actions routerLink="/games" class="btn btn-sm btn-outline-secondary">
        <i class="bi bi-x-lg"></i> Cancel
      </a>
    </app-page-header>

    @if (loadError(); as msg) {
      <div class="alert alert-danger">{{ msg }}</div>
    }

    @if (loading()) {
      <div class="d-flex align-items-center text-body-secondary">
        <span class="spinner-border spinner-border-sm me-2"></span>
        Loading game…
      </div>
    } @else {
      <!-- Step indicator ---------------------------------------------------- -->
      <ul class="gw-steps nav nav-pills mb-4" role="tablist">
        @for (s of steps; track s.label; let i = $index) {
          <li class="nav-item">
            <button
              type="button"
              class="nav-link gw-step-btn"
              [class.active]="currentStep() === i"
              [class.gw-step-btn--invalid]="!stepValid()[i] && i !== steps.length - 1"
              (click)="goToStep(i)"
            >
              <span class="gw-step-num">{{ i + 1 }}</span>
              <i class="bi {{ s.icon }} d-none d-sm-inline"></i>
              <span>{{ s.label }}</span>
              @if (!stepValid()[i] && i !== steps.length - 1) {
                <i class="bi bi-exclamation-circle-fill text-danger ms-1" title="Needs attention"></i>
              }
            </button>
          </li>
        }
      </ul>

      <!-- Step 0: Basics ------------------------------------------------------ -->
      <div [hidden]="currentStep() !== 0">
        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Identity</h2>
            <app-field-row label="Name" [required]="true" [error]="nameError() ?? undefined" for="gw-name">
              <input
                id="gw-name"
                class="form-control"
                type="text"
                [ngModel]="draft().name"
                (ngModelChange)="onNameChange($event)"
              />
            </app-field-row>
            <app-field-row
              label="Slug"
              [required]="true"
              [error]="slugError() ?? undefined"
              hint="URL-safe unique identifier, e.g. 'summer-camp-2026'. Auto-suggested from the name until you edit it directly."
              for="gw-slug"
            >
              <input
                id="gw-slug"
                class="form-control font-monospace"
                type="text"
                [ngModel]="draft().slug"
                (ngModelChange)="onSlugChange($event)"
              />
            </app-field-row>
            <app-field-row
              label="Mode"
              for="gw-mode"
              hint="Domination is the classic capture-and-hold loop: teams contest towers and hold zones for points. Trail is a clue-driven point-to-point run instead of zone/floating-point scoring. Each Session may override this."
            >
              <select
                id="gw-mode"
                class="form-select"
                [ngModel]="draft().mode"
                (ngModelChange)="patch('mode', $event)"
              >
                @for (o of modeOptions; track o.value) {
                  <option [ngValue]="o.value">{{ o.label }}</option>
                }
              </select>
            </app-field-row>
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-1">
              Base map location
              <app-info-hint text="Where the player map centers by default, and the reference point for base_zoom_level. Click the map (or type coordinates) to place it." />
            </h2>
            <p class="text-body-secondary small mb-2">
              Click anywhere on the map to drop the pin, or type coordinates directly.
            </p>
            <div #mapContainer class="gw-map mb-3"></div>
            <div class="row g-2">
              <div class="col-6 col-md-3">
                <app-field-row label="Latitude" for="gw-lat">
                  <input
                    id="gw-lat"
                    class="form-control"
                    type="number"
                    step="any"
                    placeholder="—"
                    [ngModel]="draft().base_lat"
                    (ngModelChange)="onLatChange($event)"
                  />
                </app-field-row>
              </div>
              <div class="col-6 col-md-3">
                <app-field-row label="Longitude" for="gw-lng">
                  <input
                    id="gw-lng"
                    class="form-control"
                    type="number"
                    step="any"
                    placeholder="—"
                    [ngModel]="draft().base_lng"
                    (ngModelChange)="onLngChange($event)"
                  />
                </app-field-row>
              </div>
              <div class="col-6 col-md-3">
                <app-field-row
                  label="Base zoom"
                  hint="Initial Leaflet zoom level (1–19) the player map opens at, centered on the point above."
                  for="gw-zoom"
                >
                  <input
                    id="gw-zoom"
                    class="form-control"
                    type="number"
                    min="1"
                    max="19"
                    [ngModel]="draft().base_zoom_level"
                    (ngModelChange)="patch('base_zoom_level', numOr($event, 15))"
                  />
                </app-field-row>
              </div>
            </div>
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-1">
              Map collections
              <app-info-hint text="A Game's playable geometry (towers/zones) comes from one or more repository Collections. Check every Collection this game should draw its map from." />
            </h2>
            @if (allCollections().length === 0) {
              <p class="text-body-secondary small mb-0">
                No collections in the repository yet — create one on the
                <a routerLink="/collections">Collections</a> page.
              </p>
            } @else {
              <div class="d-flex flex-wrap gap-3">
                @for (c of allCollections(); track c.id) {
                  <div class="form-check gw-toggle-row">
                    <input
                      type="checkbox"
                      class="form-check-input"
                      [id]="'gw-col-' + c.id"
                      [checked]="draft().collections.includes(c.id)"
                      (change)="toggleCollection(c.id)"
                    />
                    <label class="form-check-label" [for]="'gw-col-' + c.id">{{ c.name }}</label>
                  </div>
                }
              </div>
            }
          </div>
        </div>
      </div>

      <!-- Step 1: Core rules --------------------------------------------------- -->
      <div [hidden]="currentStep() !== 1">
        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Capture &amp; scoring</h2>
            <div class="row g-3">
              <div class="col-md-4">
                <app-field-row
                  label="Proximity (m)"
                  hint="How close a player must be to a tower to submit its challenge."
                  for="gw-prox"
                >
                  <input
                    id="gw-prox"
                    class="form-control"
                    type="number"
                    min="1"
                    [ngModel]="draft().proximity_meters"
                    (ngModelChange)="patch('proximity_meters', numOr($event, 1))"
                  />
                </app-field-row>
              </div>
              <div class="col-md-4">
                <app-field-row
                  label="Cooloff (min)"
                  hint="Minutes a team must wait before re-attempting the same tower after a rejected submission."
                  for="gw-cooloff"
                >
                  <input
                    id="gw-cooloff"
                    class="form-control"
                    type="number"
                    min="0"
                    [ngModel]="draft().cooloff_minutes"
                    (ngModelChange)="patch('cooloff_minutes', numOr($event, 0))"
                  />
                </app-field-row>
              </div>
              <div class="col-md-4">
                <app-field-row
                  label="Initial bonus"
                  hint="Default bonus points for the first team to capture a tower, when the tower has no bonus override of its own."
                  for="gw-bonus"
                >
                  <input
                    id="gw-bonus"
                    class="form-control"
                    type="number"
                    min="0"
                    [ngModel]="draft().initial_bonus_default"
                    (ngModelChange)="patch('initial_bonus_default', numOr($event, 0))"
                  />
                </app-field-row>
              </div>
              <div class="col-md-6">
                <app-field-row
                  label="Zone conquest rule"
                  hint="How a team comes to control a zone. Majority (default) needs most towers; All needs every active tower; Any awards the zone to whoever holds the most towers, ties broken by the latest capture. Individual zones may override this."
                  for="gw-conquest"
                >
                  <select
                    id="gw-conquest"
                    class="form-select"
                    [ngModel]="draft().zone_conquest_rule"
                    (ngModelChange)="patch('zone_conquest_rule', $event)"
                  >
                    @for (o of conquestRuleOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </app-field-row>
              </div>
              <div class="col-md-6">
                <app-field-row
                  label="Score time unit"
                  hint="Zone scores accrue per this unit of time held. Minutes reproduces the historical formulas."
                  for="gw-timeunit"
                >
                  <select
                    id="gw-timeunit"
                    class="form-select"
                    [ngModel]="draft().score_time_unit"
                    (ngModelChange)="patch('score_time_unit', $event)"
                  >
                    @for (o of timeUnitOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </app-field-row>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Step 2: Teams ---------------------------------------------------------- -->
      <div [hidden]="currentStep() !== 2">
        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Team composition</h2>
            <div class="row g-3">
              @for (f of teamRuleFields; track f.field) {
                <div class="col-6 col-md-3">
                  <app-field-row [label]="f.label" [hint]="f.hint" [for]="'gw-' + f.field">
                    <input
                      [id]="'gw-' + f.field"
                      class="form-control"
                      type="number"
                      [min]="f.min"
                      [ngModel]="draft()[f.field]"
                      (ngModelChange)="patch(f.field, numOr($event, f.min))"
                    />
                  </app-field-row>
                </div>
              }
            </div>
            @if (teamsError(); as msg) {
              <div class="alert alert-warning py-2 mb-0">{{ msg }}</div>
            }
            <p class="text-body-secondary small mb-0 mt-2">
              A Session may only start once enough ready teams meet the member minimum. Only
              teams meeting the member minimum count toward the team minimum.
            </p>
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Team formation</h2>
            <div class="form-check form-switch gw-toggle-row mb-2">
              <input
                type="checkbox"
                class="form-check-input"
                role="switch"
                id="gw-ptc"
                [ngModel]="draft().allow_player_team_creation"
                (ngModelChange)="patch('allow_player_team_creation', $event)"
              />
              <label class="form-check-label" for="gw-ptc">
                Players may create their own teams
                <app-info-hint text="Off (default) keeps rosters staff-built. On lets players spin up their own teams from the app. Overridable per Session." />
              </label>
            </div>
            <app-field-row
              label="Join confirmation"
              hint="Default policy for a player joining an existing team. Each Team can override it individually."
              for="gw-joinconf"
            >
              <select
                id="gw-joinconf"
                class="form-select"
                [ngModel]="draft().team_join_confirmation"
                (ngModelChange)="patch('team_join_confirmation', $event)"
              >
                @for (o of confirmationOptions; track o.value) {
                  <option [ngValue]="o.value">{{ o.label }}</option>
                }
              </select>
            </app-field-row>
          </div>
        </div>
      </div>

      <!-- Step 3: Modes & mechanics ------------------------------------------------ -->
      <div [hidden]="currentStep() !== 3">
        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Tower locking</h2>
            <app-field-row
              label="Lock mode"
              hint="Free for all (default) reproduces today's race-to-finish contention exactly. Lock on initiate grants the initiating team an exclusive finish window per TeamGroup."
              for="gw-lockmode"
            >
              <select
                id="gw-lockmode"
                class="form-select"
                [ngModel]="draft().tower_lock_mode"
                (ngModelChange)="patch('tower_lock_mode', $event)"
              >
                @for (o of towerLockModeOptions; track o.value) {
                  <option [ngValue]="o.value">{{ o.label }}</option>
                }
              </select>
            </app-field-row>
            @if (draft().tower_lock_mode === 'LOCK_ON_INITIATE') {
              <app-field-row
                label="Finish window (min)"
                hint="How long the initiating team's exclusive lock lasts before it expires."
                for="gw-lockmin"
              >
                <input
                  id="gw-lockmin"
                  class="form-control"
                  type="number"
                  min="1"
                  [ngModel]="draft().tower_lock_finish_minutes"
                  (ngModelChange)="patch('tower_lock_finish_minutes', numOr($event, 1))"
                />
              </app-field-row>
            }
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">
              Tower visibility
              <app-info-hint text="Game-wide defaults for two independent axes: whether a tower appears on the map, and whether its challenge is legible before arrival. Individual towers/zones may override either." />
            </h2>
            <div class="row g-3">
              <div class="col-md-6">
                <app-field-row label="Discoverability default" for="gw-discover">
                  <select
                    id="gw-discover"
                    class="form-select"
                    [ngModel]="draft().tower_discoverability_default"
                    (ngModelChange)="patch('tower_discoverability_default', $event)"
                  >
                    @for (o of discoverabilityOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </app-field-row>
              </div>
              <div class="col-md-6">
                <app-field-row label="Challenge visibility default" for="gw-chalvis">
                  <select
                    id="gw-chalvis"
                    class="form-select"
                    [ngModel]="draft().challenge_visibility_default"
                    (ngModelChange)="patch('challenge_visibility_default', $event)"
                  >
                    @for (o of challengeVisibilityOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </app-field-row>
              </div>
              <div class="col-md-6">
                <app-field-row
                  label="Fog reveal coverage (%)"
                  hint="For Fog reveal towers: the % of a zone a team must cover before the zone's towers reveal."
                  for="gw-fog"
                >
                  <input
                    id="gw-fog"
                    class="form-control"
                    type="number"
                    min="0"
                    max="100"
                    [ngModel]="draft().fog_reveal_coverage_pct_default"
                    (ngModelChange)="patch('fog_reveal_coverage_pct_default', numOr($event, 0))"
                  />
                </app-field-row>
              </div>
              <div class="col-md-6 d-flex align-items-end">
                <div class="form-check form-switch gw-toggle-row mb-2">
                  <input
                    type="checkbox"
                    class="form-check-input"
                    role="switch"
                    id="gw-roto"
                    [ngModel]="draft().reveal_other_teams_ownership"
                    (ngModelChange)="patch('reveal_other_teams_ownership', $event)"
                  />
                  <label class="form-check-label" for="gw-roto">
                    Reveal other teams' ownership on the map
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">
              Presence rules
              <app-info-hint text="Whether a team must stay physically together and which other players show on a player's live map." />
            </h2>
            <div class="row g-3">
              <div class="col-md-6">
                <app-field-row label="Togetherness" for="gw-together">
                  <select
                    id="gw-together"
                    class="form-select"
                    [ngModel]="draft().togetherness_mode"
                    (ngModelChange)="patch('togetherness_mode', $event)"
                  >
                    @for (o of togethernessOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </app-field-row>
              </div>
              <div class="col-md-6">
                <app-field-row label="Teammate map visibility" for="gw-teamvis">
                  <select
                    id="gw-teamvis"
                    class="form-select"
                    [ngModel]="draft().teammate_visibility_mode"
                    (ngModelChange)="patch('teammate_visibility_mode', $event)"
                  >
                    @for (o of teammateVisibilityOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </app-field-row>
              </div>
              @if (draft().teammate_visibility_mode === 'SELECT_COUNT') {
                <div class="col-md-6">
                  <app-field-row label="Nearest N players" for="gw-nearestn">
                    <input
                      id="gw-nearestn"
                      class="form-control"
                      type="number"
                      min="0"
                      [ngModel]="draft().teammate_visibility_count"
                      (ngModelChange)="patch('teammate_visibility_count', numOr($event, 0))"
                    />
                  </app-field-row>
                </div>
              }
              <div class="col-md-6">
                <app-field-row
                  label="Presence window (s)"
                  hint="0 = a point-in-time check. Above 0, each counted member's live track must stay inside the geofence for that long — harder to spoof than one GPS fix."
                  for="gw-window"
                >
                  <input
                    id="gw-window"
                    class="form-control"
                    type="number"
                    min="0"
                    [ngModel]="draft().presence_window_seconds"
                    (ngModelChange)="patch('presence_window_seconds', numOr($event, 0))"
                  />
                </app-field-row>
              </div>
            </div>
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Live location</h2>
            <div class="form-check form-switch gw-toggle-row mb-2">
              <input
                type="checkbox"
                class="form-check-input"
                role="switch"
                id="gw-loctrack"
                [ngModel]="draft().location_tracking_enabled"
                (ngModelChange)="patch('location_tracking_enabled', $event)"
              />
              <label class="form-check-label" for="gw-loctrack">
                Track player locations
                <app-info-hint text="Off by default so existing games are unchanged. Required for live-map dots, presence checks, and the live-location overlay." />
              </label>
            </div>
            @if (draft().location_tracking_enabled) {
              <div class="row g-3">
                <div class="col-md-4">
                  <app-field-row
                    label="Ping interval (s)"
                    hint="Battery/power tradeoff — how often a phone reports its position. No player-facing control."
                    for="gw-pingint"
                  >
                    <input
                      id="gw-pingint"
                      class="form-control"
                      type="number"
                      min="5"
                      [ngModel]="draft().location_ping_interval_seconds"
                      (ngModelChange)="patch('location_ping_interval_seconds', numOr($event, 5))"
                    />
                  </app-field-row>
                </div>
                <div class="col-md-4">
                  <app-field-row label="Visibility" for="gw-locvis">
                    <select
                      id="gw-locvis"
                      class="form-select"
                      [ngModel]="draft().location_visibility"
                      (ngModelChange)="patch('location_visibility', $event)"
                    >
                      @for (o of locationVisibilityOptions; track o.value) {
                        <option [ngValue]="o.value">{{ o.label }}</option>
                      }
                    </select>
                  </app-field-row>
                </div>
                <div class="col-md-4">
                  <app-field-row
                    label="Retention (days)"
                    hint="How long raw location pings are kept before being purged."
                    for="gw-locret"
                  >
                    <input
                      id="gw-locret"
                      class="form-control"
                      type="number"
                      min="1"
                      [ngModel]="draft().location_retention_days"
                      (ngModelChange)="patch('location_retention_days', numOr($event, 1))"
                    />
                  </app-field-row>
                </div>
                <div class="col-12">
                  <app-field-row
                    label="Consent text"
                    hint="Shown to players before tracking starts, explaining what is collected and why."
                    for="gw-locconsent"
                  >
                    <textarea
                      id="gw-locconsent"
                      class="form-control"
                      rows="2"
                      [ngModel]="draft().location_consent_text"
                      (ngModelChange)="patch('location_consent_text', $event)"
                    ></textarea>
                  </app-field-row>
                </div>
              </div>
            }
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Realtime &amp; push</h2>
            @for (f of realtimeFields; track f.field) {
              <div class="form-check form-switch gw-toggle-row mb-2">
                <input
                  type="checkbox"
                  class="form-check-input"
                  role="switch"
                  [id]="'gw-' + f.field"
                  [ngModel]="draft()[f.field]"
                  (ngModelChange)="patch(f.field, $event)"
                />
                <label class="form-check-label" [for]="'gw-' + f.field">
                  {{ f.label }}
                  <app-info-hint [text]="f.hint" />
                </label>
              </div>
            }
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">NFC capture mode</h2>
            @for (f of nfcFields; track f.field) {
              <div class="form-check form-switch gw-toggle-row mb-2">
                <input
                  type="checkbox"
                  class="form-check-input"
                  role="switch"
                  [id]="'gw-' + f.field"
                  [ngModel]="draft()[f.field]"
                  (ngModelChange)="patch(f.field, $event)"
                />
                <label class="form-check-label" [for]="'gw-' + f.field">
                  {{ f.label }}
                  <app-info-hint [text]="f.hint" />
                </label>
              </div>
            }
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">BLE proximity</h2>
            <div class="form-check form-switch gw-toggle-row mb-2">
              <input
                type="checkbox"
                class="form-check-input"
                role="switch"
                id="gw-blereq"
                [ngModel]="draft().require_ble_capable"
                (ngModelChange)="patch('require_ble_capable', $event)"
              />
              <label class="form-check-label" for="gw-blereq">
                Require a BLE-capable device
                <app-info-hint text="Only devices with working Bluetooth may participate in BLE-gated proximity challenges. The server never exposes raw metres — only coarse buckets." />
              </label>
            </div>
            @if (draft().require_ble_capable) {
              <div class="row g-3">
                @for (f of bleNumFields; track f.field) {
                  <div class="col-6 col-md-4">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'gw-' + f.field">
                      <input
                        [id]="'gw-' + f.field"
                        class="form-control"
                        type="number"
                        [ngModel]="draft()[f.field]"
                        (ngModelChange)="patch(f.field, numOr($event, 0))"
                      />
                    </app-field-row>
                  </div>
                }
              </div>
            }
          </div>
        </div>
      </div>

      <!-- Step 4: Dementors ------------------------------------------------------- -->
      <div [hidden]="currentStep() !== 4">
        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-1">Dementors mini-mode</h2>
            <p class="text-body-secondary small">
              This is the only place to enable Dementors for this game. Wizards carry energy that
              nearby dementors drain over BLE proximity; a drained wizard flips (or drops out).
              Everything below only takes effect once this is on.
            </p>
            <div class="form-check form-switch gw-toggle-row mb-3">
              <input
                type="checkbox"
                class="form-check-input"
                role="switch"
                id="gw-dementors"
                [ngModel]="draft().dementors_enabled"
                (ngModelChange)="patch('dementors_enabled', $event)"
              />
              <label class="form-check-label fw-semibold" for="gw-dementors">
                Enable Dementors for this game
              </label>
            </div>

            @if (draft().dementors_enabled) {
              <h3 class="h6 text-body-secondary mt-4">Population &amp; energy</h3>
              <div class="row g-3">
                @for (f of dementorNumFields; track f.field) {
                  <div class="col-6 col-md-4">
                    <app-field-row [label]="f.label" [hint]="f.hint" [for]="'gw-' + f.field">
                      <input
                        [id]="'gw-' + f.field"
                        class="form-control"
                        type="number"
                        [step]="f.step ?? 1"
                        [ngModel]="draft()[f.field]"
                        (ngModelChange)="patch(f.field, numOr($event, 0))"
                      />
                    </app-field-row>
                  </div>
                }
                <div class="col-6 col-md-4">
                  <app-field-row
                    label="Drain range"
                    hint="How close (BLE proximity bucket) a dementor must be to drain a wizard."
                    for="gw-drainrange"
                  >
                    <select
                      id="gw-drainrange"
                      class="form-select"
                      [ngModel]="draft().dementor_drain_range_bucket"
                      (ngModelChange)="patch('dementor_drain_range_bucket', $event)"
                    >
                      @for (o of proximityBucketOptions; track o.value) {
                        <option [ngValue]="o.value">{{ o.label }}</option>
                      }
                    </select>
                  </app-field-row>
                </div>
              </div>

              <h3 class="h6 text-body-secondary mt-3">Outcomes</h3>
              <div class="row g-3">
                <div class="col-md-4">
                  <app-field-row
                    label="On empty"
                    hint="What happens to a wizard whose energy reaches zero."
                    for="gw-emptyout"
                  >
                    <select
                      id="gw-emptyout"
                      class="form-select"
                      [ngModel]="draft().dementor_empty_outcome"
                      (ngModelChange)="patch('dementor_empty_outcome', $event)"
                    >
                      @for (o of dementorEmptyOptions; track o.value) {
                        <option [ngValue]="o.value">{{ o.label }}</option>
                      }
                    </select>
                  </app-field-row>
                </div>
                <div class="col-md-4">
                  <app-field-row
                    label="Conversion threshold"
                    hint="Energy a dementor needs to accumulate to convert/spawn."
                    for="gw-convthresh"
                  >
                    <input
                      id="gw-convthresh"
                      class="form-control"
                      type="number"
                      step="0.1"
                      [ngModel]="draft().dementor_conversion_threshold"
                      (ngModelChange)="patch('dementor_conversion_threshold', numOr($event, 0))"
                    />
                  </app-field-row>
                </div>
              </div>

              <h3 class="h6 text-body-secondary mt-3">Group defense</h3>
              <div class="form-check form-switch gw-toggle-row mb-2">
                <input
                  type="checkbox"
                  class="form-check-input"
                  role="switch"
                  id="gw-safety"
                  [ngModel]="draft().dementor_safety_in_numbers"
                  (ngModelChange)="patch('dementor_safety_in_numbers', $event)"
                />
                <label class="form-check-label" for="gw-safety">
                  Safety in numbers
                  <app-info-hint text="A group of wizards together drains slower / resists better than a lone wizard." />
                </label>
              </div>
              <div class="row g-3">
                <div class="col-md-4">
                  <app-field-row
                    label="Reverse group size"
                    hint="Wizards needed together to reverse (banish) a dementor."
                    for="gw-revgroup"
                  >
                    <input
                      id="gw-revgroup"
                      class="form-control"
                      type="number"
                      min="1"
                      [ngModel]="draft().dementor_reverse_group_size"
                      (ngModelChange)="patch('dementor_reverse_group_size', numOr($event, 1))"
                    />
                  </app-field-row>
                </div>
                <div class="col-md-4">
                  <app-field-row
                    label="Reverse hold (s)"
                    hint="Seconds the group must hold position together to complete a reversal."
                    for="gw-revhold"
                  >
                    <input
                      id="gw-revhold"
                      class="form-control"
                      type="number"
                      min="0"
                      [ngModel]="draft().dementor_reverse_hold_seconds"
                      (ngModelChange)="patch('dementor_reverse_hold_seconds', numOr($event, 0))"
                    />
                  </app-field-row>
                </div>
              </div>
            }
          </div>
        </div>
      </div>

      <!-- Step 5: Failure & pausing ------------------------------------------------- -->
      <div [hidden]="currentStep() !== 5">
        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Failure consequences</h2>
            <p class="text-body-secondary small">
              All default to "off" so a rejected submission simply behaves like a plain cooloff.
            </p>
            <div class="row g-3">
              <div class="col-md-4">
                <app-field-row label="Point penalty" hint="Points deducted on a rejected submission." for="gw-failpen">
                  <input
                    id="gw-failpen"
                    class="form-control"
                    type="number"
                    min="0"
                    [ngModel]="draft().fail_point_penalty"
                    (ngModelChange)="patch('fail_point_penalty', numOr($event, 0))"
                  />
                </app-field-row>
              </div>
              <div class="col-md-4">
                <app-field-row
                  label="Cooloff scaling (≥1)"
                  hint="Multiplies the cooloff duration after each consecutive failure."
                  for="gw-failscale"
                >
                  <input
                    id="gw-failscale"
                    class="form-control"
                    type="number"
                    min="1"
                    step="0.1"
                    [ngModel]="draft().fail_cooloff_scaling"
                    (ngModelChange)="patch('fail_cooloff_scaling', numOr($event, 1))"
                  />
                </app-field-row>
              </div>
              <div class="col-md-4">
                <app-field-row
                  label="Tower lockout (min)"
                  hint="0 disables lockout. Above 0, the tower becomes untouchable by the team for this many minutes."
                  for="gw-faillock"
                >
                  <input
                    id="gw-faillock"
                    class="form-control"
                    type="number"
                    min="0"
                    [ngModel]="draft().fail_tower_lockout_minutes"
                    (ngModelChange)="patch('fail_tower_lockout_minutes', numOr($event, 0))"
                  />
                </app-field-row>
              </div>
              <div class="col-md-6 d-flex align-items-end">
                <div class="form-check form-switch gw-toggle-row mb-2">
                  <input
                    type="checkbox"
                    class="form-check-input"
                    role="switch"
                    id="gw-failrollback"
                    [ngModel]="draft().fail_difficulty_rollback"
                    (ngModelChange)="patch('fail_difficulty_rollback', $event)"
                  />
                  <label class="form-check-label" for="gw-failrollback">
                    Difficulty rollback after failure
                  </label>
                </div>
              </div>
              <div class="col-md-6">
                <app-field-row
                  label="Consecutive-fail counter reset"
                  hint="What clears a team's streak of consecutive failures at a tower."
                  for="gw-failreset"
                >
                  <select
                    id="gw-failreset"
                    class="form-select"
                    [ngModel]="draft().fail_counter_reset"
                    (ngModelChange)="patch('fail_counter_reset', $event)"
                  >
                    @for (o of resetOptions; track o.value) {
                      <option [ngValue]="o.value">{{ o.label }}</option>
                    }
                  </select>
                </app-field-row>
              </div>
            </div>
          </div>
        </div>

        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Day pausing</h2>
            @for (k of pauseFields; track k.field) {
              <div class="form-check form-switch gw-toggle-row mb-2">
                <input
                  type="checkbox"
                  class="form-check-input"
                  role="switch"
                  [id]="'gw-' + k.field"
                  [ngModel]="draft()[k.field]"
                  (ngModelChange)="patch(k.field, $event)"
                />
                <label class="form-check-label" [for]="'gw-' + k.field">
                  {{ k.label }}
                  <app-info-hint [text]="k.hint" />
                </label>
              </div>
            }
          </div>
        </div>
      </div>

      <!-- Step 6: Review & create --------------------------------------------------- -->
      <div [hidden]="currentStep() !== 6">
        <div class="card mb-3">
          <div class="card-body">
            <h2 class="h6 mb-3">Review</h2>
            @if (!canSubmit()) {
              <div class="alert alert-warning">
                Fix the highlighted steps before {{ gameId() ? 'saving' : 'creating' }} this game:
                <ul class="mb-0 mt-1">
                  @for (s of steps; track s.label; let i = $index) {
                    @if (!stepValid()[i] && i !== steps.length - 1) {
                      <li>
                        <button type="button" class="btn btn-link btn-sm p-0 align-baseline" (click)="goToStep(i)">
                          {{ s.label }}
                        </button>
                      </li>
                    }
                  }
                </ul>
              </div>
            }
            <dl class="row small mb-0">
              <dt class="col-sm-3">Name</dt>
              <dd class="col-sm-9">{{ draft().name || '—' }}</dd>
              <dt class="col-sm-3">Slug</dt>
              <dd class="col-sm-9"><code>{{ draft().slug || '—' }}</code></dd>
              <dt class="col-sm-3">Mode</dt>
              <dd class="col-sm-9">{{ modeLabel(draft().mode) }}</dd>
              <dt class="col-sm-3">Base point</dt>
              <dd class="col-sm-9">
                @if (draft().base_lat !== null && draft().base_lng !== null) {
                  {{ draft().base_lat }}, {{ draft().base_lng }} (zoom {{ draft().base_zoom_level }})
                } @else {
                  <span class="text-body-secondary">not set</span>
                }
              </dd>
              <dt class="col-sm-3">Collections</dt>
              <dd class="col-sm-9">{{ draft().collections.length }} linked</dd>
              <dt class="col-sm-3">Teams</dt>
              <dd class="col-sm-9">
                {{ draft().min_teams }}–{{ draft().max_teams || '∞' }} teams,
                {{ draft().min_members_per_team }}–{{ draft().max_members_per_team || '∞' }}
                members each
              </dd>
              <dt class="col-sm-3">Dementors</dt>
              <dd class="col-sm-9">{{ draft().dementors_enabled ? 'Enabled' : 'Off' }}</dd>
            </dl>
          </div>
        </div>

        @if (saveError(); as msg) {
          <div class="alert alert-danger">{{ msg }}</div>
        }

        <div class="d-flex gap-2 mb-4">
          <button
            type="button"
            class="btn btn-primary"
            [disabled]="!canSubmit() || saving()"
            (click)="submit()"
          >
            @if (saving()) {
              <span class="spinner-border spinner-border-sm me-1"></span>
            }
            {{ gameId() ? 'Save changes' : 'Create game' }}
          </button>
          <a routerLink="/games" class="btn btn-outline-secondary">Cancel</a>
        </div>

        @if (gameId(); as id) {
          <div class="card mb-3">
            <div class="card-body">
              <h2 class="h6 mb-3">
                Advanced
                <app-info-hint text="Custom in-game roles and live score multipliers belong to this Game template and are edited here." />
              </h2>
              <h3 class="h6 text-body-secondary">Game roles</h3>
              <app-game-roles-panel [gameId]="id" />
              <h3 class="h6 text-body-secondary mt-4">Score multipliers</h3>
              <app-score-multipliers-panel [gameId]="id" />
            </div>
          </div>
        }
      </div>

      <!-- Back / next --------------------------------------------------------------- -->
      <div class="d-flex justify-content-between gw-nav-footer">
        <button type="button" class="btn btn-outline-secondary" [disabled]="currentStep() === 0" (click)="back()">
          <i class="bi bi-arrow-left"></i> Back
        </button>
        @if (currentStep() < steps.length - 1) {
          <button type="button" class="btn btn-primary" (click)="next()">
            Next <i class="bi bi-arrow-right"></i>
          </button>
        }
      </div>
    }
  `,
  styles: `
    .gw-steps {
      flex-wrap: wrap;
      gap: var(--space-1);
    }

    .gw-step-btn {
      display: inline-flex;
      align-items: center;
      gap: var(--space-2);
      min-height: 44px;
      padding-left: var(--space-3);
      padding-right: var(--space-3);
    }

    .gw-step-num {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 1.5rem;
      height: 1.5rem;
      border-radius: 50%;
      background: var(--panel-sunken);
      font-size: var(--text-xs);
      font-weight: 650;
    }

    .nav-link.active .gw-step-num {
      background: rgba(255, 255, 255, 0.25);
    }

    .gw-step-btn--invalid:not(.active) {
      border: 1px solid var(--danger);
    }

    .gw-toggle-row {
      min-height: 44px;
      display: flex;
      align-items: center;
      gap: var(--space-2);
      padding-left: 2.5em;
    }

    .gw-toggle-row .form-check-input {
      margin-left: -2.5em;
    }

    .gw-map {
      width: 100%;
      height: 280px;
      border-radius: var(--radius);
      border: 1px solid var(--border);
    }

    .gw-nav-footer {
      position: sticky;
      bottom: 0;
      padding: var(--space-3) 0;
      background: var(--bg);
      border-top: 1px solid var(--border);
      margin-top: var(--space-4);
    }

    @media (max-width: 640px) {
      .gw-steps {
        flex-direction: column;
        align-items: stretch;
      }

      .gw-step-btn {
        width: 100%;
      }
    }
  `,
})
export class GameWizardComponent {
  private readonly api = inject(StaffApiService);
  private readonly route = inject(ActivatedRoute);
  private readonly router = inject(Router);

  protected readonly steps = STEPS;
  protected readonly currentStep = signal(0);

  protected readonly gameId = signal<number | null>(null);
  protected readonly loading = signal(false);
  protected readonly loadError = signal<string | null>(null);
  protected readonly saving = signal(false);
  protected readonly saveError = signal<string | null>(null);

  protected readonly draft = signal<GameWizardDraft>(defaultDraft());
  protected readonly allCollections = signal<AdminCollection[]>([]);
  private slugTouched = false;

  private readonly mapContainer = viewChild<ElementRef<HTMLDivElement>>('mapContainer');
  private map: L.Map | null = null;
  private marker: L.CircleMarker | null = null;

  protected readonly nameError = computed(() =>
    this.draft().name.trim().length === 0 ? 'Required.' : null,
  );
  protected readonly slugError = computed(() => {
    const slug = this.draft().slug;
    if (slug.trim().length === 0) return 'Required.';
    if (!SLUG_RE.test(slug)) {
      return 'Lowercase letters, numbers and hyphens only.';
    }
    return null;
  });
  protected readonly basicsValid = computed(() => !this.nameError() && !this.slugError());

  protected readonly teamsError = computed(() => {
    const d = this.draft();
    if (d.min_teams < 1) return 'Minimum teams must be at least 1.';
    if (d.min_members_per_team < 1) return 'Minimum members per team must be at least 1.';
    if (d.max_teams !== 0 && d.max_teams < d.min_teams) {
      return 'Maximum teams cannot be smaller than the minimum (or 0 for no cap).';
    }
    if (d.max_members_per_team !== 0 && d.max_members_per_team < d.min_members_per_team) {
      return 'Maximum members per team cannot be smaller than the minimum (or 0 for no cap).';
    }
    return null;
  });
  protected readonly teamsValid = computed(() => !this.teamsError());

  protected readonly stepValid = computed<boolean[]>(() => [
    this.basicsValid(),
    true,
    this.teamsValid(),
    true,
    true,
    true,
    true,
  ]);
  protected readonly canSubmit = computed(() =>
    this.stepValid()
      .slice(0, -1)
      .every((v) => v),
  );

  // ---- Field-group metadata (rendered via @for to avoid ~60 near-identical
  // blocks) ----------------------------------------------------------------

  protected readonly teamRuleFields: {
    field: 'min_teams' | 'max_teams' | 'min_members_per_team' | 'max_members_per_team';
    label: string;
    hint: string;
    min: number;
  }[] = [
    { field: 'min_teams', label: 'Min teams', hint: 'A session can only start once at least this many teams are ready.', min: 1 },
    { field: 'max_teams', label: 'Max teams', hint: '0 means no cap.', min: 0 },
    { field: 'min_members_per_team', label: 'Min members/team', hint: 'Below this, a team does not count as ready.', min: 1 },
    { field: 'max_members_per_team', label: 'Max members/team', hint: '0 means no cap.', min: 0 },
  ];

  protected readonly realtimeFields: {
    field: 'realtime_enabled' | 'push_notifications_enabled';
    label: string;
    hint: string;
  }[] = [
    {
      field: 'realtime_enabled',
      label: 'Realtime updates',
      hint: "On (default) keeps the live map/scoreboard pushed over WebSocket; clients still fall back to polling automatically if a socket can't connect.",
    },
    {
      field: 'push_notifications_enabled',
      label: 'Push notifications',
      hint: "Off by default. Turn on once your push setup is ready to notify players' devices of key events.",
    },
  ];

  protected readonly nfcFields: {
    field: 'nfc_secure_mode' | 'nfc_require_app' | 'nfc_replay_hardening';
    label: string;
    hint: string;
  }[] = [
    {
      field: 'nfc_secure_mode',
      label: 'Secure token mode',
      hint: 'Require the secure NFC token flow instead of legacy forwardable RFID URLs. Off preserves existing tags.',
    },
    {
      field: 'nfc_require_app',
      label: 'Require the player app',
      hint: 'Scans must open inside the player app, not a bare browser tab. Only meaningful with secure mode on.',
    },
    {
      field: 'nfc_replay_hardening',
      label: 'Replay hardening',
      hint: 'Reject a scan of the same NFC token twice in quick succession, to blunt QR/photo replay.',
    },
  ];

  protected readonly bleNumFields: {
    field:
      | 'ble_report_interval_seconds'
      | 'ble_scan_duty_cycle_percent'
      | 'ble_freshness_window_seconds'
      | 'ble_identity_rotation_minutes'
      | 'ble_rssi_very_close_dbm'
      | 'ble_rssi_near_dbm'
      | 'ble_rssi_hysteresis_db';
    label: string;
    hint: string;
  }[] = [
    { field: 'ble_report_interval_seconds', label: 'Report interval (s)', hint: 'How often a phone reports nearby BLE beacons to the server.' },
    { field: 'ble_scan_duty_cycle_percent', label: 'Scan duty cycle (%)', hint: 'Share of each interval spent actively scanning — lower saves battery, higher improves detection speed.' },
    { field: 'ble_freshness_window_seconds', label: 'Freshness window (s)', hint: 'A sighting older than this is treated as stale and ignored.' },
    { field: 'ble_identity_rotation_minutes', label: 'Identity rotation (min)', hint: "How often a beacon's broadcast identity rotates, for privacy." },
    { field: 'ble_rssi_very_close_dbm', label: 'RSSI "very close" (dBm)', hint: 'Signal strength at or above this counts as very close. Less negative = closer required.' },
    { field: 'ble_rssi_near_dbm', label: 'RSSI "near" (dBm)', hint: 'Signal strength at or above this counts as near.' },
    { field: 'ble_rssi_hysteresis_db', label: 'RSSI hysteresis (dB)', hint: 'Buffer before flipping between proximity buckets, to stop flicker at the boundary.' },
  ];

  protected readonly dementorNumFields: {
    field:
      | 'dementor_initial_dementors'
      | 'dementor_starting_energy'
      | 'dementor_drain_per_second'
      | 'dementor_restore_per_second'
      | 'dementor_wizard_regen_per_second'
      | 'dementor_tick_seconds';
    label: string;
    hint: string;
    step?: number;
  }[] = [
    { field: 'dementor_initial_dementors', label: 'Initial dementors', hint: 'How many dementors start active.', step: 1 },
    { field: 'dementor_starting_energy', label: 'Starting energy', hint: 'Energy each wizard starts with before any draining.', step: 1 },
    { field: 'dementor_drain_per_second', label: 'Drain / second', hint: 'Energy a nearby dementor drains from a wizard each second.', step: 0.1 },
    { field: 'dementor_restore_per_second', label: 'Restore / second', hint: 'Energy per second a wizard regains once out of a dementor\'s range.', step: 0.1 },
    { field: 'dementor_wizard_regen_per_second', label: 'Passive regen / second', hint: 'Passive energy regeneration regardless of dementor proximity (0 = none).', step: 0.1 },
    { field: 'dementor_tick_seconds', label: 'Simulation tick (s)', hint: 'How often the drain/restore simulation ticks.', step: 1 },
  ];

  protected readonly pauseFields: {
    field: 'pause_freezes_floating_score' | 'pause_restores_ownerships_on_resume' | 'pause_rejects_submissions';
    label: string;
    hint: string;
  }[] = [
    { field: 'pause_freezes_floating_score', label: 'Freeze floating score while paused', hint: "Zone floating points stop accruing during a pause window." },
    { field: 'pause_restores_ownerships_on_resume', label: 'Restore ownerships on resume', hint: 'Tower/zone control from before the pause carries over into the resumed run.' },
    { field: 'pause_rejects_submissions', label: 'Reject submissions while paused', hint: 'Challenge submissions made during a pause are auto-rejected instead of queued.' },
  ];

  // ---- Enum label options --------------------------------------------------

  protected readonly modeOptions: { value: GameMode; label: string }[] = [
    { value: 'DOMINATION', label: 'Domination — capture towers, hold zones (default)' },
    { value: 'TRAIL', label: 'Trail / discovery — clue-driven point-to-point run' },
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

  protected readonly confirmationOptions: { value: TeamJoinConfirmation; label: string }[] = [
    { value: 'AUTO_APPROVE', label: 'Auto-approve joins (default)' },
    { value: 'CAPTAIN', label: 'Captain approves joins' },
    { value: 'STAFF', label: 'Staff approve joins' },
  ];

  protected readonly towerLockModeOptions: { value: TowerLockMode; label: string }[] = [
    { value: 'FREE_FOR_ALL', label: 'Free for all (default)' },
    { value: 'LOCK_ON_INITIATE', label: 'Lock on initiate' },
  ];

  protected readonly discoverabilityOptions: { value: Discoverability; label: string }[] = [
    { value: 'VISIBLE', label: 'Visible (default)' },
    { value: 'HIDDEN', label: 'Hidden — pops up on approach' },
    { value: 'FOG_REVEAL', label: 'Fog reveal — uncover the zone' },
  ];

  protected readonly challengeVisibilityOptions: { value: ChallengeVisibility; label: string }[] = [
    { value: 'VISIBLE_ANYWHERE', label: 'Visible anywhere (default)' },
    { value: 'HIDDEN_UNTIL_ARRIVAL', label: 'Hidden until arrival' },
  ];

  protected readonly togethernessOptions: { value: TogethernessMode; label: string }[] = [
    { value: 'SPLIT_ALLOWED', label: 'Members may split up (default)' },
    { value: 'WHOLE_TEAM_TOGETHER', label: 'Whole team must be together' },
  ];

  protected readonly teammateVisibilityOptions: { value: TeammateVisibilityMode; label: string }[] = [
    { value: 'OWN_TEAM', label: 'Own team only (default)' },
    { value: 'EVERYONE', label: 'Everyone in the session' },
    { value: 'SELECT_COUNT', label: 'The nearest N players' },
  ];

  protected readonly locationVisibilityOptions: { value: LocationVisibility; label: string }[] = [
    { value: 'NONE', label: 'Stored only — nothing shown to players' },
    { value: 'OWN_TEAM', label: 'Players see their own team (default)' },
    { value: 'EVERYONE', label: 'Players see everyone' },
  ];

  protected readonly proximityBucketOptions: { value: ProximityBucket; label: string }[] = [
    { value: 'VERY_CLOSE', label: 'Very close' },
    { value: 'NEAR', label: 'Near (default)' },
    { value: 'FAR', label: 'Far' },
  ];

  protected readonly dementorEmptyOptions: { value: DementorEmptyOutcome; label: string }[] = [
    { value: 'FLIP', label: 'Flip to dementor on empty (default)' },
    { value: 'DIE', label: 'Out of play on empty' },
  ];

  protected readonly resetOptions: { value: FailCounterReset; label: string }[] = [
    { value: 'TOWER_SUCCESS_ONLY', label: 'Reset only on success at the same tower (default)' },
    { value: 'ANY_SUCCESS_ELSEWHERE', label: 'Reset on any confirmed submission' },
    { value: 'ANY_ATTEMPT_ELSEWHERE', label: 'Reset on any submission anywhere' },
  ];

  constructor() {
    const idParam = this.route.snapshot.paramMap.get('id');
    if (idParam) {
      const id = Number(idParam);
      this.gameId.set(id);
      this.loading.set(true);
      this.api.getGame(id).subscribe({
        next: (g) => {
          this.draft.set(draftFromGame(g));
          this.slugTouched = true;
          this.loading.set(false);
          this.recenterMap();
        },
        error: (err) => {
          this.loading.set(false);
          this.loadError.set(extractErrorMessage(err));
        },
      });
    }
    this.api.listCollections().subscribe({
      next: (list) => this.allCollections.set(list),
      error: () => {},
    });

    afterNextRender(() => this.initMap());

    effect(() => {
      const d = this.draft();
      if (!this.marker) return;
      if (d.base_lat === null || d.base_lng === null) return;
      const current = this.marker.getLatLng();
      if (Math.abs(current.lat - d.base_lat) > 1e-9 || Math.abs(current.lng - d.base_lng) > 1e-9) {
        this.marker.setLatLng([d.base_lat, d.base_lng]);
      }
    });
  }

  // ---- Generic helpers ------------------------------------------------------

  protected patch<K extends keyof GameWizardDraft>(field: K, value: GameWizardDraft[K]): void {
    this.draft.update((d) => ({ ...d, [field]: value }));
  }

  /** Coerces a number input's emitted value (which may be '' when cleared). */
  protected numOr(value: number | string | null, fallback: number): number {
    if (value === null || value === '') return fallback;
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
  }

  protected modeLabel(mode: GameMode): string {
    return this.modeOptions.find((o) => o.value === mode)?.label ?? mode;
  }

  // ---- Step navigation --------------------------------------------------

  protected goToStep(i: number): void {
    this.currentStep.set(i);
    if (i === 0) {
      setTimeout(() => this.map?.invalidateSize(), 0);
    }
  }

  protected next(): void {
    if (this.currentStep() < this.steps.length - 1) {
      this.goToStep(this.currentStep() + 1);
    }
  }

  protected back(): void {
    if (this.currentStep() > 0) {
      this.goToStep(this.currentStep() - 1);
    }
  }

  // ---- Basics: slug auto-suggest + collections ---------------------------

  protected onNameChange(value: string): void {
    this.patch('name', value);
    if (!this.slugTouched) {
      this.patch('slug', slugify(value));
    }
  }

  protected onSlugChange(value: string): void {
    this.slugTouched = true;
    this.patch('slug', value);
  }

  protected toggleCollection(id: number): void {
    const has = this.draft().collections.includes(id);
    this.patch('collections', has ? this.draft().collections.filter((c) => c !== id) : [...this.draft().collections, id]);
  }

  // ---- Map picker ---------------------------------------------------------

  private initMap(): void {
    const el = this.mapContainer()?.nativeElement;
    if (!el || this.map) return;
    const d = this.draft();
    const center: [number, number] =
      d.base_lat !== null && d.base_lng !== null ? [d.base_lat, d.base_lng] : FALLBACK_CENTER;
    this.map = L.map(el).setView(center, d.base_zoom_level || FALLBACK_ZOOM);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(this.map);
    if (d.base_lat !== null && d.base_lng !== null) {
      this.marker = L.circleMarker(center, MARKER_STYLE).addTo(this.map);
    }
    this.map.on('click', (e: L.LeafletMouseEvent) => this.placeMarker(e.latlng.lat, e.latlng.lng, false));
  }

  private recenterMap(): void {
    const d = this.draft();
    if (!this.map || d.base_lat === null || d.base_lng === null) return;
    const center: [number, number] = [d.base_lat, d.base_lng];
    this.map.setView(center, d.base_zoom_level || FALLBACK_ZOOM);
    if (!this.marker) {
      this.marker = L.circleMarker(center, MARKER_STYLE).addTo(this.map);
    } else {
      this.marker.setLatLng(center);
    }
  }

  private placeMarker(lat: number, lng: number, pan: boolean): void {
    const rlat = Math.round(lat * 1e6) / 1e6;
    const rlng = Math.round(lng * 1e6) / 1e6;
    this.draft.update((d) => ({ ...d, base_lat: rlat, base_lng: rlng }));
    if (!this.marker && this.map) {
      this.marker = L.circleMarker([rlat, rlng], MARKER_STYLE).addTo(this.map);
    } else {
      this.marker?.setLatLng([rlat, rlng]);
    }
    if (pan) this.map?.panTo([rlat, rlng]);
  }

  protected onLatChange(value: number | null): void {
    this.patch('base_lat', value);
    if (value !== null && this.draft().base_lng !== null) {
      this.placeMarker(value, this.draft().base_lng!, true);
    }
  }

  protected onLngChange(value: number | null): void {
    this.patch('base_lng', value);
    if (value !== null && this.draft().base_lat !== null) {
      this.placeMarker(this.draft().base_lat!, value, true);
    }
  }

  // ---- Submit ---------------------------------------------------------------

  protected submit(): void {
    if (!this.canSubmit() || this.saving()) return;
    this.saving.set(true);
    this.saveError.set(null);
    const payload: AdminGamePayload = { ...this.draft() };
    const id = this.gameId();
    const obs = id ? this.api.updateGame(id, payload) : this.api.createGame({ ...payload, is_active: false });
    obs.subscribe({
      next: (g) => {
        this.saving.set(false);
        if (!id) {
          this.router.navigate(['/games', g.id, 'edit']);
        } else {
          this.draft.set(draftFromGame(g));
        }
      },
      error: (err) => {
        this.saving.set(false);
        this.saveError.set(extractErrorMessage(err));
      },
    });
  }
}
