from colorfield.fields import ColorField
from django.contrib.auth import get_user_model
from django.contrib.gis.db.models import PointField
from django.db import models
from django.db.models import ManyToManyField
from smart_selects.db_fields import ChainedForeignKey, ChainedManyToManyField


class Player(models.Model):
    user = models.OneToOneField(get_user_model(), on_delete=models.CASCADE)


class Game(models.Model):
    name = models.CharField(max_length=255)
    players = models.ManyToManyField(Player, blank=True, related_name='games')

    base_point = PointField(null=True, blank=True)
    base_zoom_level = models.PositiveSmallIntegerField(default=15)

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    is_active = models.BooleanField(default=False)

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
    players = ManyToManyField(Player, blank=True, related_name='teams', through="organize.TeamPlayer")

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


class TeamPlayer(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    player = models.ForeignKey(Player, on_delete=models.CASCADE)

    joined_at = models.DateTimeField()
