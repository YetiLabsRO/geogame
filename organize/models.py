import uuid

from colorfield.fields import ColorField
from django.conf import settings
from django.contrib.gis.db.models import PointField
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
    'allow_player_team_creation',
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

    # --- Player team-formation knobs. Defaults preserve today's
    # staff-only roster building; overridable per Session
    # (allow_player_team_creation) / per Team (team_join_confirmation). ---
    allow_player_team_creation = models.BooleanField(default=False)
    team_join_confirmation = models.CharField(
        max_length=16,
        choices=JOIN_CONFIRM_CHOICES,
        default=JOIN_CONFIRM_AUTO_APPROVE,
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
    allow_player_team_creation = models.BooleanField(null=True, blank=True)

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

    def save(self, *args, **kwargs):
        # Keep the denormalized game FK in sync with the team's session.
        if self.team_id is not None:
            self.game_id = self.team.session.game_id
        super().save(*args, **kwargs)


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
