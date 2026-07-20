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
)


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

    def __init__(self, message, *, requires_override=False):
        super().__init__(message)
        self.requires_override = requires_override


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
        # Seam for the game-config-team-rules change: when it lands, it
        # provides Session.can_start() / start_blockers() gating helpers
        # that this hook picks up without further wiring here.
        gate = getattr(self, 'can_start', None)
        if callable(gate) and not gate():
            blockers_fn = getattr(self, 'start_blockers', None)
            blockers = blockers_fn() if callable(blockers_fn) else []
            detail = '; '.join(str(b) for b in blockers) or 'start conditions not met'
            raise IllegalTransition(f'Session cannot start: {detail}.')

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

    @property
    def game(self):
        """Convenience accessor: a Team's Game is its Session's Game."""
        return self.session.game

    def __str__(self):
        return self.name

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


def _default_invite_expiry():
    return timezone.now() + timezone.timedelta(days=14)


class Invite(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='invites')
    email = models.EmailField(blank=True, null=True)
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

    def __str__(self):
        label = self.email or 'no-email'
        return f'Invite({self.team.name} → {label})'
