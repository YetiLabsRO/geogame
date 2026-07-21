import math
from datetime import datetime, timedelta, timezone

from colorfield.fields import ColorField
from django.conf import settings
from django.contrib.gis.db import models
from django.db import transaction
from django.db.models import Count, F, Max, Value
from django.db.models.functions import Greatest

from organize.models import (
    FAIL_RESET_ANY_ATTEMPT_ELSEWHERE,
    FAIL_RESET_ANY_SUCCESS_ELSEWHERE,
    Team,
    TeamGroup,
)


def _now():
    return datetime.now(timezone.utc)


# Challenge role-requirement modes (team-roles-as-mechanics).
ROLE_REQUIREMENT_NONE = 'NONE'
ROLE_REQUIREMENT_ALL = 'ALL'
ROLE_REQUIREMENT_ANY = 'ANY'
ROLE_REQUIREMENT_CHOICES = [
    (ROLE_REQUIREMENT_NONE, 'No role requirement'),
    (ROLE_REQUIREMENT_ALL, 'One holder for each required role'),
    (ROLE_REQUIREMENT_ANY, 'At least one required role held'),
]


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

    def zone_control(self, group: TeamGroup):
        teams = self.teamzoneownership_set.filter(team__group=group, timestamp_end__isnull=True).values_list('team', flat=True)
        # return Team.objects.filter(pk__in=teams)
        return teams

    def assign_to_team(self, team, handover_time=None):
        if not handover_time:
            handover_time = datetime.now(timezone.utc)
        try:
            current_ownership = TeamZoneOwnership.objects.get(zone=self, timestamp_end__isnull=True, team__group=team.group)
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
    order = models.PositiveIntegerField(null=True, blank=True, help_text="if the game requires any tower order, use this to order towers")

    def __init__(self, *args, **kwargs):
        super(Tower, self).__init__(*args, **kwargs)
        self.__is_active = self.is_active

    def __str__(self):
        return self.name

    def unassign(self):
        from game import events

        handover_time = datetime.now(timezone.utc)
        ownerships = TeamTowerOwnership.objects.filter(tower=self, timestamp_end__isnull=True)
        # Realtime: remember whose map/scoreboard this release affects.
        affected_team_ids = set(ownerships.values_list('team_id', flat=True))
        ownerships.update(timestamp_end=handover_time)

        zone_tower_count = Tower.objects.filter(zone=self.zone, is_active=True).count()
        if zone_tower_count == 0:
            ownerships = TeamZoneOwnership.objects.filter(zone=self.zone, timestamp_end__isnull=True)
            for ownership in ownerships:
                ownership.timestamp_end = handover_time
                ownership.save()
                ownership.team.update_score(ownership.get_score())
                affected_team_ids.add(ownership.team_id)

        elif zone_tower_count > 0:
            #   recalculeaza ownership pentru situatia cu noul turn
            #   get current zone owners
            #   for each team type (separate controls) of every Game that
            #   reaches this zone through its collections
            for group in TeamGroup.objects.filter(game__collections__zones=self.zone).distinct():
                current_zone_control_teams = self.zone.zone_control(group=group)
                #   recalculate maximum number of towers owned in zone
                team_stats = TeamTowerOwnership.objects.filter(
                    tower__zone=self.zone,
                    tower__is_active=True,
                    timestamp_end__isnull=True,
                    team__group=group).values('team').annotate(tower_count=Count('tower'))

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
                    affected_team_ids.add(zone_ownership.team_id)

                #   add new zone owners
                to_add = list(set(new_team_ids) - set(current_zone_control_teams))
                for team_id in to_add:
                    TeamZoneOwnership.objects.create(zone=self.zone, team_id=team_id, timestamp_start=handover_time)
                    affected_team_ids.add(team_id)

        # Realtime: broadcast the release + recolor to every Session whose
        # teams were touched by this deactivation (a repository tower can
        # be live in several Sessions at once).
        for session in self._sessions_for_teams(affected_team_ids):
            events.emit_tower_ownership_changed(session, self, team=None, kind='released')
            if self.zone_id:
                events.emit_zone_control_changed(session, self.zone)
            events.emit_scoreboard_update(session)

    @staticmethod
    def _sessions_for_teams(team_ids):
        from organize.models import Session
        if not team_ids:
            return Session.objects.none()
        return Session.objects.filter(teams__id__in=team_ids).distinct()

    def assign_to_team(self, team, challenge=None, no_bonus=False):
        from game import events

        # Realtime: a same-group open ownership held by ANOTHER team means
        # this capture is a steal; otherwise it is a (re)conquest. Snapshot
        # zone control before the recompute to detect a control flip.
        was_steal = TeamTowerOwnership.objects.filter(
            tower=self, timestamp_end__isnull=True, team__group=team.group,
        ).exclude(team=team).exists()
        zone_control_before = (
            set(self.zone.zone_control(group=team.group))
            if (self.zone_id and team.group_id) else set()
        )
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
                .get(tower=self, timestamp_end__isnull=True, team__group=team.group)
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
            current_zone_control_teams = self.zone.zone_control(group=team.group)
            #   recalculate maximum number of towers owned in zone
            team_stats = TeamTowerOwnership.objects\
                .filter(tower__zone=self.zone, tower__is_active=True, timestamp_end__isnull=True,
                        team__group=team.group)\
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

        # Realtime: broadcast the capture (and any zone-control flip) to
        # the Session group, then a fresh scoreboard snapshot. Push
        # notifications for steal/conquer hang off the same emit (see
        # game/events.py); everything degrades to a no-op without a
        # channel layer.
        session = team.session
        events.emit_tower_ownership_changed(
            session, self, team=team, kind='stolen' if was_steal else 'conquered',
        )
        if self.zone_id and team.group_id:
            zone_control_after = set(self.zone.zone_control(group=team.group))
            if zone_control_after != zone_control_before:
                events.emit_zone_control_changed(session, self.zone)
        events.emit_scoreboard_update(session)

    def _difficulty_rollback(self, team):
        """Phase 10: how many difficulty buckets to drop after failures.

        When `fail_difficulty_rollback` is on and the team has outstanding
        consecutive fails on this tower, the next challenge is drawn from
        the next-lower difficulty bucket.
        """
        if not team.session.effective('fail_difficulty_rollback'):
            return 0
        counter = TeamTowerFailCounter.objects.filter(team=team, tower=self).first()
        if counter and counter.consecutive_fails > 0:
            return 1
        return 0

    def get_next_challenge(self, team):
        rollback = self._difficulty_rollback(team)

        #   first, use tower-related challenges
        max_difficulty = TeamTowerChallenge.objects.filter(team=team, tower=self, outcome=TeamTowerChallenge.CONFIRMED)\
            .aggregate(max_difficulty=Max('challenge__difficulty'))['max_difficulty']
        max_difficulty = 1 if max_difficulty is None else max_difficulty
        floor = max(1, max_difficulty - rollback)

        used_challenges_ids = TeamTowerChallenge.objects.filter(team=team, outcome=TeamTowerChallenge.CONFIRMED)\
            .exclude(challenge__isnull=True).values_list('challenge_id', flat=True)
        used_challenges_ids = list(used_challenges_ids)
        challenge = Challenge.objects.exclude(pk__in=used_challenges_ids)\
            .filter(tower=self, difficulty__gte=floor).order_by("difficulty").first()

        if challenge:
            return challenge

        # then, use generic challenges
        generic_challenge_filter = dict(team=team, tower__isnull=True, outcome=TeamTowerChallenge.CONFIRMED)
        max_difficulty = TeamTowerChallenge.objects.filter(**generic_challenge_filter)\
            .aggregate(max_difficulty=Max('challenge__difficulty'))['max_difficulty']
        max_difficulty = 1 if max_difficulty is None else max_difficulty
        floor = max(1, max_difficulty - rollback)

        challenge = Challenge.objects.exclude(pk__in=used_challenges_ids)\
            .filter(difficulty__gte=floor, tower__isnull=True).order_by("difficulty").first()

        if challenge:
            return challenge

        # TODO: out of challenges, what now?
        # Returning toughest challenge on repeat for now
        return Challenge.objects.filter(tower__isnull=True).order_by("-difficulty").first()

    def tower_control(self, group: TeamGroup):
        try:
            return TeamTowerOwnership.objects.get(timestamp_end__isnull=True, tower=self, team__group=group).team
        except TeamTowerOwnership.DoesNotExist:
            return None

    def team_pending(self, team):
        return TeamTowerChallenge.objects.filter(team=team, tower=self, outcome=TeamTowerChallenge.PENDING).exists()

    def team_in_cooloff(self, team):
        now = _now()
        # An explicit failure lockout blocks the team regardless of cooloff.
        counter = TeamTowerFailCounter.objects.filter(team=team, tower=self).first()
        if counter and counter.locked_until and counter.locked_until > now:
            return True

        ttc = TeamTowerChallenge.objects.filter(team=team, tower=self).order_by("-timestamp_submitted").first()
        if not (ttc and ttc.outcome == TeamTowerChallenge.REJECTED and ttc.timestamp_verified):
            return False

        # Base cooloff, scaled by consecutive fails on this tower (Phase 10).
        # The game context comes from the team's session — a repository
        # tower has no single owning Game anymore.
        scaling = team.session.effective('fail_cooloff_scaling')
        fails = counter.consecutive_fails if counter else 0
        cooloff_seconds = team.session.game.cooloff_minutes * 60 * (scaling ** fails)
        elapsed = (now - ttc.timestamp_verified).total_seconds()
        return elapsed < cooloff_seconds

    def save(self, *args, **kwargs):
        autocreated_zone = None
        if self.zone is None and self.autocreate_zone:
            p = self.location
            p.transform(3857)
            circle = p.buffer(100)
            circle.transform(4326)

            self.zone = autocreated_zone = Zone.objects.create(
                name=f"{self.name} - zone",
                color="#000000",
                shape=circle,
                scoring_type=Zone.SCORE_LIN
            )

        super(Tower, self).save(*args, **kwargs)
        if autocreated_zone is not None:
            # Keep the autocreated zone reachable wherever the tower is:
            # add it to every collection the tower already belongs to.
            for collection in self.collections.all():
                collection.zones.add(autocreated_zone)
        if self.__is_active != self.is_active and self.is_active is False:
            self.unassign()


class Collection(models.Model):
    """A named, reusable grouping of repository Towers and Zones.

    Collections are the "maps" a Game references: geometry lives in the
    repository (Tower / Zone rows without a single-Game owner) and is
    composed into Collections, which Games link through
    `Game.collections`. A Tower or Zone may belong to any number of
    Collections; removing it from a Collection never deletes the row.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='collections_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    towers = models.ManyToManyField(Tower, related_name='collections', blank=True)
    zones = models.ManyToManyField(Zone, related_name='collections', blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Challenge(models.Model):
    # game is nullable at the column level through T3.1 so the data
    # migration can backfill; T3.2 tightens to NOT NULL once every row
    # is attached to a Game.
    game = models.ForeignKey(
        "organize.Game",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='challenges',
    )
    text = models.TextField(null=False, blank=False)
    tower = models.ForeignKey(Tower, null=True, blank=True, on_delete=models.CASCADE)
    difficulty = models.PositiveSmallIntegerField(default=1)

    # --- team-roles-as-mechanics: opt-in role gating. Defaults (NONE /
    # empty / False) preserve pre-change behavior exactly. ---
    role_requirement_mode = models.CharField(
        max_length=8,
        choices=ROLE_REQUIREMENT_CHOICES,
        default=ROLE_REQUIREMENT_NONE,
    )
    required_roles = models.ManyToManyField(
        'organize.GameRole', blank=True, related_name='required_by_challenges',
    )
    # Creator intent that required-role holders must also be physically
    # present. The presence test itself is the `presence-rules`
    # capability; until that ships, assignment alone suffices.
    require_holders_present = models.BooleanField(default=False)

    def __str__(self):
        if self.tower:
            return "(Turn {}) {}".format(self.tower, self.text)
        return self.text

    def team_satisfies_roles(self, team):
        """Evaluate this challenge's role requirement for `team`.

        Returns `(ok, missing_role_slugs)`. Counts the DISTINCT roles
        covered by the team's active role holders — never member
        head-count: one member holding two required roles satisfies an
        ALL requirement over those two roles alone; many members holding
        none fail.

        - NONE → always `(True, [])`.
        - ANY  → ok when at least one required role is covered; on
          failure every required slug is reported missing.
        - ALL  → ok only when every required role is covered; the
          uncovered slugs are reported missing.
        """
        if self.role_requirement_mode == ROLE_REQUIREMENT_NONE:
            return True, []
        required = list(self.required_roles.all())
        if not required:
            return True, []
        held = team.active_role_slugs()
        missing = [role.slug for role in required if role.slug not in held]
        if self.role_requirement_mode == ROLE_REQUIREMENT_ANY:
            covered = len(missing) < len(required)
            return covered, ([] if covered else missing)
        return not missing, missing


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
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submitted_challenges',
    )
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='checked_challenges',
    )
    response_text = models.TextField(null=True, blank=True)
    photo = models.ImageField(upload_to="photos", null=True, blank=True)

    class Meta:
        ordering = ["-timestamp_submitted"]

    def __init__(self, *args, **kwargs):
        super(TeamTowerChallenge, self).__init__(*args, **kwargs)
        self.__original_outcome = self.outcome

    def save(self, *args, **kwargs):
        is_insert = self._state.adding
        super(TeamTowerChallenge, self).save(*args, **kwargs)
        if is_insert:
            self._on_submission_created()
        #   if the team completed the challenge
        if self.__original_outcome != self.outcome:
            if self.outcome == TeamTowerChallenge.CONFIRMED:
                self.__original_outcome = self.outcome
                self.timestamp_verified = datetime.now(timezone.utc)
                self.tower.assign_to_team(self.team, self.challenge)
                self._reset_fail_counters_on_confirm()
                self.save()
            elif self.outcome == TeamTowerChallenge.REJECTED:
                self.__original_outcome = self.outcome
                self.timestamp_verified = datetime.now(timezone.utc)
                self._apply_failure_consequences()
                self.save()

    # --- Phase 10: challenge-failure counter maintenance -------------------

    def _on_submission_created(self):
        """Failure-counter resets that key off a brand-new submission."""
        mode = self.team.session.effective('fail_counter_reset')
        if mode == FAIL_RESET_ANY_ATTEMPT_ELSEWHERE:
            self._reset_other_tower_counters()
        # RFID auto-confirm inserts an already-CONFIRMED row, so the
        # PENDING->CONFIRMED transition never fires for it.
        if self.outcome == TeamTowerChallenge.CONFIRMED:
            self._reset_fail_counters_on_confirm()

    def _reset_other_tower_counters(self):
        TeamTowerFailCounter.objects.filter(team=self.team).exclude(tower=self.tower).update(
            consecutive_fails=0, locked_until=None,
        )

    def _reset_fail_counters_on_confirm(self):
        mode = self.team.session.effective('fail_counter_reset')
        # A success on this tower always clears this tower's counter.
        TeamTowerFailCounter.objects.filter(team=self.team, tower=self.tower).update(
            consecutive_fails=0, locked_until=None,
        )
        if mode in (FAIL_RESET_ANY_SUCCESS_ELSEWHERE, FAIL_RESET_ANY_ATTEMPT_ELSEWHERE):
            self._reset_other_tower_counters()

    def _apply_failure_consequences(self):
        session = self.team.session
        now = datetime.now(timezone.utc)
        counter, _ = TeamTowerFailCounter.objects.get_or_create(team=self.team, tower=self.tower)
        counter.consecutive_fails = (counter.consecutive_fails or 0) + 1
        counter.last_failed_at = now
        lockout = session.effective('fail_tower_lockout_minutes')
        if lockout:
            counter.locked_until = now + timedelta(minutes=lockout)
        counter.save()

        penalty = session.effective('fail_point_penalty')
        if penalty:
            # Atomic subtract, clamped to >= 0.
            Team.objects.filter(pk=self.team_id).update(
                score=Greatest(F('score') - penalty, Value(0)),
            )
            # Realtime: the queryset update bypasses Team.update_score,
            # so broadcast the scoreboard change explicitly.
            from game import events
            events.emit_scoreboard_update(session)


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


class PauseWindow(models.Model):
    """A day cut-off pause on a Session (Phase 10, §20).

    A Session is "paused" while it has an open window (`ended_at IS NULL`).
    On pause the session's active tower/zone ownerships are closed at
    `started_at` and snapshotted here so they can be reopened on resume.
    """

    session = models.ForeignKey(
        'organize.Session', on_delete=models.CASCADE, related_name='pause_windows',
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    restore_on_resume = models.BooleanField(default=True)
    # Snapshots of ownerships open at pause time: lists of [team_id, tower_id]
    # / [team_id, zone_id]. Empty when restore is disabled.
    tower_ownerships = models.JSONField(default=list, blank=True)
    zone_ownerships = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        state = 'open' if self.ended_at is None else 'closed'
        return f'PauseWindow({self.session}, {state})'

    @classmethod
    def open_for(cls, session):
        if session is None:
            return None
        return cls.objects.filter(
            session=session, ended_at__isnull=True,
        ).order_by('-started_at').first()

    @classmethod
    def is_paused(cls, session):
        return cls.open_for(session) is not None

    @classmethod
    def pause_session(cls, session, when=None):
        """Open a PauseWindow, closing + snapshotting active ownerships.

        Returns the new window, or None if the session is already paused.
        """
        if cls.open_for(session) is not None:
            return None
        when = when or _now()
        freeze = session.effective('pause_freezes_floating_score')
        restore = session.effective('pause_restores_ownerships_on_resume')
        team_ids = list(session.teams.values_list('id', flat=True))

        with transaction.atomic():
            tower_pairs = list(
                TeamTowerOwnership.objects
                .filter(team_id__in=team_ids, timestamp_end__isnull=True)
                .values_list('team_id', 'tower_id')
            )
            zone_owns = list(
                TeamZoneOwnership.objects
                .filter(team_id__in=team_ids, timestamp_end__isnull=True)
                .select_related('team', 'zone')
            )
            zone_pairs = [(zo.team_id, zo.zone_id) for zo in zone_owns]

            TeamTowerOwnership.objects.filter(
                team_id__in=team_ids, timestamp_end__isnull=True,
            ).update(timestamp_end=when)

            for zo in zone_owns:
                zo.timestamp_end = when
                zo.save()
                if freeze:
                    # Lock the floating earned up to the pause into the score.
                    zo.team.update_score(zo.get_score())

            window = cls.objects.create(
                session=session,
                started_at=when,
                restore_on_resume=restore,
                tower_ownerships=[list(p) for p in tower_pairs] if restore else [],
                zone_ownerships=[list(p) for p in zone_pairs] if restore else [],
            )
            # Keep the explicit lifecycle state in lockstep with the
            # open-window predicate (session-lifecycle invariant).
            session.state = session.PAUSED
            session.save(update_fields=['state'])
            return window

    @classmethod
    def resume_session(cls, session, when=None):
        """Close the open window and (optionally) reopen snapshotted ownerships."""
        window = cls.open_for(session)
        if window is None:
            return None
        when = when or _now()
        with transaction.atomic():
            window.ended_at = when
            window.save(update_fields=['ended_at'])
            if window.restore_on_resume:
                window._reopen_ownerships(when)
            # Lockstep with the lifecycle state (see pause_session).
            session.state = session.RUNNING
            session.save(update_fields=['state'])
        return window

    def _reopen_ownerships(self, when):
        for team_id, tower_id in self.tower_ownerships:
            self._reopen_one(TeamTowerOwnership, team_id, 'tower_id', tower_id, when)
        for team_id, zone_id in self.zone_ownerships:
            self._reopen_one(TeamZoneOwnership, team_id, 'zone_id', zone_id, when)

    @staticmethod
    def _reopen_one(model, team_id, target_field, target_id, when):
        # Reconcile with captures made while paused: don't hand a tower/zone
        # back to the pre-pause owner if the same group already holds it.
        group_id = Team.objects.filter(pk=team_id).values_list('group_id', flat=True).first()
        clash = model.objects.filter(
            timestamp_end__isnull=True, team__group_id=group_id,
            **{target_field: target_id},
        ).exists()
        if clash:
            return
        row = model.objects.create(team_id=team_id, **{target_field: target_id})
        # timestamp_start is auto_now_add; pin it to the resume instant.
        model.objects.filter(pk=row.pk).update(timestamp_start=when)


class TeamTowerFailCounter(models.Model):
    """Consecutive challenge-failure state for a (team, tower) pair (§21)."""

    team = models.ForeignKey('organize.Team', on_delete=models.CASCADE)
    tower = models.ForeignKey(Tower, on_delete=models.CASCADE)
    consecutive_fails = models.PositiveIntegerField(default=0)
    last_failed_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = (('team', 'tower'),)

    def __str__(self):
        return f'{self.team} @ {self.tower}: {self.consecutive_fails} fails'

    def is_locked(self, now=None):
        if self.locked_until is None:
            return False
        return self.locked_until > (now or _now())
