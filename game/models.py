import math
from datetime import datetime, timedelta, timezone

from colorfield.fields import ColorField
from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Max, Value
from django.db.models.functions import Greatest
from django.db.models.signals import m2m_changed, pre_delete

from organize.models import (
    CHALLENGE_VIS_VISIBLE_ANYWHERE,
    CHALLENGE_VISIBILITY_CHOICES,
    CONQUEST_RULE_ALL,
    CONQUEST_RULE_ANY,
    CONQUEST_RULE_CHOICES,
    CONQUEST_RULE_MAJORITY,
    DISCOVERABILITY_CHOICES,
    DISCOVERABILITY_VISIBLE,
    FAIL_RESET_ANY_ATTEMPT_ELSEWHERE,
    FAIL_RESET_ANY_SUCCESS_ELSEWHERE,
    TIME_UNIT_MINUTE,
    TIME_UNIT_SECONDS,
    Team,
    TeamGroup,
)


def _now():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Effective-value helpers (zone-conquest-and-scoring-config)
# ---------------------------------------------------------------------------


def effective_conquest_rule(zone, session=None, game=None):
    """Most-specific conquest rule: Zone override > Session override > Game default.

    `session` may be None when the recompute has no Session context for a
    TeamGroup (e.g. no team currently holds a tower); pass the group's
    `game` so the Game default still applies.
    """
    if zone.conquest_rule:
        return zone.conquest_rule
    if session is not None:
        return session.effective('zone_conquest_rule')
    if game is not None:
        return game.zone_conquest_rule
    return CONQUEST_RULE_MAJORITY


def effective_proximity(tower, game):
    """Capture radius in meters: Tower override when set, else the Game default."""
    if tower.proximity_meters is not None:
        return tower.proximity_meters
    return game.proximity_meters


def effective_time_unit(session):
    """Scoring time unit: Session override when set, else the Game default."""
    return session.effective('score_time_unit')


# ---------------------------------------------------------------------------
# Effective-value helpers (tower-visibility). Resolution order for each
# axis: per-tower/per-zone override → Session override → Game default.
# ---------------------------------------------------------------------------


def _effective_visibility(override, session, game, field, fallback):
    if override is not None and override != '':
        return override
    if session is not None:
        return session.effective(field)
    if game is not None:
        return getattr(game, field)
    return fallback


def effective_discoverability(tower, session=None, game=None):
    """Tower discoverability axis: Tower override > Session > Game default."""
    return _effective_visibility(
        tower.discoverability, session, game,
        'tower_discoverability_default', DISCOVERABILITY_VISIBLE,
    )


def effective_challenge_visibility(tower, session=None, game=None):
    """Challenge visibility axis: Tower override > Session > Game default."""
    return _effective_visibility(
        tower.challenge_visibility, session, game,
        'challenge_visibility_default', CHALLENGE_VIS_VISIBLE_ANYWHERE,
    )


def effective_fog_reveal_pct(zone, session=None, game=None):
    """Fog-reveal coverage threshold: Zone override > Session > Game default."""
    return _effective_visibility(
        zone.fog_reveal_coverage_pct, session, game,
        'fog_reveal_coverage_pct_default', 60.0,
    )


# Challenge role-requirement modes (team-roles-as-mechanics).
ROLE_REQUIREMENT_NONE = 'NONE'
ROLE_REQUIREMENT_ALL = 'ALL'
ROLE_REQUIREMENT_ANY = 'ANY'
ROLE_REQUIREMENT_CHOICES = [
    (ROLE_REQUIREMENT_NONE, 'No role requirement'),
    (ROLE_REQUIREMENT_ALL, 'One holder for each required role'),
    (ROLE_REQUIREMENT_ANY, 'At least one required role held'),
]


# Presence verification methods (presence-rules capability). Geofencing
# (optionally strengthened by a continuous-tracking window) is the
# primary method; a photo of the required people is a deliberately
# weaker fallback (easily AI-edited) that always goes to staff review.
PRESENCE_METHOD_GEOFENCE = 'GEOFENCE'
PRESENCE_METHOD_PHOTO = 'PHOTO'
PRESENCE_METHOD_GEOFENCE_OR_PHOTO = 'GEOFENCE_OR_PHOTO'
PRESENCE_METHOD_CHOICES = [
    (PRESENCE_METHOD_GEOFENCE, 'Geofence (live-location pings)'),
    (PRESENCE_METHOD_PHOTO, 'Photo of the required people (staff-reviewed)'),
    (PRESENCE_METHOD_GEOFENCE_OR_PHOTO, 'Geofence, with photo fallback'),
]

# Presence evaluation reason codes (presence-rules capability).
PRESENCE_REASON_INSUFFICIENT_MEMBERS = 'INSUFFICIENT_MEMBERS_PRESENT'
PRESENCE_REASON_MEMBER_OUTSIDE = 'MEMBER_OUTSIDE_GEOFENCE'
PRESENCE_REASON_WINDOW_NOT_SATISFIED = 'PRESENCE_WINDOW_NOT_SATISFIED'
PRESENCE_REASON_PHOTO_REVIEW = 'PHOTO_REVIEW_REQUIRED'


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

    # Per-zone conquest-rule override (zone-conquest-and-scoring-config).
    # NULL inherits the Session override / Game default.
    conquest_rule = models.CharField(
        max_length=16, choices=CONQUEST_RULE_CHOICES, null=True, blank=True,
    )

    # Per-zone fog-of-war reveal threshold override, percent of zone
    # area a team must cover to reveal the zone's FOG_REVEAL towers
    # (tower-visibility). NULL inherits the Session override / Game default.
    fog_reveal_coverage_pct = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.name

    def effective_fog_reveal_pct(self, session=None, game=None):
        """Effective fog threshold: Zone override > Session > Game default."""
        return effective_fog_reveal_pct(self, session=session, game=game)

    def clean(self):
        """At-least-one-tower invariant (tower-zone-topology).

        Enforced at the application layer: an existing Zone may not be
        saved while it has zero member towers. Brand-new zones (no pk)
        are exempt — membership can only be linked after the row exists
        (the autocreate-circle flow links the founding tower right away).
        """
        super().clean()
        if self.pk and not self.towers.exists():
            raise ValidationError(
                'A zone must retain at least one member tower. '
                'Link a tower before saving this zone.',
            )

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

    def _get_score_exp(self, units):
        return math.pow(units, 2) / 140 + 10

    def _get_score_exp_bonus(self, units):
        return min(math.pow(units, 2) / 25 + 50, 200)

    def _get_score_log(self, units):
        return 30 * math.log(units) + pow(units, 2) / 10000

    def _get_score_prop(self, units):
        return units

    def get_score(self, seconds, time_unit=TIME_UNIT_MINUTE):
        """Floating points for an ownership window of `seconds` seconds.

        The window duration is first converted into `units` of the
        effective scoring time unit (zone-conquest-and-scoring-config);
        the four formula shapes are unchanged, so the MINUTE default
        yields `units == mins` and reproduces historical scores exactly.
        """
        score_functions = {
            Zone.SCORE_EXP: self._get_score_exp,
            Zone.SCORE_LOG: self._get_score_log,
            Zone.SCORE_LIN: self._get_score_prop,
            Zone.SCORE_BONUS: self._get_score_exp_bonus,
        }

        units = seconds / float(TIME_UNIT_SECONDS[time_unit])
        return score_functions[self.scoring_type](units)


class Tower(models.Model):
    CATEGORY_NORMAL = 1
    CATEGORY_RFID = 2
    CATEGORY_CHOICES = [
        (CATEGORY_NORMAL, "Normal"),
        (CATEGORY_RFID, "RFID")
    ]

    name = models.CharField(max_length=255)

    location = models.PointField()
    # Many-to-many zone membership (tower-zone-topology): a tower may
    # belong to several, possibly overlapping, zones. Membership is
    # logical, not spatial — it is never inferred from geometry.
    zones = models.ManyToManyField(Zone, related_name='towers', blank=True)
    category = models.PositiveSmallIntegerField(choices=CATEGORY_CHOICES)
    is_active = models.BooleanField()

    # Per-tower capture-radius override (zone-conquest-and-scoring-config).
    # NULL falls back to the game-wide Game.proximity_meters default.
    proximity_meters = models.PositiveIntegerField(null=True, blank=True)

    # --- tower-visibility: the two independent visibility axes. NULL
    # inherits the Session override / Game default (VISIBLE and
    # VISIBLE_ANYWHERE by default, preserving shipped behavior). ---
    discoverability = models.CharField(
        max_length=16, choices=DISCOVERABILITY_CHOICES, null=True, blank=True,
    )
    challenge_visibility = models.CharField(
        max_length=32, choices=CHALLENGE_VISIBILITY_CHOICES, null=True, blank=True,
    )

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

    def effective_discoverability(self, session=None, game=None):
        """Effective discoverability axis: Tower override > Session > Game."""
        return effective_discoverability(self, session=session, game=game)

    def effective_challenge_visibility(self, session=None, game=None):
        """Effective challenge-visibility axis: Tower override > Session > Game."""
        return effective_challenge_visibility(self, session=session, game=game)

    def unassign(self):
        handover_time = datetime.now(timezone.utc)
        ownerships = TeamTowerOwnership.objects.filter(tower=self, timestamp_end__isnull=True)
        ownerships.update(timestamp_end=handover_time)

        # Recompute control of EVERY zone this tower belongs to — each
        # zone independently (tower-zone-topology).
        self._recompute_zones_control(handover_time)

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
                .get(tower=self, timestamp_end__isnull=True, team__group=team.group)
            ownership.timestamp_end = handover_time
            ownership.save()
        except TeamTowerOwnership.DoesNotExist:
            pass

        TeamTowerOwnership.objects.create(tower=self, team=team, timestamp_start=handover_time)

        # When towers are reassigned, recalculate zone control across
        # every zone the tower belongs to (tower-zone-topology).
        self._recompute_zones_control(handover_time, capturing_team=team)

    # --- Zone-control recompute (implements the `Zone conquest rule`
    # requirement from zone-conquest-and-scoring-config over the
    # many-to-many topology from tower-zone-topology). -------------------

    def _recompute_zones_control(self, handover_time, capturing_team=None):
        """Recompute conquest-rule control of every zone this tower belongs to.

        Each zone is evaluated independently, per TeamGroup, over the
        zone's currently-active member towers (reverse many-to-many).
        A change of controller closes the prior owner's TeamZoneOwnership
        (finalizing its floating score into the locked team score) and
        opens a new one for the new controller, if any.
        """
        for zone in self.zones.all():
            active_tower_ids = list(
                zone.towers.filter(is_active=True).values_list('pk', flat=True),
            )
            if not active_tower_ids:
                # No active member tower left: close every open ownership
                # for the zone (legacy deactivation behavior).
                open_ownerships = TeamZoneOwnership.objects.filter(
                    zone=zone, timestamp_end__isnull=True,
                ).select_related('team__session__game', 'zone')
                for zone_ownership in open_ownerships:
                    zone_ownership.timestamp_end = handover_time
                    zone_ownership.save()
                    zone_ownership.team.update_score(zone_ownership.get_score())
                continue

            # One control computation per TeamGroup of every Game that
            # reaches this zone through its collections.
            for group in TeamGroup.objects.filter(game__collections__zones=zone).distinct():
                self._recompute_zone_group_control(
                    zone, group, active_tower_ids, handover_time, capturing_team,
                )

    def _resolve_rule_session(self, group, active_tower_ids, capturing_team):
        """Best Session context for resolving a zone's effective rule.

        The capturing team's Session when the group is its own; otherwise
        the Session of any team in the group currently holding a member
        tower; otherwise None (the caller falls back to the group's Game
        default).
        """
        if capturing_team is not None and capturing_team.group_id == group.id:
            return capturing_team.session
        holder = (
            TeamTowerOwnership.objects
            .filter(
                tower_id__in=active_tower_ids,
                tower__is_active=True,
                timestamp_end__isnull=True,
                team__group=group,
            )
            .select_related('team__session')
            .first()
        )
        return holder.team.session if holder else None

    def _recompute_zone_group_control(self, zone, group, active_tower_ids,
                                      handover_time, capturing_team):
        session = self._resolve_rule_session(group, active_tower_ids, capturing_team)
        rule = effective_conquest_rule(zone, session=session, game=group.game)

        current_zone_control_teams = set(zone.zone_control(group=group))

        open_ownerships = TeamTowerOwnership.objects.filter(
            tower_id__in=active_tower_ids,
            tower__is_active=True,
            timestamp_end__isnull=True,
            team__group=group,
        )

        if rule == CONQUEST_RULE_ALL:
            # Only a team holding EVERY active member tower controls the zone.
            team_stats = open_ownerships.values('team').annotate(
                tower_count=Count('tower', distinct=True),
            )
            new_team_ids = [
                stat['team'] for stat in team_stats
                if stat['tower_count'] == len(active_tower_ids)
            ]
        elif rule == CONQUEST_RULE_ANY:
            # Any holder is eligible; most towers wins, ties broken by
            # the most recent capture (deterministic single winner).
            team_stats = list(
                open_ownerships.values('team').annotate(
                    tower_count=Count('tower', distinct=True),
                ),
            )
            if team_stats:
                max_towers = max(stat['tower_count'] for stat in team_stats)
                leaders = [
                    stat['team'] for stat in team_stats
                    if stat['tower_count'] == max_towers
                ]
                if len(leaders) > 1:
                    latest = (
                        open_ownerships
                        .filter(team_id__in=leaders)
                        .order_by('-timestamp_start')
                        .first()
                    )
                    leaders = [latest.team_id]
                new_team_ids = leaders
            else:
                new_team_ids = []
        else:
            # MAJORITY — the pre-change computation retained verbatim:
            # the team(s) holding the most active member towers control
            # the zone (a tie keeps every tied team as a controller).
            team_stats = open_ownerships.values('team').annotate(tower_count=Count('tower'))
            if team_stats.count():
                max_towers = max(stat['tower_count'] for stat in team_stats)
                new_team_ids = [
                    stat['team'] for stat in team_stats
                    if stat['tower_count'] == max_towers
                ]
            else:
                new_team_ids = []

        # Remove old owners that are not in control anymore.
        to_remove = list(current_zone_control_teams - set(new_team_ids))
        to_close = TeamZoneOwnership.objects.filter(
            zone=zone, timestamp_end__isnull=True, team__in=to_remove,
        ).select_related('team__session__game', 'zone')
        for zone_ownership in to_close:
            zone_ownership.timestamp_end = handover_time
            zone_ownership.save()
            zone_ownership.team.update_score(zone_ownership.get_score())

        # Add new zone owners.
        to_add = list(set(new_team_ids) - current_zone_control_teams)
        for team_id in to_add:
            TeamZoneOwnership.objects.create(
                zone=zone, team_id=team_id, timestamp_start=handover_time,
            )

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

    def ensure_autocreated_zone(self):
        """Autocreate-circle-zone hook (tower-zone-topology).

        When `autocreate_zone` is set and the tower belongs to NO zone,
        create a circular Zone around the tower and ADD it to the
        tower's `zones` set — the tower is the new zone's founding
        member, so the at-least-one-tower invariant holds from creation.
        Returns the new Zone, or None when nothing was created.
        """
        if not self.autocreate_zone or self.pk is None or self.zones.exists():
            return None

        p = self.location.clone()
        p.transform(3857)
        circle = p.buffer(100)
        circle.transform(4326)

        zone = Zone.objects.create(
            name=f"{self.name} - zone",
            color="#000000",
            shape=circle,
            scoring_type=Zone.SCORE_LIN,
        )
        self.zones.add(zone)
        # Keep the autocreated zone reachable wherever the tower is:
        # add it to every collection the tower already belongs to.
        for collection in self.collections.all():
            collection.zones.add(zone)
        return zone

    def save(self, *args, **kwargs):
        super(Tower, self).save(*args, **kwargs)
        # M2M membership needs a pk, so the autocreate hook runs after
        # the row exists (the admin re-runs it after its M2M save too).
        self.ensure_autocreated_zone()
        if self.__is_active != self.is_active and self.is_active is False:
            self.unassign()


# ---------------------------------------------------------------------------
# At-least-one-tower invariant guards (tower-zone-topology)
#
# Application-layer enforcement: any membership removal or tower deletion
# that would leave a Zone with zero member towers is rejected with a
# ValidationError. (Minimum cardinality on a many-to-many cannot be a
# simple DB constraint.)
# ---------------------------------------------------------------------------


def _last_member_zone_names(tower, zones):
    """Names of `zones` whose only member tower is `tower`."""
    blocked = []
    for zone in zones:
        member_ids = set(zone.towers.values_list('pk', flat=True))
        if member_ids == {tower.pk}:
            blocked.append(zone.name)
    return blocked


def _guard_zone_membership_removal(sender, instance, action, reverse, pk_set, **kwargs):
    if action not in ('pre_remove', 'pre_clear'):
        return
    if not reverse:
        # instance is a Tower losing zone memberships.
        if action == 'pre_clear':
            zones = list(instance.zones.all())
        else:
            zones = list(Zone.objects.filter(pk__in=pk_set))
        blocked = _last_member_zone_names(instance, zones)
        if blocked:
            raise ValidationError(
                f'Cannot remove tower "{instance.name}" from '
                f'{", ".join(blocked)}: a zone must retain at least one '
                'member tower.',
            )
    else:
        # instance is a Zone losing member towers.
        member_ids = set(instance.towers.values_list('pk', flat=True))
        if not member_ids:
            return
        remaining = member_ids if action == 'pre_clear' else member_ids - set(pk_set)
        if action == 'pre_clear' or not remaining:
            raise ValidationError(
                f'Cannot remove the last member tower(s) of zone '
                f'"{instance.name}": a zone must retain at least one '
                'member tower.',
            )


def _guard_tower_delete(sender, instance, **kwargs):
    blocked = _last_member_zone_names(instance, instance.zones.all())
    if blocked:
        raise ValidationError(
            f'Cannot delete tower "{instance.name}": it is the last member '
            f'tower of {", ".join(blocked)}. Link another tower or delete '
            'the zone first.',
        )


m2m_changed.connect(
    _guard_zone_membership_removal,
    sender=Tower.zones.through,
    dispatch_uid='tower_zone_topology_membership_guard',
)
pre_delete.connect(
    _guard_tower_delete,
    sender=Tower,
    dispatch_uid='tower_zone_topology_tower_delete_guard',
)


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


class PresenceRequirement(models.Model):
    """A named, reusable presence requirement (presence-rules capability).

    Referenced by any number of Challenges through their nullable
    `presence_requirement` FK; NULL there means "no requirement". A
    NULL `geofence_radius_meters` falls back to the tower's effective
    `proximity_meters`; a NULL `window_seconds` falls back to the
    Session's effective `presence_window_seconds` (see
    `game.presence.resolve_presence`).
    """

    name = models.CharField(max_length=255)
    min_members_present = models.PositiveIntegerField(default=1)
    method = models.CharField(
        max_length=32,
        choices=PRESENCE_METHOD_CHOICES,
        default=PRESENCE_METHOD_GEOFENCE,
    )
    geofence_radius_meters = models.PositiveIntegerField(null=True, blank=True)
    window_seconds = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return (
            f'{self.name} (≥{self.min_members_present} present, {self.method})'
        )

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.min_members_present < 1:
            raise ValidationError(
                {'min_members_present': 'At least one member must be required.'},
            )


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

    # presence-rules: NULL means the challenge has no presence
    # requirement (the default — submissions behave exactly as before).
    # Deleting a referenced PresenceRequirement detaches, never deletes
    # the Challenge.
    presence_requirement = models.ForeignKey(
        PresenceRequirement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='challenges',
    )

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


class PresenceCheck(models.Model):
    """Audit record of one presence evaluation (presence-rules capability).

    Written for every presence-gated submission that is stored, so
    staff review and later disputes can see exactly what was verified:
    the resolved requirement, which member ids passed, the method used,
    and whether the continuous-tracking window was satisfied
    (`window_satisfied` is NULL when the window could not be evaluated,
    e.g. live-location was unavailable).
    """

    team_tower_challenge = models.OneToOneField(
        TeamTowerChallenge,
        on_delete=models.CASCADE,
        related_name='presence_check',
    )
    required_count = models.PositiveIntegerField()
    present_count = models.PositiveIntegerField(default=0)
    method = models.CharField(max_length=32, choices=PRESENCE_METHOD_CHOICES)
    # Auth-user ids of the members verified present (JSON list of ints).
    verified_member_ids = models.JSONField(default=list, blank=True)
    window_seconds = models.PositiveIntegerField(default=0)
    window_satisfied = models.BooleanField(null=True, blank=True)
    satisfied = models.BooleanField(default=False)
    reason_code = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        state = 'ok' if self.satisfied else (self.reason_code or 'failed')
        return (
            f'PresenceCheck(ttc={self.team_tower_challenge_id}, '
            f'{self.present_count}/{self.required_count}, {state})'
        )


class TeamZoneOwnership(models.Model):
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE)
    timestamp_start = models.DateTimeField(auto_now_add=True)
    timestamp_end = models.DateTimeField(null=True, blank=True)

    def get_score(self, when=None):
        ref_time = self.timestamp_end or datetime.now(timezone.utc)
        score_time = (ref_time - self.timestamp_start).seconds
        # Accrue in the Session's effective scoring time unit; the
        # MINUTE default reproduces historical scores exactly.
        return self.zone.get_score(
            seconds=score_time,
            time_unit=effective_time_unit(self.team.session),
        )

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
                # team__session__game: get_score resolves the effective
                # scoring time unit through the owning team's Session.
                .select_related('team__session__game', 'zone')
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


class LocationPingQuerySet(models.QuerySet):
    def latest_per_user(self, session):
        """Most recent ping per user in `session`, newest first.

        The live feed's read shape: one row per user, each user's
        latest `recorded_at`. Uses Postgres DISTINCT ON via
        order_by(user, -recorded_at) + distinct(user).
        """
        return (
            self.filter(session=session)
            .order_by('user_id', '-recorded_at')
            .distinct('user_id')
        )


class LocationPing(models.Model):
    """One consented position sample (live-location capability).

    Append-only history: serves live plotting (latest per user) and
    after-game replay/analysis (per-user time series). `recorded_at` is
    the client's sample clock; `received_at` is stamped by the server so
    stale/queued uploads can be reasoned about. `team` is denormalized
    from the submitter's active membership at ingestion time so replay
    grouping survives roster changes.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='location_pings',
    )
    session = models.ForeignKey(
        'organize.Session', on_delete=models.CASCADE, related_name='location_pings',
    )
    team = models.ForeignKey(
        'organize.Team',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='location_pings',
    )
    point = models.PointField()
    accuracy = models.FloatField(null=True, blank=True, help_text='GPS accuracy in meters')
    recorded_at = models.DateTimeField()
    received_at = models.DateTimeField(auto_now_add=True)

    objects = LocationPingQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(
                fields=['session', 'user', 'recorded_at'],
                name='locationping_session_user_ts',
            ),
        ]
        ordering = ['-recorded_at']

    def __str__(self):
        return f'{self.user} @ {self.recorded_at:%H:%M:%S} in {self.session}'


class LocationConsent(models.Model):
    """A player's recorded agreement to a Session's location rules.

    Standing consent = a row with `withdrawn_at IS NULL`. The agreed
    consent text is snapshotted (plus a hash) so audits know exactly
    which version was accepted. Withdrawal keeps the row for audit but
    stops streaming/plotting and purges the user's pings for the
    Session (see the live-location capability).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='location_consents',
    )
    session = models.ForeignKey(
        'organize.Session', on_delete=models.CASCADE, related_name='location_consents',
    )
    agreed_at = models.DateTimeField()
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    consent_text = models.TextField(blank=True, default='')
    consent_text_hash = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        # One consent row per (user, session): re-granting after a
        # withdrawal updates the same row (fresh agreed_at + snapshot).
        unique_together = (('user', 'session'),)

    def __str__(self):
        state = 'withdrawn' if self.withdrawn_at else 'standing'
        return f'LocationConsent({self.user}, {self.session}, {state})'

    @property
    def is_standing(self):
        return self.withdrawn_at is None

    @classmethod
    def standing_for(cls, user, session):
        """The user's standing consent row for `session`, or None."""
        if user is None or not getattr(user, 'is_authenticated', False):
            return None
        return cls.objects.filter(
            user=user, session=session, withdrawn_at__isnull=True,
        ).first()

    @classmethod
    def grant(cls, user, session):
        """Record (or re-grant) consent, snapshotting the effective text."""
        import hashlib
        text = session.effective('location_consent_text') or ''
        consent, _created = cls.objects.update_or_create(
            user=user,
            session=session,
            defaults={
                'agreed_at': _now(),
                'withdrawn_at': None,
                'consent_text': text,
                'consent_text_hash': hashlib.sha256(text.encode()).hexdigest(),
            },
        )
        return consent

    def withdraw(self):
        """Withdraw consent and purge this user's pings for the Session."""
        self.withdrawn_at = _now()
        self.save(update_fields=['withdrawn_at'])
        LocationPing.objects.filter(user=self.user, session=self.session).delete()


class TowerDiscovery(models.Model):
    """One team's discovery of one tower in one Session (discovery-tracking).

    Append-only: created the first time the team reveals the tower and
    NEVER deleted by conquest, loss of ownership, or ownerlessness — "a
    team sees a tower" ⇔ the tower's effective discoverability is
    VISIBLE **or** a TowerDiscovery row exists, fully decoupled from
    ownership. Unique per (session, team, tower) so re-revealing never
    duplicates.
    """

    METHOD_PROXIMITY = 'PROXIMITY'
    METHOD_ZONE_ENTRY = 'ZONE_ENTRY'
    METHOD_ZONE_COVERAGE = 'ZONE_COVERAGE'
    METHOD_ALWAYS_VISIBLE = 'ALWAYS_VISIBLE'
    METHOD_STAFF = 'STAFF'
    METHOD_CHOICES = [
        (METHOD_PROXIMITY, 'Walked within the tower proximity'),
        (METHOD_ZONE_ENTRY, 'Entered the tower zone'),
        (METHOD_ZONE_COVERAGE, 'Covered enough of the tower zone'),
        (METHOD_ALWAYS_VISIBLE, 'Always visible'),
        (METHOD_STAFF, 'Revealed by staff'),
    ]

    session = models.ForeignKey(
        'organize.Session', on_delete=models.CASCADE, related_name='tower_discoveries',
    )
    team = models.ForeignKey(
        'organize.Team', on_delete=models.CASCADE, related_name='tower_discoveries',
    )
    tower = models.ForeignKey(
        Tower, on_delete=models.CASCADE, related_name='discoveries',
    )
    discovered_at = models.DateTimeField(auto_now_add=True)
    discovered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tower_discoveries',
    )
    method = models.CharField(max_length=16, choices=METHOD_CHOICES)

    class Meta:
        unique_together = (('session', 'team', 'tower'),)
        ordering = ['-discovered_at']

    def __str__(self):
        return f'{self.team} discovered {self.tower} ({self.method})'


class TeamZoneCoverage(models.Model):
    """Accumulated visited geometry of one team over one zone (fog-of-war).

    The incremental store behind the ZONE_COVERAGE reveal: each reported
    position is buffered and unioned into `visited`; `coverage_pct` is
    area(visited ∩ zone) / area(zone). `revealed` short-circuits further
    accumulation once the zone's effective threshold has been crossed.
    """

    session = models.ForeignKey(
        'organize.Session', on_delete=models.CASCADE, related_name='zone_coverages',
    )
    team = models.ForeignKey(
        'organize.Team', on_delete=models.CASCADE, related_name='zone_coverages',
    )
    zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, related_name='team_coverages',
    )
    visited = models.GeometryField(null=True, blank=True)
    coverage_pct = models.FloatField(default=0)
    revealed = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (('session', 'team', 'zone'),)

    def __str__(self):
        return f'{self.team} covered {self.coverage_pct:.1f}% of {self.zone}'


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
