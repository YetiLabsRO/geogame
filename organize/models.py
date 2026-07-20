import uuid

from colorfield.fields import ColorField
from django.conf import settings
from django.contrib.gis.db.models import PointField
from django.core.exceptions import ValidationError
from django.db import models
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

    # --- Team-composition rules. Minima default to 1, maxima use 0 to
    # mean "no cap", so defaults keep a single one-member team startable.
    # Overridable per Session (see Session.effective). ---
    min_teams = models.PositiveSmallIntegerField(default=1)
    max_teams = models.PositiveSmallIntegerField(default=0)
    min_members_per_team = models.PositiveSmallIntegerField(default=1)
    max_members_per_team = models.PositiveSmallIntegerField(default=0)

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


class TeamGroup(models.Model):
    name = models.CharField(max_length=255)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    slug = models.SlugField()

    class Meta:
        unique_together = (('game', 'slug'),)


class Session(models.Model):
    """A single run of a Game with its own roster and scoreboard.

    Multiple sessions on the same Game share Zone / Tower / Challenge /
    TeamGroup configuration but keep separate Teams and ownership
    state. Each session carries its own clock; shared-clock
    SessionGroups are a future phase.
    """

    game = models.ForeignKey(
        Game, on_delete=models.CASCADE, related_name='sessions',
    )
    slug = models.SlugField(max_length=64)
    name = models.CharField(max_length=255)
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    is_active = models.BooleanField(default=False)
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

    # --- Team-composition overrides. NULL means "inherit the Game
    # default"; a 0 maximum means "explicitly no cap". ---
    min_teams = models.PositiveSmallIntegerField(null=True, blank=True)
    max_teams = models.PositiveSmallIntegerField(null=True, blank=True)
    min_members_per_team = models.PositiveSmallIntegerField(null=True, blank=True)
    max_members_per_team = models.PositiveSmallIntegerField(null=True, blank=True)

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
