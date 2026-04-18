import uuid

from colorfield.fields import ColorField
from django.conf import settings
from django.contrib.gis.db.models import PointField
from django.db import models
from django.db.models import ManyToManyField
from django.utils import timezone
from smart_selects.db_fields import ChainedForeignKey


class Game(models.Model):
    name = models.CharField(max_length=255)

    base_point = PointField(null=True, blank=True)
    base_zoom_level = models.PositiveSmallIntegerField(default=15)

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    is_active = models.BooleanField(default=False)

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profile')
    current_game = models.ForeignKey(
        Game, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
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


class Team(models.Model):
    name = models.CharField(max_length=255)
    game = models.ForeignKey(Game, on_delete=models.CASCADE)
    code = models.CharField(max_length=8, unique=True)
    group = ChainedForeignKey(
        TeamGroup,
        on_delete=models.CASCADE,
        chained_field="game",
        chained_model_field="game",
        blank=True,
        null=True
    )
    color = ColorField()
    description = models.TextField(null=True, blank=True)
    members = ManyToManyField(
        UserProfile, blank=True, related_name='teams', through='organize.TeamMembership',
    )

    score = models.PositiveIntegerField(default=0)

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


class TeamMembership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(UserProfile, on_delete=models.CASCADE, related_name='memberships')
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
        ]

    def __str__(self):
        return f'{self.user} in {self.team}'


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
