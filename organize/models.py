import uuid
from datetime import timedelta

from colorfield.fields import ColorField
from django.conf import settings
from django.contrib.gis.db.models import PointField
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import ManyToManyField
from django.utils import timezone

# Consecutive-fail counter reset policies (Phase 10, §21.1).
FAIL_RESET_TOWER_SUCCESS_ONLY = 'TOWER_SUCCESS_ONLY'
FAIL_RESET_ANY_SUCCESS_ELSEWHERE = 'ANY_SUCCESS_ELSEWHERE'
FAIL_RESET_ANY_ATTEMPT_ELSEWHERE = 'ANY_ATTEMPT_ELSEWHERE'
FAIL_RESET_CHOICES = [
    (FAIL_RESET_TOWER_SUCCESS_ONLY, 'Reset only on a confirmed submission at the same tower'),
    (FAIL_RESET_ANY_SUCCESS_ELSEWHERE, 'Also reset on a confirmed submission at any other tower'),
    (FAIL_RESET_ANY_ATTEMPT_ELSEWHERE, 'Also reset on any submission at any other tower'),
]

# Built-in role powers (team-roles-as-mechanics). Most GameRoles are
# arbitrary flavor with no engine behavior (NONE); a few opt into a
# known power. New powers become new enum values, not new models.
BUILTIN_POWER_NONE = 'NONE'
BUILTIN_POWER_INVITER = 'INVITER'
BUILTIN_POWER_CHOICES = [
    (BUILTIN_POWER_NONE, 'No built-in power'),
    (BUILTIN_POWER_INVITER, 'Inviter — may invite players into their team'),
]

# Coarse BLE proximity buckets (ble-proximity capability). Ordinal,
# closest first; the server never exposes metres. Defined here (like the
# FAIL_RESET_* choices) so Game/Session config fields can reference them
# without a circular organize→game import.
PROXIMITY_BUCKET_VERY_CLOSE = 'VERY_CLOSE'
PROXIMITY_BUCKET_NEAR = 'NEAR'
PROXIMITY_BUCKET_FAR = 'FAR'
PROXIMITY_BUCKET_CHOICES = [
    (PROXIMITY_BUCKET_VERY_CLOSE, 'Very close'),
    (PROXIMITY_BUCKET_NEAR, 'Near'),
    (PROXIMITY_BUCKET_FAR, 'Far'),
]

# What happens to a wizard drained to empty (mode-dementors).
DEMENTOR_EMPTY_FLIP = 'FLIP'
DEMENTOR_EMPTY_DIE = 'DIE'
DEMENTOR_EMPTY_CHOICES = [
    (DEMENTOR_EMPTY_FLIP, 'Flip to dementor on empty'),
    (DEMENTOR_EMPTY_DIE, 'Out of play on empty'),
]

# Team-join confirmation policies (player-team-formation).
JOIN_CONFIRM_AUTO_APPROVE = 'AUTO_APPROVE'
JOIN_CONFIRM_CAPTAIN = 'CAPTAIN'
JOIN_CONFIRM_STAFF = 'STAFF'
JOIN_CONFIRM_CHOICES = [
    (JOIN_CONFIRM_AUTO_APPROVE, 'Auto-approve joins'),
    (JOIN_CONFIRM_CAPTAIN, 'Captain approves joins'),
    (JOIN_CONFIRM_STAFF, 'Staff approve joins'),
]

# Config fields that live on Game as defaults and are overridable per
# Session. `Session.effective(field)` resolves override-or-default.
OVERRIDABLE_CONFIG_FIELDS = (
    'pause_freezes_floating_score',
    'pause_restores_ownerships_on_resume',
    'pause_rejects_submissions',
    'fail_point_penalty',
    'fail_cooloff_scaling',
    'fail_tower_lockout_minutes',
    'fail_difficulty_rollback',
    'fail_counter_reset',
    'min_teams',
    'max_teams',
    'min_members_per_team',
    'max_members_per_team',
    'allow_player_team_creation',
    # BLE proximity substrate knobs (ble-proximity capability).
    'require_ble_capable',
    'ble_report_interval_seconds',
    'ble_scan_duty_cycle_percent',
    'ble_freshness_window_seconds',
    'ble_identity_rotation_minutes',
    'ble_rssi_very_close_dbm',
    'ble_rssi_near_dbm',
    'ble_rssi_hysteresis_db',
    # Dementors mode knobs (mode-dementors capability).
    'dementors_enabled',
    'dementor_initial_dementors',
    'dementor_starting_energy',
    'dementor_drain_per_second',
    'dementor_drain_range_bucket',
    'dementor_empty_outcome',
    'dementor_safety_in_numbers',
    'dementor_reverse_group_size',
    'dementor_reverse_hold_seconds',
    'dementor_conversion_threshold',
    'dementor_restore_per_second',
    'dementor_wizard_regen_per_second',
    'dementor_tick_seconds',
)


def effective_allow_player_team_creation(session):
    """Effective player team-creation toggle: Session override, else Game default."""
    return session.effective('allow_player_team_creation')


def effective_team_join_confirmation(team):
    """Effective join-confirmation policy: Team override, else Game default."""
    return team.team_join_confirmation or team.session.game.team_join_confirmation


class Game(models.Model):
    """Reusable event configuration — map, rules, challenge bank.

    Runtime state (dates, teams, ownership) lives on `Session` so that
    multiple independent runs can share the same Game.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=64, unique=True)

    base_point = PointField(null=True, blank=True)
    base_zoom_level = models.PositiveSmallIntegerField(default=15)

    is_active = models.BooleanField(default=False)

    # Per-game rule defaults. Existing callers hardcode 50m / 5min;
    # T3.6 will wire these through the request path.
    proximity_meters = models.PositiveSmallIntegerField(default=50)
    cooloff_minutes = models.PositiveSmallIntegerField(default=5)
    initial_bonus_default = models.PositiveIntegerField(default=0)

    # --- Phase 10: day-pausing knobs. Defaults preserve prior behavior;
    # overridable per Session (see Session.effective). ---
    pause_freezes_floating_score = models.BooleanField(default=True)
    pause_restores_ownerships_on_resume = models.BooleanField(default=True)
    pause_rejects_submissions = models.BooleanField(default=True)

    # --- Phase 10: challenge-failure knobs. All default to "off" so a
    # rejected submission keeps behaving as a plain cooloff. ---
    fail_point_penalty = models.PositiveIntegerField(default=0)
    fail_cooloff_scaling = models.FloatField(default=1.0)
    fail_tower_lockout_minutes = models.PositiveIntegerField(default=0)
    fail_difficulty_rollback = models.BooleanField(default=False)
    fail_counter_reset = models.CharField(
        max_length=32,
        choices=FAIL_RESET_CHOICES,
        default=FAIL_RESET_TOWER_SUCCESS_ONLY,
    )

    # --- Team-composition rules. Minima default to 1, maxima use 0 to
    # mean "no cap", so defaults keep a single one-member team startable.
    # Overridable per Session (see Session.effective). ---
    min_teams = models.PositiveSmallIntegerField(default=1)
    max_teams = models.PositiveSmallIntegerField(default=0)
    min_members_per_team = models.PositiveSmallIntegerField(default=1)
    max_members_per_team = models.PositiveSmallIntegerField(default=0)

    # --- Player team-formation knobs. Defaults preserve today's
    # staff-only roster building; overridable per Session
    # (allow_player_team_creation) / per Team (team_join_confirmation). ---
    allow_player_team_creation = models.BooleanField(default=False)
    team_join_confirmation = models.CharField(
        max_length=16,
        choices=JOIN_CONFIRM_CHOICES,
        default=JOIN_CONFIRM_AUTO_APPROVE,
    )

    # --- BLE proximity substrate defaults (ble-proximity). Cadence and
    # RSSI thresholds are coarse by design (buckets, never metres);
    # overridable per Session (see Session.effective). ---
    require_ble_capable = models.BooleanField(default=False)
    ble_report_interval_seconds = models.PositiveSmallIntegerField(default=10)
    ble_scan_duty_cycle_percent = models.PositiveSmallIntegerField(default=100)
    ble_freshness_window_seconds = models.PositiveSmallIntegerField(default=30)
    ble_identity_rotation_minutes = models.PositiveSmallIntegerField(default=15)
    ble_rssi_very_close_dbm = models.SmallIntegerField(default=-55)
    ble_rssi_near_dbm = models.SmallIntegerField(default=-75)
    ble_rssi_hysteresis_db = models.PositiveSmallIntegerField(default=5)

    # --- Dementors mode defaults (mode-dementors). `dementors_enabled`
    # is the opt-in gate: everything below is inert until a Game (or a
    # Session override) turns it on. Overridable per Session. ---
    dementors_enabled = models.BooleanField(default=False)
    dementor_initial_dementors = models.PositiveSmallIntegerField(default=1)
    dementor_starting_energy = models.FloatField(default=100.0)
    dementor_drain_per_second = models.FloatField(default=1.0)
    dementor_drain_range_bucket = models.CharField(
        max_length=16,
        choices=PROXIMITY_BUCKET_CHOICES,
        default=PROXIMITY_BUCKET_NEAR,
    )
    dementor_empty_outcome = models.CharField(
        max_length=8,
        choices=DEMENTOR_EMPTY_CHOICES,
        default=DEMENTOR_EMPTY_FLIP,
    )
    dementor_safety_in_numbers = models.BooleanField(default=True)
    dementor_reverse_group_size = models.PositiveSmallIntegerField(default=3)
    dementor_reverse_hold_seconds = models.PositiveSmallIntegerField(default=30)
    dementor_conversion_threshold = models.FloatField(default=100.0)
    dementor_restore_per_second = models.FloatField(default=1.0)
    dementor_wizard_regen_per_second = models.FloatField(default=0.0)
    dementor_tick_seconds = models.PositiveSmallIntegerField(default=5)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='games_created',
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    def __str__(self):
        return self.name

    def clone(self, slug, name=None, created_by=None):
        """Deep-copy this Game template.

        Copies config fields, TeamGroups, GameRoles, and Challenges,
        remapping each cloned Challenge's `required_roles` to the
        clone's own roles so the clone never references the original's
        roles. Zones/Towers are not cloned yet — that belongs to the
        `game-authoring-roles` capability, which extends this routine;
        until then tower-linked challenges are copied as generic
        (tower=None).
        """
        from game.models import Challenge

        with transaction.atomic():
            clone = Game.objects.get(pk=self.pk)
            clone.pk = None
            clone._state.adding = True
            clone.slug = slug
            clone.name = name or f'{self.name} (copy)'
            clone.is_active = False
            clone.created_by = created_by
            clone.created_at = None  # auto_now_add repopulates on save
            clone.save()

            for group in TeamGroup.objects.filter(game=self):
                TeamGroup.objects.create(game=clone, name=group.name, slug=group.slug)

            role_map = {}
            for role in self.roles.all():
                role_map[role.pk] = GameRole.objects.create(
                    game=clone,
                    name=role.name,
                    slug=role.slug,
                    description=role.description,
                    builtin_power=role.builtin_power,
                )

            challenges = Challenge.objects.filter(game=self).prefetch_related('required_roles')
            for challenge in challenges:
                required = list(challenge.required_roles.all())
                challenge_clone = Challenge.objects.create(
                    game=clone,
                    text=challenge.text,
                    tower=None,
                    difficulty=challenge.difficulty,
                    role_requirement_mode=challenge.role_requirement_mode,
                    require_holders_present=challenge.require_holders_present,
                )
                if required:
                    challenge_clone.required_roles.set(
                        [role_map[r.pk] for r in required],
                    )
            return clone


class GameRole(models.Model):
    """A creator-defined, per-Game in-game role (COOK, NAVIGATOR, …).

    Part of the Game template's authored rule set — mirrors TeamGroup's
    per-Game shape so authoring and cloning behave consistently. Not a
    staff/admin permission: `builtin_power` opts a role into a known
    engine behavior (currently only INVITER); everything else is flavor
    usable purely through challenge role requirements.
    """

    game = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='roles')
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=64)
    description = models.TextField(blank=True, default='')
    builtin_power = models.CharField(
        max_length=16,
        choices=BUILTIN_POWER_CHOICES,
        default=BUILTIN_POWER_NONE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('game', 'slug'),)

    def __str__(self):
        return f'{self.game.slug}/{self.slug}'


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    # Renamed from current_game in T3.3: scope is the runtime Session,
    # not the static Game. The Game is reachable via current_session.game.
    current_session = models.ForeignKey(
        'organize.Session',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    # Free-form key-value attributes (e.g. age group, experience level)
    # read best-effort by the staff balanced-team builder.
    attributes = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.user.get_username()

    def can_invite_to(self, team):
        """INVITER built-in power: may this user create invites for `team`?

        True for staff (the pre-existing path, unchanged), or when the
        user's ACTIVE membership on that team holds a role whose
        `builtin_power` is INVITER. With no INVITER role defined or
        assigned this returns False for non-staff — invite creation
        stays staff-only exactly as before this change.
        """
        if self.user.is_staff:
            return True
        return TeamRole.objects.filter(
            membership__user=self,
            membership__team=team,
            membership__is_active=True,
            role__builtin_power=BUILTIN_POWER_INVITER,
        ).exists()


class TeamGroup(models.Model):
    name = models.CharField(max_length=255)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    slug = models.SlugField()

    class Meta:
        unique_together = (('game', 'slug'),)


class IllegalTransition(Exception):
    """A lifecycle action that is not a legal edge from the current state.

    API layers translate this into HTTP 409. `requires_override` marks
    rejections that a staff `override` flag would allow (currently only
    the out-of-window `open_participation` timing bound).
    """

    def __init__(self, message, *, requires_override=False, blockers=None):
        super().__init__(message)
        self.requires_override = requires_override
        # Machine-readable start blockers (game-config-team-rules), when
        # the rejection is the start-gate; None otherwise.
        self.blockers = blockers


class Session(models.Model):
    """A single run of a Game with its own roster and scoreboard.

    Multiple sessions on the same Game share Zone / Tower / Challenge /
    TeamGroup configuration but keep separate Teams and ownership
    state. Each session carries its own clock; shared-clock
    SessionGroups are a future phase.
    """

    # --- Lifecycle states (session-lifecycle capability). ---
    DRAFT = 'DRAFT'
    OPEN_FOR_PARTICIPANTS = 'OPEN_FOR_PARTICIPANTS'
    RUNNING = 'RUNNING'
    PAUSED = 'PAUSED'
    FINISHED = 'FINISHED'
    STATE_CHOICES = [
        (DRAFT, 'Draft'),
        (OPEN_FOR_PARTICIPANTS, 'Open for participants'),
        (RUNNING, 'Running'),
        (PAUSED, 'Paused'),
        (FINISHED, 'Finished'),
    ]
    # States in which the derived `is_active` reads True (visible in
    # player / scoreboard views, selectable as current session).
    ACTIVE_STATES = (OPEN_FOR_PARTICIPANTS, RUNNING, PAUSED)

    # Canonical allowed-transition table — the single source of truth
    # used by the transition engine, serializers, and the runner UI.
    # Rows are (action, from_state, to_state); anything else is a 409.
    TRANSITIONS = (
        ('open_participation', DRAFT, OPEN_FOR_PARTICIPANTS),
        ('close_participation', OPEN_FOR_PARTICIPANTS, DRAFT),
        ('start', OPEN_FOR_PARTICIPANTS, RUNNING),
        ('pause', RUNNING, PAUSED),
        ('resume', PAUSED, RUNNING),
        ('finish', RUNNING, FINISHED),
        ('finish', PAUSED, FINISHED),
    )

    # `open_participation` timing bound relative to `scheduled_start`:
    # openable from 7 days before down to 1 hour before the planned start.
    PARTICIPATION_OPEN_MAX_BEFORE = timedelta(days=7)
    PARTICIPATION_OPEN_MIN_BEFORE = timedelta(hours=1)

    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name='sessions',
    )
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    state = models.CharField(
        max_length=32, choices=STATE_CHOICES, default=DRAFT,
    )
    # Optional planned RUNNING time; bounds when participation may open.
    scheduled_start = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sessions_created',
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True)

    # --- Phase 10: per-session overrides. NULL means "inherit the Game
    # default"; resolve with Session.effective(field). ---
    pause_freezes_floating_score = models.BooleanField(null=True, blank=True)
    pause_restores_ownerships_on_resume = models.BooleanField(null=True, blank=True)
    pause_rejects_submissions = models.BooleanField(null=True, blank=True)
    fail_point_penalty = models.PositiveIntegerField(null=True, blank=True)
    fail_cooloff_scaling = models.FloatField(null=True, blank=True)
    fail_tower_lockout_minutes = models.PositiveIntegerField(null=True, blank=True)
    fail_difficulty_rollback = models.BooleanField(null=True, blank=True)
    fail_counter_reset = models.CharField(
        max_length=32, choices=FAIL_RESET_CHOICES, null=True, blank=True,
    )
    allow_player_team_creation = models.BooleanField(null=True, blank=True)

    # --- Team-composition overrides. NULL means "inherit the Game
    # default"; a 0 maximum means "explicitly no cap". ---
    min_teams = models.PositiveSmallIntegerField(null=True, blank=True)
    max_teams = models.PositiveSmallIntegerField(null=True, blank=True)
    min_members_per_team = models.PositiveSmallIntegerField(null=True, blank=True)
    max_members_per_team = models.PositiveSmallIntegerField(null=True, blank=True)

    # --- BLE proximity substrate overrides (ble-proximity). NULL means
    # "inherit the Game default". ---
    require_ble_capable = models.BooleanField(null=True, blank=True)
    ble_report_interval_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    ble_scan_duty_cycle_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    ble_freshness_window_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    ble_identity_rotation_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    ble_rssi_very_close_dbm = models.SmallIntegerField(null=True, blank=True)
    ble_rssi_near_dbm = models.SmallIntegerField(null=True, blank=True)
    ble_rssi_hysteresis_db = models.PositiveSmallIntegerField(null=True, blank=True)

    # --- Dementors mode overrides (mode-dementors). NULL means
    # "inherit the Game default". ---
    dementors_enabled = models.BooleanField(null=True, blank=True)
    dementor_initial_dementors = models.PositiveSmallIntegerField(null=True, blank=True)
    dementor_starting_energy = models.FloatField(null=True, blank=True)
    dementor_drain_per_second = models.FloatField(null=True, blank=True)
    dementor_drain_range_bucket = models.CharField(
        max_length=16, choices=PROXIMITY_BUCKET_CHOICES, null=True, blank=True,
    )
    dementor_empty_outcome = models.CharField(
        max_length=8, choices=DEMENTOR_EMPTY_CHOICES, null=True, blank=True,
    )
    dementor_safety_in_numbers = models.BooleanField(null=True, blank=True)
    dementor_reverse_group_size = models.PositiveSmallIntegerField(null=True, blank=True)
    dementor_reverse_hold_seconds = models.PositiveSmallIntegerField(null=True, blank=True)
    dementor_conversion_threshold = models.FloatField(null=True, blank=True)
    dementor_restore_per_second = models.FloatField(null=True, blank=True)
    dementor_wizard_regen_per_second = models.FloatField(null=True, blank=True)
    dementor_tick_seconds = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        unique_together = (('game', 'slug'),)

    def __str__(self):
        return f'{self.game.slug}/{self.slug}'

    def effective(self, field):
        """Resolve an overridable config field: session override, else game default."""
        if field not in OVERRIDABLE_CONFIG_FIELDS:
            raise ValueError(f'{field!r} is not an overridable config field')
        value = getattr(self, field)
        if value is None:
            return getattr(self.game, field)
        return value

    # ------------------------------------------------------------------
    # Lifecycle state machine (session-lifecycle capability)
    # ------------------------------------------------------------------

    @property
    def is_active(self):
        """Derived, read-only successor of the old boolean column.

        True while the Session is visible in player / scoreboard views
        and selectable as a current session. Query with
        `state__in=Session.ACTIVE_STATES` at the ORM level.
        """
        return self.state in self.ACTIVE_STATES

    def is_running(self):
        return self.state == self.RUNNING

    def is_paused(self):
        return self.state == self.PAUSED

    def is_finished(self):
        return self.state == self.FINISHED

    @property
    def allowed_transitions(self):
        """Actions legal from the current state, in table order."""
        return [
            action for action, source, _target in self.TRANSITIONS
            if source == self.state
        ]

    def transition(self, action, *, actor=None, override=False):
        """Apply a lifecycle action atomically.

        Validates the current state against the canonical TRANSITIONS
        table, applies the action's side effects and the state change in
        one transaction, and raises IllegalTransition (mapped to HTTP
        409 by the API layer) for anything not in the table.
        """
        target = next(
            (
                to_state for act, from_state, to_state in self.TRANSITIONS
                if act == action and from_state == self.state
            ),
            None,
        )
        if target is None:
            raise IllegalTransition(
                f'Cannot {action} a session in state {self.state}.',
            )
        with transaction.atomic():
            getattr(self, f'_apply_{action}')(override=override)
            self.state = target
            self.save(update_fields=['state'])
        return self

    def _apply_open_participation(self, override=False):
        """Enforce the scheduled_start timing bound (7 days–1 hour before)."""
        if self.scheduled_start is None or override:
            return
        now = timezone.now()
        earliest = self.scheduled_start - self.PARTICIPATION_OPEN_MAX_BEFORE
        latest = self.scheduled_start - self.PARTICIPATION_OPEN_MIN_BEFORE
        if not (earliest <= now <= latest):
            raise IllegalTransition(
                'Participation may only open between 7 days and 1 hour '
                'before the scheduled start; use override to open anyway.',
                requires_override=True,
            )

    def _apply_close_participation(self, override=False):
        """Re-close the roster window; existing Teams are retained."""

    def _apply_start(self, override=False):
        # Start-gate: the team-composition thresholds from the
        # game-config-team-rules change. Blockers are dicts with a
        # machine-readable code and a human message (see start_blockers).
        if not self.can_start():
            blockers = self.start_blockers()
            detail = '; '.join(
                b.get('message', str(b)) for b in blockers
            ) or 'start conditions not met'
            raise IllegalTransition(
                f'Session cannot start: {detail}', blockers=blockers,
            )
        # mode-dementors: seed per-player roles + starting energy when the
        # mode is enabled for this run. Idempotent — existing states are
        # kept, so re-running a start after a rollback is safe.
        if self.effective('dementors_enabled'):
            from game.dementors import assign_initial_roles
            assign_initial_roles(self)

    def _apply_pause(self, override=False):
        from game.models import PauseWindow
        if PauseWindow.pause_session(self) is None:
            raise IllegalTransition('Session already has an open pause window.')

    def _apply_resume(self, override=False):
        from game.models import PauseWindow
        if PauseWindow.resume_session(self) is None:
            raise IllegalTransition('Session has no open pause window.')

    def _apply_finish(self, override=False):
        # Close any open pause window WITHOUT reopening ownerships, then
        # close every remaining open ownership (unassign_all semantics).
        from game.models import PauseWindow
        window = PauseWindow.open_for(self)
        if window is not None:
            window.ended_at = timezone.now()
            window.save(update_fields=['ended_at'])
        self.close_ownerships()

    def close_ownerships(self):
        """Close every open ownership for this Session's teams.

        Same semantics as `unassign_all` / the legacy deactivation path:
        tower ownerships close outright; zone ownerships lock their
        floating score into the team's cumulative score first. All
        records are preserved for session history.
        """
        from game.models import TeamTowerOwnership, TeamZoneOwnership
        now = timezone.now()
        team_ids = list(self.teams.values_list('id', flat=True))

        TeamTowerOwnership.objects.filter(
            team_id__in=team_ids, timestamp_end__isnull=True,
        ).update(timestamp_end=now)

        zone_ownerships = list(
            TeamZoneOwnership.objects
            .filter(team_id__in=team_ids, timestamp_end__isnull=True)
            .select_related('team', 'zone')
        )
        for zone_ownership in zone_ownerships:
            zone_ownership.timestamp_end = now
            zone_ownership.save()
            zone_ownership.team.update_score(zone_ownership.get_score())

    def accepts_roster_changes(self):
        """Whether Teams may be created / joined right now.

        Rosters form in OPEN_FOR_PARTICIPANTS; DRAFT and FINISHED are
        closed. RUNNING/PAUSED joins stay permitted for now — gating
        them is owned by the game-config-team-rules change.
        """
        return self.state not in (self.DRAFT, self.FINISHED)
    def ready_team_count(self):
        """Number of this Session's teams that satisfy the member rules."""
        return sum(1 for team in self.teams.all() if team.is_ready())

    def start_blockers(self):
        """Why this Session may not move into active play, as an ordered list.

        Each blocker is a dict with a machine-readable `code`, a
        human-readable `message`, and the relevant numbers (plus
        `team_id` / `team_name` for per-team blockers). Empty list ⇒
        the team-composition thresholds are met and the run may start.

        Only *ready* teams (see Team.is_ready) count toward `min_teams`,
        so padding with an empty team cannot unlock a competitive
        minimum. The non-zero `max_teams` cap counts every team.

        This is the single reusable start-gate: the staff activation
        path calls it, and any future lifecycle transition (see the
        game-lifecycle-states change) should call it too.
        """
        blockers = []
        min_teams = self.effective('min_teams')
        max_teams = self.effective('max_teams')
        min_members = self.effective('min_members_per_team')
        max_members = self.effective('max_members_per_team')

        teams = list(self.teams.order_by('name', 'id'))
        ready_count = sum(1 for team in teams if team.is_ready())

        if ready_count < min_teams:
            blockers.append({
                'code': 'too_few_teams',
                'required': min_teams,
                'current': ready_count,
                'message': (
                    f'Needs at least {min_teams} ready team(s); '
                    f'currently {ready_count}.'
                ),
            })
            for team in teams:
                count = team.active_member_count()
                if count < min_members:
                    shortfall = min_members - count
                    blockers.append({
                        'code': 'team_below_minimum',
                        'team_id': team.id,
                        'team_name': team.name,
                        'required': min_members,
                        'current': count,
                        'shortfall': shortfall,
                        'message': (
                            f'Team "{team.name}" has {count} of the required '
                            f'{min_members} member(s) ({shortfall} more needed).'
                        ),
                    })

        if max_teams and len(teams) > max_teams:
            blockers.append({
                'code': 'too_many_teams',
                'allowed': max_teams,
                'current': len(teams),
                'message': (
                    f'Allows at most {max_teams} team(s); '
                    f'currently {len(teams)}.'
                ),
            })

        if max_members:
            for team in teams:
                count = team.active_member_count()
                if count > max_members:
                    blockers.append({
                        'code': 'team_above_maximum',
                        'team_id': team.id,
                        'team_name': team.name,
                        'allowed': max_members,
                        'current': count,
                        'message': (
                            f'Team "{team.name}" has {count} members, over '
                            f'the maximum of {max_members}.'
                        ),
                    })

        return blockers

    def can_start(self):
        """True when no team-composition blocker prevents starting."""
        return not self.start_blockers()


class Team(models.Model):
    name = models.CharField(max_length=255)
    session = models.ForeignKey(
        Session, on_delete=models.CASCADE, related_name='teams',
    )
    # ChainedForeignKey dropped in T3.2 — with Team.game removed, a
    # single-hop chain from Team to TeamGroup would have to traverse
    # session.game, which smart_selects cannot express.
    group = models.ForeignKey(
        TeamGroup,
        on_delete=models.CASCADE,
        blank=True,
        null=True,
    )
    color = ColorField()
    description = models.TextField(null=True, blank=True)
    members = ManyToManyField(
        UserProfile, blank=True, related_name='teams', through='organize.TeamMembership',
    )

    score = models.PositiveIntegerField(default=0)

    # --- Player team-formation (see the team-formation capability). ---
    # The creating player; may manage this team's invites, join code and
    # join requests. Staff can manage any team's.
    captain = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teams_captained',
    )
    # Per-team override of Game.team_join_confirmation (null = inherit).
    team_join_confirmation = models.CharField(
        max_length=16, choices=JOIN_CONFIRM_CHOICES, null=True, blank=True,
    )
    # Untied, shareable join code: anyone holding it may (request to)
    # join while it is set. Rotatable / revocable by captain or staff.
    join_code = models.UUIDField(null=True, blank=True, unique=True, editable=False)

    @property
    def game(self):
        """Convenience accessor: a Team's Game is its Session's Game."""
        return self.session.game

    def __str__(self):
        return self.name

    def active_member_count(self, when=None):
        """Count of live members: TeamMembership rows with is_active=True.

        With `when`, counts the members who were on the roster at that
        moment instead (joined before it and not yet departed).
        """
        if when is None:
            return self.memberships.filter(is_active=True).count()
        return self.memberships.filter(
            models.Q(joined_at__lte=when)
            & (models.Q(left_at__isnull=True) | models.Q(left_at__gt=when)),
        ).count()

    def members_needed(self, when=None):
        """How many more members this team needs to reach the effective minimum."""
        minimum = self.session.effective('min_members_per_team')
        return max(0, minimum - self.active_member_count(when=when))

    def is_ready(self, when=None):
        """Whether the active-member count satisfies the effective member rules.

        Ready ⇔ count ≥ effective min_members_per_team and, when the
        effective max_members_per_team is non-zero, count ≤ that cap
        (0 means "no cap").
        """
        count = self.active_member_count(when=when)
        minimum = self.session.effective('min_members_per_team')
        maximum = self.session.effective('max_members_per_team')
        if count < minimum:
            return False
        if maximum and count > maximum:
            return False
        return True

    def update_score(self, score):
        self.score += score
        self.save()

    def floating_score(self, when=None):
        floating_score_current = 0
        for zone_ownership in self.teamzoneownership_set.filter(timestamp_end__isnull=True):
            floating_score_current += zone_ownership.get_score(when=when)
        return floating_score_current

    def current_score(self):
        return round(self.score + self.floating_score(), 2)

    def active_role_slugs(self):
        """Distinct role slugs held by this team's ACTIVE memberships.

        The unit of role coverage for rule evaluation: head-count never
        matters, only which distinct roles the active roster covers.
        """
        return set(
            TeamRole.objects.filter(
                membership__team=self, membership__is_active=True,
            ).values_list('role__slug', flat=True),
        )

    def rotate_join_code(self):
        """Issue a fresh untied join code, superseding any previous one."""
        self.join_code = uuid.uuid4()
        self.save(update_fields=['join_code'])
        return self.join_code

    def revoke_join_code(self):
        """Invalidate the current join code without issuing a new one."""
        self.join_code = None
        self.save(update_fields=['join_code'])


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='memberships')
    # Denormalized from team.session.game so the DB can enforce the
    # "one session per game per player" rule directly. Kept in sync
    # via save(); Teams don't move between sessions so drift is a
    # non-issue in normal operation.
    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name='memberships',
    )
    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'user'],
                condition=models.Q(is_active=True),
                name='unique_active_team_membership',
            ),
            models.UniqueConstraint(
                fields=['user', 'game'],
                condition=models.Q(is_active=True),
                name='unique_active_membership_per_game',
            ),
        ]

    def __str__(self):
        return f'{self.user} in {self.team}'

    def clean(self):
        """Refuse to grow a team past the effective max_members_per_team.

        Runs on the Django-admin add/edit form (full_clean); the API
        join paths (invite-accept) make the same check explicitly so
        they can return a friendly 409.
        """
        super().clean()
        if not self.is_active or self.team_id is None:
            return
        maximum = self.team.session.effective('max_members_per_team')
        if not maximum:
            return
        others = self.team.memberships.filter(is_active=True)
        if self.pk:
            others = others.exclude(pk=self.pk)
        if others.count() >= maximum:
            raise ValidationError(
                f'Team "{self.team.name}" is already at its maximum of '
                f'{maximum} member(s).',
            )

    def save(self, *args, **kwargs):
        # Keep the denormalized game FK in sync with the team's session.
        if self.team_id is not None:
            self.game_id = self.team.session.game_id
        super().save(*args, **kwargs)

    def role_slugs(self):
        """Slugs of the GameRoles this membership holds."""
        return list(self.roles.values_list('role__slug', flat=True))


class TeamRole(models.Model):
    """Assignment of a GameRole to a specific TeamMembership.

    "This member, in this team, in this run, holds this role." Attached
    to the membership (not the Team or the user globally) so roles
    travel with the roster, respect the membership lifecycle
    (`is_active`/`left_at`), and never leak across Sessions.
    """

    membership = models.ForeignKey(
        TeamMembership, on_delete=models.CASCADE, related_name='roles',
    )
    role = models.ForeignKey(
        GameRole, on_delete=models.CASCADE, related_name='assignments',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='team_roles_assigned',
    )
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = (('membership', 'role'),)

    def __str__(self):
        return f'{self.membership} as {self.role.slug}'

    def clean(self):
        if self.role_id is not None and self.membership_id is not None:
            if self.role.game_id != self.membership.game_id:
                raise ValidationError(
                    'Role must belong to the same Game as the membership.',
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


def user_can_invite_to_team(user, team):
    """May `user` create invites for `team`? Staff, or INVITER holder.

    Seam for the invite flow (coordinates with the `team-invites` /
    `team-formation` capabilities): call this wherever invite creation
    is authorized instead of a bare `is_staff` check.
    """
    if user is None or not user.is_authenticated:
        return False
    profile = getattr(user, 'profile', None)
    if profile is None:
        return user.is_staff
    return profile.can_invite_to(team)


def active_membership_conflict(profile, team):
    """Return the active membership blocking `profile` from joining `team`.

    One-active-membership-per-(user, game): a player already on another
    team in the same Game cannot join. Returns None when joining is fine
    (including when the player is already on `team` itself).
    """
    return (
        TeamMembership.objects
        .filter(user=profile, is_active=True, game=team.session.game)
        .exclude(team=team)
        .select_related('team')
        .first()
    )


class TeamJoinRequest(models.Model):
    """A player-initiated request to join a team.

    Direction matters: invites are initiated by the team, join requests
    by the joiner (browse-and-ask, or a QR/LINK acceptance on a team
    whose confirmation policy is not AUTO_APPROVE).
    """

    STATUS_PENDING = 'PENDING'
    STATUS_APPROVED = 'APPROVED'
    STATUS_REJECTED = 'REJECTED'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    SOURCE_BROWSE = 'BROWSE'
    SOURCE_QR = 'QR'
    SOURCE_LINK = 'LINK'
    SOURCE_CHOICES = [
        (SOURCE_BROWSE, 'Browsed the team list'),
        (SOURCE_QR, 'Scanned an untied QR / join code'),
        (SOURCE_LINK, 'Followed a recipient-bound invite link'),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='join_requests')
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='join_requests')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)
    source = models.CharField(max_length=8, choices=SOURCE_CHOICES, default=SOURCE_BROWSE)
    note = models.TextField(blank=True, default='')
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='join_requests_decided',
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'user'],
                condition=models.Q(status='PENDING'),
                name='unique_pending_join_request',
            ),
        ]

    def __str__(self):
        return f'JoinRequest({self.user} → {self.team.name}, {self.status})'

    def approve(self, decided_by=None):
        """Approve: stamp the decision and create the TeamMembership."""
        membership, _ = TeamMembership.objects.get_or_create(
            team=self.team, user=self.user, is_active=True,
        )
        self.status = self.STATUS_APPROVED
        self.decided_by = decided_by
        self.decided_at = timezone.now()
        self.save(update_fields=['status', 'decided_by', 'decided_at'])
        return membership

    def reject(self, decided_by=None):
        """Reject: stamp the decision; no membership is created."""
        self.status = self.STATUS_REJECTED
        self.decided_by = decided_by
        self.decided_at = timezone.now()
        self.save(update_fields=['status', 'decided_by', 'decided_at'])


def _default_invite_expiry():
    return timezone.now() + timezone.timedelta(days=14)


class Invite(models.Model):
    # Invite kinds: an untied QR any holder may accept while valid, vs a
    # recipient-bound LINK only its named recipient may accept.
    KIND_QR = 'QR'
    KIND_LINK = 'LINK'
    KIND_CHOICES = [
        (KIND_QR, 'Untied QR / shareable code'),
        (KIND_LINK, 'Recipient-bound link'),
    ]

    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='invites')
    email = models.EmailField(blank=True, null=True)
    kind = models.CharField(max_length=8, choices=KIND_CHOICES, default=KIND_QR)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='invites_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_invite_expiry)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='invites_accepted',
    )
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked = models.BooleanField(default=False)

    def is_usable(self):
        if self.revoked or self.accepted_at is not None:
            return False
        return self.expires_at > timezone.now()

    def is_recipient_bound(self):
        """A LINK invite with an email may only be accepted by that recipient."""
        return self.kind == self.KIND_LINK and bool(self.email)

    def __str__(self):
        label = self.email or 'no-email'
        return f'Invite({self.team.name} → {label})'
