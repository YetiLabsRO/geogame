from colorfield.fields import ColorField
from django.contrib.gis.db import models
from django.conf import settings
from django.db.models import Count, Max
from datetime import datetime, timezone
import math


class Zone(models.Model):
    SCORE_LOG = 1
    SCORE_EXP = 2
    SCORE_LIN = 3
    SCORE_BONUS = 4

    ZONE_SCORING_CHOICES = [
        (SCORE_LOG, "Multe puncte la început, tot mai puține apoi"),
        (SCORE_EXP, "Putine puncte la început, tot mai multe apoi"),
        (SCORE_LIN, "Puncte proportional cu posesia"),
        (SCORE_BONUS, "Putine punct la început, tot mai multe apoi (bonus)")
    ]

    name = models.CharField(max_length=255)
    color = ColorField(default="#000000", max_length=18)
    scoring_type = models.PositiveSmallIntegerField(choices=ZONE_SCORING_CHOICES)
    shape = models.PolygonField(null=True, blank=True)

    def __str__(self):
        return self.name

    def zone_control(self, category):
        teams = self.teamzoneownership_set.filter(team__category=category, timestamp_end__isnull=True).values_list('team', flat=True)
        # return Team.objects.filter(pk__in=teams)
        return teams

    def assign_to_team(self, team, handover_time=None):
        if not handover_time:
            handover_time = datetime.now(timezone.utc)
        try:
            current_ownership = TeamZoneOwnership.objects.get(zone=self, timestamp_end__isnull=True, team__category=team.category)
            current_ownership.timestamp_end = handover_time
            current_ownership.save()
            current_ownership.team.update_score(current_ownership.get_score())
        except TeamZoneOwnership.DoesNotExist:
            pass

        TeamZoneOwnership.objects.create(zone=self, team=team, timestamp_start=handover_time)

    def _get_score_exp(self, seconds):
        mins = seconds / 60.
        return math.pow(mins, 2) / 140 + 10

    def _get_score_exp_bonus(self, seconds):
        mins = seconds / 60.
        return min(math.pow(mins, 2) / 25 + 50, 200)

    def _get_score_log(self, seconds):
        mins = seconds / 60.
        return 30 * math.log(mins) + pow(mins, 2) / 10000

    def _get_score_prop(self, seconds):
        mins = seconds / 60.
        return mins

    def get_score(self, seconds):
        score_functions = {
            Zone.SCORE_EXP: self._get_score_exp,
            Zone.SCORE_LOG: self._get_score_log,
            Zone.SCORE_LIN: self._get_score_prop,
            Zone.SCORE_BONUS: self._get_score_exp_bonus,
        }

        return score_functions[self.scoring_type](seconds)


class Tower(models.Model):
    CATEGORY_NORMAL = 1
    CATEGORY_RFID = 2
    CATEGORY_CHOICES = [
        (CATEGORY_NORMAL, "Normal"),
        (CATEGORY_RFID, "RFID")
    ]

    name = models.CharField(max_length=255)
    location = models.PointField()
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, null=True, blank=True)
    category = models.PositiveSmallIntegerField(choices=CATEGORY_CHOICES)
    is_active = models.BooleanField()

    initial_bonus = models.PositiveIntegerField(default=0, help_text="Număr inițial de puncte obținute la câștigarea turnului")
    decrease_initial_bonus = models.BooleanField(default=False, help_text="Dacă la fiecare recucerire ulterioară de către aceeași echipă să se înjumătățească numărul inițial de puncte obținute (minimul va fi 1)")

    autocreate_zone = models.BooleanField(default=False, verbose_name="Creează zonă", help_text="Creează o zonă nou, circulară, pentru acest turn")

    rfid_code = models.CharField(max_length=16, unique=True, null=True, blank=True)

    def __init__(self, *args, **kwargs):
        super(Tower, self).__init__(*args, **kwargs)
        self.__is_active = self.is_active

    def __str__(self):
        return self.name

    def unassign(self):
        handover_time = datetime.now(timezone.utc)
        ownerships = TeamTowerOwnership.objects.filter(tower=self, timestamp_end__isnull=True)
        ownerships.update(timestamp_end=handover_time)

        zone_tower_count = Tower.objects.filter(zone=self.zone, is_active=True).count()
        if zone_tower_count == 0:
            ownerships = TeamZoneOwnership.objects.filter(zone=self.zone, timestamp_end__isnull=True)
            for ownership in ownerships:
                ownership.timestamp_end = handover_time
                ownership.save()
                ownership.team.update_score(ownership.get_score())

        elif zone_tower_count > 0:
            #   recalculeaza ownership pentru situatia cu noul turn
            #   get current zone owners
            #   for each team type (separate controls)
            for category in [choice[0] for choice in Team.CATEGORY_CHOICES]:
                current_zone_control_teams = self.zone.zone_control(category=category)
                #   recalculate maximum number of towers owned in zone
                team_stats = TeamTowerOwnership.objects.filter(tower__zone=self.zone, tower__is_active=True,
                                                               timestamp_end__isnull=True, team__category=category)\
                    .values('team').annotate(tower_count=Count('tower'))

                if team_stats.count():
                    max_towers = max((stat['tower_count'] for stat in team_stats))
                    new_team_ids = list(stat['team'] for stat in team_stats if stat['tower_count'] == max_towers)
                else:
                    new_team_ids = []

                #   remove old owners that are not in control anymore
                to_remove = list(set(current_zone_control_teams) - set(new_team_ids))
                to_close = TeamZoneOwnership.objects.filter(zone=self.zone, timestamp_end__isnull=True, team__in=to_remove)
                for zone_ownership in to_close:
                    zone_ownership.timestamp_end = handover_time
                    zone_ownership.save()
                    zone_ownership.team.update_score(zone_ownership.get_score())

                #   add new zone owners
                to_add = list(set(new_team_ids) - set(current_zone_control_teams))
                for team_id in to_add:
                    TeamZoneOwnership.objects.create(zone=self.zone, team_id=team_id, timestamp_start=handover_time)

    def assign_to_team(self, team, challenge=None, no_bonus=False):
        if not no_bonus:
            bonus = self.initial_bonus
            if self.decrease_initial_bonus:
                previous_tower_ownerships = TeamTowerOwnership.objects.filter(tower=self, team=team).count()
                while previous_tower_ownerships > 0:
                    bonus = bonus / 2.
                    previous_tower_ownerships -= 1
            team.update_score(max(bonus, 1))

        handover_time = datetime.now(timezone.utc)
        try:
            ownership = TeamTowerOwnership.objects.exclude(team=team)\
                .get(tower=self, timestamp_end__isnull=True, team__category=team.category)
            ownership.timestamp_end = handover_time
            ownership.save()
        except TeamTowerOwnership.DoesNotExist:
            pass

        TeamTowerOwnership.objects.create(tower=self, team=team, timestamp_start=handover_time)

        #   when towers are reassigned, recalculate zone assignments
        zone_tower_count = Tower.objects.filter(zone=self.zone, is_active=True).count()
        if zone_tower_count == 1:
            #   for towers that control their zone on their own, this is straightforward
            self.zone.assign_to_team(team=team, handover_time=handover_time)
        elif zone_tower_count > 1:
            #   for towers that share control of their zone with other towers, we need to
            #   figure out more

            #   get current zone owners
            current_zone_control_teams = self.zone.zone_control(category=team.category)
            #   recalculate maximum number of towers owned in zone
            team_stats = TeamTowerOwnership.objects\
                .filter(tower__zone=self.zone, tower__is_active=True, timestamp_end__isnull=True,
                        team__category=team.category)\
                .values('team').annotate(tower_count=Count('tower'))

            max_towers = max((stat['tower_count'] for stat in team_stats))
            new_team_ids = list(stat['team'] for stat in team_stats if stat['tower_count'] == max_towers)

            #   remove old owners that are not in control anymore
            to_remove = list(set(current_zone_control_teams) - set(new_team_ids))
            to_close = TeamZoneOwnership.objects.filter(zone=self.zone, timestamp_end__isnull=True, team__in=to_remove)
            for zone_ownership in to_close:
                zone_ownership.timestamp_end = handover_time
                zone_ownership.save()
                zone_ownership.team.update_score(zone_ownership.get_score())

            #   add new zone owners
            to_add = list(set(new_team_ids) - set(current_zone_control_teams))
            for team_id in to_add:
                TeamZoneOwnership.objects.create(zone=self.zone, team_id=team_id, timestamp_start=handover_time)

    def get_next_challenge(self, team):
        #   first, use tower-related challenges
        max_difficulty = TeamTowerChallenge.objects.filter(team=team, tower=self, outcome=TeamTowerChallenge.CONFIRMED)\
            .aggregate(max_difficulty=Max('challenge__difficulty'))['max_difficulty']
        max_difficulty = 1 if max_difficulty is None else max_difficulty

        used_challenges_ids = TeamTowerChallenge.objects.filter(team=team, outcome=TeamTowerChallenge.CONFIRMED)\
            .exclude(challenge__isnull=True).values_list('challenge_id', flat=True)
        used_challenges_ids = list(used_challenges_ids)
        challenge = Challenge.objects.exclude(pk__in=used_challenges_ids)\
            .filter(tower=self, difficulty__gte=max_difficulty).order_by("difficulty").first()

        if challenge:
            return challenge

        # then, use generic challenges
        generic_challenge_filter = dict(team=team, tower__isnull=True, outcome=TeamTowerChallenge.CONFIRMED)
        max_difficulty = TeamTowerChallenge.objects.filter(**generic_challenge_filter)\
            .aggregate(max_difficulty=Max('challenge__difficulty'))['max_difficulty']
        max_difficulty = 1 if max_difficulty is None else max_difficulty

        challenge = Challenge.objects.exclude(pk__in=used_challenges_ids)\
            .filter(difficulty__gte=max_difficulty, tower__isnull=True).order_by("difficulty").first()

        if challenge:
            return challenge

        # TODO: out of challenges, what now?
        # Returning toughest challenge on repeat for now
        return Challenge.objects.filter(tower__isnull=True).order_by("-difficulty").first()

    def tower_control(self, category):
        try:
            return TeamTowerOwnership.objects.get(timestamp_end__isnull=True, tower=self, team__category=category).team
        except TeamTowerOwnership.DoesNotExist:
            return None

    def team_pending(self, team):
        return TeamTowerChallenge.objects.filter(team=team, tower=self, outcome=TeamTowerChallenge.PENDING).exists()

    def team_in_cooloff(self, team):
        ttc = TeamTowerChallenge.objects.filter(team=team, tower=self).order_by("-timestamp_submitted").first()
        if ttc and ttc.outcome == TeamTowerChallenge.REJECTED and (datetime.now(timezone.utc) - ttc.timestamp_verified).seconds < (60 * 5):
            return True

    def save(self, *args, **kwargs):
        if self.id is None and self.autocreate_zone:
            p = self.location
            p.transform(3857)
            circle = p.buffer(100)
            circle.transform(4326)

            self.zone = Zone.objects.create(
                name=f"{self.name} - zone",
                color="#000000",
                shape=circle,
                scoring_type=Zone.SCORE_LIN
            )

        super(Tower, self).save(*args, **kwargs)
        if self.__is_active != self.is_active and self.is_active is False:
            self.unassign()


class Team(models.Model):
    EXPLORATORI = 1
    TEMERARI = 2
    SENIORI = 3
    CATEGORY_CHOICES = [
        (EXPLORATORI, "eXplo"),
        (TEMERARI, "Temerari"),
        (SENIORI, "Seniori")
    ]

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=8, unique=True)
    category = models.PositiveSmallIntegerField(choices=CATEGORY_CHOICES)
    color = ColorField()
    description = models.TextField(null=True, blank=True)

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


class Challenge(models.Model):
    text = models.TextField(null=False, blank=False)
    tower = models.ForeignKey(Tower, null=True, blank=True, on_delete=models.CASCADE)
    difficulty = models.PositiveSmallIntegerField(default=1)

    def __str__(self):
        if self.tower:
            return "(Turn {}) {}".format(self.tower, self.text)
        return self.text


class TeamTowerChallenge(models.Model):
    PENDING = 0
    CONFIRMED = 1
    REJECTED = 2

    OUTCOME_CHOICES = [
        (PENDING, "In asteptare"),
        (CONFIRMED, "Confirmat"),
        (REJECTED, "Respins")
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    tower = models.ForeignKey(Tower, on_delete=models.CASCADE)
    challenge = models.ForeignKey(Challenge, on_delete=models.CASCADE, null=True, blank=True)
    timestamp_submitted = models.DateTimeField(auto_now_add=True)
    timestamp_verified = models.DateTimeField(null=True, blank=True)
    outcome = models.PositiveSmallIntegerField(choices=OUTCOME_CHOICES, default=PENDING)
    checked_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    response_text = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to="photos", null=True, blank=True)

    class Meta:
        ordering = ["-timestamp_submitted"]

    def __init__(self, *args, **kwargs):
        super(TeamTowerChallenge, self).__init__(*args, **kwargs)
        self.__original_outcome = self.outcome

    def save(self, *args, **kwargs):
        super(TeamTowerChallenge, self).save(*args, **kwargs)
        #   if the team completed the challenge
        if self.__original_outcome != self.outcome:
            if self.outcome == TeamTowerChallenge.CONFIRMED:
                self.__original_outcome = self.outcome
                self.timestamp_verified = datetime.now(timezone.utc)
                self.tower.assign_to_team(self.team, self.challenge)
                self.save()
            elif self.outcome == TeamTowerChallenge.REJECTED:
                self.__original_outcome = self.outcome
                self.timestamp_verified = datetime.now(timezone.utc)
                self.save()


class TeamZoneOwnership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE)
    timestamp_start = models.DateTimeField(auto_now_add=True)
    timestamp_end = models.DateTimeField(null=True, blank=True)

    def get_score(self, when=None):
        ref_time = self.timestamp_end or datetime.now(timezone.utc)
        score_time = (ref_time - self.timestamp_start).seconds
        return self.zone.get_score(seconds=score_time)

    def __str__(self):
        data = (self.team, self.get_score(), self.zone)
        if self.timestamp_end:
            return "{} made {} points from zone {}".format(*data)
        return "{} is making {} points from zone {}".format(*data)


class TeamTowerOwnership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    tower = models.ForeignKey(Tower, on_delete=models.CASCADE)
    timestamp_start = models.DateTimeField(auto_now_add=True)
    timestamp_end = models.DateTimeField(null=True, blank=True)

    def __init__(self, *args, **kwargs):
        super(TeamTowerOwnership, self).__init__(*args, **kwargs)
        self.__timestamp_end = self.timestamp_end

    def get_ownership_time(self):
        if self.timestamp_end:
            return (self.timestamp_end - self.timestamp_start).seconds
        return (datetime.now(timezone.utc) - self.timestamp_start).seconds

    def __str__(self):
        data = (self.team, self.tower, self.get_ownership_time())
        if self.timestamp_end:
            return "{} owned tower {} for {}s".format(*data)
        return "{} owns tower {} for {}s".format(*data)

    def save(self, *args, **kwargs):
        super(TeamTowerOwnership, self).save(*args, **kwargs)
        if self.__timestamp_end != self.timestamp_end and self.timestamp_end is not None:
            pass
