import math
import secrets
from datetime import datetime, timedelta, timezone

from colorfield.fields import ColorField
from django.conf import settings
from django.contrib.gis.db import models
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, F, Max, Q, Value
from django.db.models.functions import Greatest
from django.db.models.signals import m2m_changed, pre_delete

from game.challenge_types import (
    CHALLENGE_TYPE_CHOICES,
    REVIEW_MODE_CHOICES,
    TYPE_TEXT,
    get_handler,
)
from organize.models import (
    CONQUEST_RULE_ALL,
    CONQUEST_RULE_ANY,
    CONQUEST_RULE_CHOICES,
    CONQUEST_RULE_MAJORITY,
    FAIL_RESET_ANY_ATTEMPT_ELSEWHERE,
    FAIL_RESET_ANY_SUCCESS_ELSEWHERE,
    MODE_TRAIL,
    TIME_UNIT_MINUTE,
    TIME_UNIT_SECONDS,
    Team,
    TeamGroup,
    effective_mode,
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

    def __str__(self):
        return self.name

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

    initial_bonus = models.PositiveIntegerField(default=0, help_text="Număr inițial de puncte obținute la câștigarea turnului")
    decrease_initial_bonus = models.BooleanField(default=False, help_text="Dacă la fiecare recucerire ulterioară de către aceeași echipă să se înjumătățească numărul inițial de puncte obținute (minimul va fi 1)")

    autocreate_zone = models.BooleanField(default=False, verbose_name="Creează zonă", help_text="Creează o zonă nou, circulară, pentru acest turn")

    rfid_code = models.CharField(max_length=16, unique=True, null=True, blank=True)
    order = models.PositiveIntegerField(null=True, blank=True, help_text="if the game requires any tower order, use this to order towers")

    # field-authoring-mode: GPS accuracy (metres) of the geolocation fix
    # a field curator dropped this tower from. NULL for desk-authored
    # towers — pure capture provenance, never used in gameplay.
    authored_accuracy_m = models.FloatField(
        null=True,
        blank=True,
        help_text='GPS accuracy in metres of the field capture that placed this tower (provenance).',
    )

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

        # Recompute control of EVERY zone this tower belongs to — each
        # zone independently (tower-zone-topology). Collect the zones
        # whose control actually flipped for the realtime recolor below.
        changed_zones = self._recompute_zones_control(handover_time)

        # Realtime: broadcast the release + recolor to every Session whose
        # teams were touched by this deactivation (a repository tower can
        # be live in several Sessions at once).
        for session in self._sessions_for_teams(affected_team_ids):
            events.emit_tower_ownership_changed(session, self, team=None, kind='released')
            for zone in changed_zones:
                events.emit_zone_control_changed(session, zone)
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
        # this capture is a steal; otherwise it is a (re)conquest.
        was_steal = TeamTowerOwnership.objects.filter(
            tower=self, timestamp_end__isnull=True, team__group=team.group,
        ).exclude(team=team).exists()
        if not no_bonus:
            bonus = self.initial_bonus
            if self.decrease_initial_bonus:
                previous_tower_ownerships = TeamTowerOwnership.objects.filter(tower=self, team=team).count()
                while previous_tower_ownerships > 0:
                    bonus = bonus / 2.
                    previous_tower_ownerships -= 1
            # score-multipliers: scale the base bonus by the tower's
            # effective factor at capture time. With no multiplier the
            # factor is exactly 1.0 and the bonus (and its max(..., 1)
            # floor) is unchanged.
            factor = effective_tower_factor(team.session, self)
            if factor != 1.0:
                bonus = bonus * factor
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
        changed_zones = self._recompute_zones_control(handover_time, capturing_team=team)

        # tower-locking: a confirmed finish captures then releases — close
        # the capturing team's active lock with FINISHED. Mode-independent
        # (under FREE_FOR_ALL no lock exists, so this is a no-op) and
        # scoped to still-active locks so an expired lock is left for the
        # sweep to stamp EXPIRED.
        TowerLock.objects.filter(
            tower=self,
            team=team,
            released_at__isnull=True,
            expires_at__gt=handover_time,
        ).update(released_at=handover_time, release_reason=TowerLock.FINISHED)

        # Realtime: broadcast the capture (and any zone-control flip) to
        # the Session group, then a fresh scoreboard snapshot. Push
        # notifications for steal/conquer hang off the same emit (see
        # game/events.py); everything degrades to a no-op without a
        # channel layer.
        session = team.session
        events.emit_tower_ownership_changed(
            session, self, team=team, kind='stolen' if was_steal else 'conquered',
        )
        for zone in changed_zones:
            events.emit_zone_control_changed(session, zone)
        events.emit_scoreboard_update(session)

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

        Returns the list of zones whose control changed (realtime recolor).
        """
        changed_zones = []
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
                closed_any = False
                for zone_ownership in open_ownerships:
                    zone_ownership.timestamp_end = handover_time
                    zone_ownership.save()
                    zone_ownership.team.update_score(zone_ownership.get_score())
                    closed_any = True
                if closed_any:
                    changed_zones.append(zone)
                continue

            # One control computation per TeamGroup of every Game that
            # reaches this zone through its collections.
            zone_changed = False
            for group in TeamGroup.objects.filter(game__collections__zones=zone).distinct():
                if self._recompute_zone_group_control(
                    zone, group, active_tower_ids, handover_time, capturing_team,
                ):
                    zone_changed = True
            if zone_changed:
                changed_zones.append(zone)
        return changed_zones

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

        # Report whether this group's control of the zone changed
        # (drives the realtime zone recolor emit in the callers).
        return bool(to_remove or to_add)

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

    def active_lock(self, group):
        """The active TowerLock for `group`, honoring lazy expiry.

        A lock whose `expires_at` has passed is treated as free even if
        the sweep has not yet stamped `released_at` (tower-locking §4.1).
        Returns None when `group` is None — locks are strictly per
        TeamGroup.
        """
        if group is None:
            return None
        return TowerLock.objects.filter(
            tower=self,
            group=group,
            released_at__isnull=True,
            expires_at__gt=_now(),
        ).select_related('team').first()

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


class TowerPhoto(models.Model):
    """A curator-captured reference photo of a Tower's physical objective.

    Field-authoring provenance: helps players recognise the thing the
    tower stands for. Explicitly distinct from the player submission
    photos on `TeamTowerChallenge` — a Tower MAY have many reference
    photos (several angles of the same fountain).
    """

    tower = models.ForeignKey(Tower, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='tower_photos')
    caption = models.CharField(max_length=255, blank=True, default='')
    captured_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tower_photos',
    )
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-captured_at']

    def __str__(self):
        return f'Reference photo of {self.tower.name} ({self.captured_at:%Y-%m-%d})' \
            if self.captured_at else f'Reference photo of {self.tower.name}'


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

    def can_author(self, user):
        """Field-authoring permission on this Collection.

        Writing geometry into a Collection mutates the map of every Game
        that links it, so authoring requires template edit rights
        (`Game.can_edit`) on ALL referencing Games. Superusers and the
        collection's own creator always pass; an unreferenced collection
        with no recorded creator stays open to any staff user (legacy
        behavior, mirroring `Game.can_edit`).
        """
        if user is None or not getattr(user, 'is_authenticated', False) or not user.is_staff:
            return False
        if user.is_superuser:
            return True
        if self.created_by_id == user.id:
            return True
        games = list(self.games.all())
        if games:
            return all(game.can_edit(user) for game in games)
        return self.created_by_id is None


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

    # --- challenge-type-system: pluggable type discriminator. The
    # default (TEXT / no code / empty config / no override) preserves
    # pre-change behavior exactly; validation and review flow are
    # resolved through game.challenge_types.get_handler(type). ---
    type = models.CharField(
        max_length=8,
        choices=CHALLENGE_TYPE_CHOICES,
        default=TYPE_TEXT,
    )
    # Scan types (NFC_QR): the code embedded in the QR/NFC the venue
    # hands out. NEVER exposed to players through the challenge API.
    validation_code = models.CharField(max_length=64, null=True, blank=True)
    # Per-type extras, e.g. {'venue_label': 'Bar X', 'single_use': true}.
    type_config = models.JSONField(default=dict, blank=True)
    # Optional override of the handler's default review flow (e.g. force
    # a suspicious NFC_QR challenge to MANUAL staff review).
    review_mode = models.CharField(
        max_length=8,
        choices=REVIEW_MODE_CHOICES,
        null=True,
        blank=True,
    )

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

    def effective_review_mode(self):
        """The review flow this challenge resolves to.

        `challenge.review_mode` when set, else the registered handler's
        default; None for an unknown/unregistered type (which the
        submission pipeline rejects safely).
        """
        if self.review_mode:
            return self.review_mode
        handler = get_handler(self.type)
        return handler.review_mode if handler else None

    def required_payload(self):
        """Payload keys a submission for this challenge must supply."""
        handler = get_handler(self.type)
        return list(handler.required_payload) if handler else []

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
    # challenge-type-system: the scanned code carried by scan-type
    # submissions (NFC_QR / RFID); null for TEXT / PHOTO. Kept on auto
    # outcomes as the audit trail of what was scanned.
    submitted_code = models.CharField(max_length=64, null=True, blank=True)

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
                if effective_mode(self.team.session) == MODE_TRAIL:
                    # mode-trail-discovery: a confirmed gate advances the
                    # trail INSTEAD of capturing the tower — domination
                    # ownership/scoring stays inert in TRAIL mode.
                    from game.trail import on_submission_confirmed
                    on_submission_confirmed(self)
                else:
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
        # Auto-confirm (RFID / NFC_QR) inserts an already-CONFIRMED row,
        # so the PENDING->CONFIRMED transition never fires for it.
        if self.outcome == TeamTowerChallenge.CONFIRMED:
            self._reset_fail_counters_on_confirm()
        # challenge-type-system: an auto-REJECTED scan (wrong/consumed
        # code) is inserted as an already-REJECTED row; apply the same
        # failure consequences a staff rejection triggers so it feeds
        # the cooldown and fail counters. Flagged by the submission
        # serializer only — direct ORM inserts (fixtures, admin) keep
        # their pre-change behavior.
        if self.outcome == TeamTowerChallenge.REJECTED and getattr(self, '_system_resolved', False):
            self._apply_failure_consequences()

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
        base = self.zone.get_score(
            seconds=score_time,
            time_unit=effective_time_unit(self.team.session),
        )
        # score-multipliers: floating points are the base curve value
        # times the zone's effective factor at the evaluation instant;
        # a finalized (closed) window uses the factor at close time.
        # With no multiplier the factor is exactly 1.0 (identity).
        factor = effective_zone_factor(self.team.session, self.zone, at=ref_time)
        if factor != 1.0:
            return base * factor
        return base

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


class TowerLock(models.Model):
    """An exclusive attempt window on a tower (tower-locking capability).

    Created by `initiate` under LOCK_ON_INITIATE: the tower is locked to
    `team` for its TeamGroup until `expires_at`. A lock is ACTIVE while
    `released_at` is null and `expires_at` is in the future; the partial
    unique constraint allows at most one un-released lock per
    (tower, group), so a lock in one group never blocks another group.
    `group` is denormalized from `team.group` so the constraint can
    target the group directly.
    """

    FINISHED = 'FINISHED'
    EXPIRED = 'EXPIRED'
    CANCELLED = 'CANCELLED'
    RELEASE_REASON_CHOICES = [
        (FINISHED, 'Finished — a confirmed finish captured the tower'),
        (EXPIRED, 'Expired — the finish deadline passed without a confirmed finish'),
        (CANCELLED, 'Cancelled — voluntarily or by staff, before finishing'),
    ]

    tower = models.ForeignKey(Tower, on_delete=models.CASCADE, related_name='locks')
    team = models.ForeignKey('organize.Team', on_delete=models.CASCADE, related_name='tower_locks')
    group = models.ForeignKey(
        'organize.TeamGroup', on_delete=models.CASCADE, related_name='tower_locks',
    )
    started_at = models.DateTimeField()
    expires_at = models.DateTimeField()
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.CharField(
        max_length=16, choices=RELEASE_REASON_CHOICES, null=True, blank=True,
    )

    class Meta:
        ordering = ['-started_at']
        constraints = [
            models.UniqueConstraint(
                fields=['tower', 'group'],
                condition=models.Q(released_at__isnull=True),
                name='unique_active_tower_lock_per_group',
            ),
        ]

    def __str__(self):
        state = self.release_reason or ('active' if self.is_active() else 'expired')
        return f'TowerLock({self.team} @ {self.tower}, {state})'

    def is_active(self, now=None):
        """Active ⇔ not released AND the finish deadline is still ahead."""
        now = now or _now()
        return self.released_at is None and self.expires_at > now

    def remaining_seconds(self, now=None):
        now = now or _now()
        if not self.is_active(now):
            return 0
        return max(0, int((self.expires_at - now).total_seconds()))

    def release(self, reason, when=None):
        """Idempotently release this lock: only sets `released_at` when null.

        Performed as a guarded UPDATE so concurrent releases (finish vs
        sweep vs cancel) cannot double-release — the first writer wins
        and later calls are no-ops. Returns True when this call did the
        release.
        """
        when = when or _now()
        updated = TowerLock.objects.filter(
            pk=self.pk, released_at__isnull=True,
        ).update(released_at=when, release_reason=reason)
        if updated:
            self.released_at = when
            self.release_reason = reason
        else:
            self.refresh_from_db(fields=['released_at', 'release_reason'])
        return bool(updated)

    @classmethod
    def sweep_expired(cls, now=None):
        """Stamp EXPIRED on every lapsed, un-released lock. Idempotent.

        `released_at` is pinned to `expires_at` — the instant the lock
        logically stopped protecting the tower — rather than the sweep
        time. Lazy-on-read checks make this a tidy-up, never a
        correctness dependency.
        """
        now = now or _now()
        return cls.objects.filter(
            released_at__isnull=True, expires_at__lte=now,
        ).update(released_at=F('expires_at'), release_reason=cls.EXPIRED)

    @classmethod
    def acquire(cls, tower, team, minutes, now=None):
        """Try to lock `tower` for `team`'s group for `minutes` minutes.

        Returns `(lock, created)`; `(None, False)` means another team in
        the group holds an active lock (the caller maps that to 409).
        Re-initiating while already holding the active lock returns the
        existing lock (idempotent). Expired locks on this (tower, group)
        are lazily released first so a stale row never blocks the
        partial-unique constraint.
        """
        from django.db import IntegrityError
        now = now or _now()
        group = team.group
        with transaction.atomic():
            # Lazy expiry (§4.1): free any lapsed lock before acquiring.
            cls.objects.filter(
                tower=tower, group=group,
                released_at__isnull=True, expires_at__lte=now,
            ).update(released_at=F('expires_at'), release_reason=cls.EXPIRED)

            current = cls.objects.filter(
                tower=tower, group=group, released_at__isnull=True,
            ).select_related('team').first()
            if current is not None:
                if current.team_id == team.id:
                    return current, False
                return None, False
            try:
                with transaction.atomic():
                    lock = cls.objects.create(
                        tower=tower,
                        team=team,
                        group=group,
                        started_at=now,
                        expires_at=now + timedelta(minutes=minutes),
                    )
            except IntegrityError:
                # A concurrent initiate won the partial-unique race.
                return None, False
            return lock, True


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


# --- nfc-native-and-secure-links: provisioned tags + scan audit ----------

NFC_MODE_LEGACY_URL = 'LEGACY_URL'
NFC_MODE_SECURE_TOKEN = 'SECURE_TOKEN'
NFC_MODE_CHOICES = [
    (NFC_MODE_LEGACY_URL, 'Legacy forwardable URL (mirrors /tower/rfid/<code>/)'),
    (NFC_MODE_SECURE_TOKEN, 'Secure app-only token'),
]


def _generate_nfc_token():
    """Opaque URL-safe token (32 chars). Meaningless outside the capture API."""
    return secrets.token_urlsafe(24)


class NfcTag(models.Model):
    """A provisioned physical tag (NTAG sticker / printed QR).

    Threat model (see the change's design.md): the tag's contents are
    EXTRACTABLE AND FORGEABLE — a motivated attacker with a reader can
    dump the NDEF and replay the token. Integrity relies on app-gating
    + proximity + the TagScan audit, never on tag secrecy. SECURE_TOKEN
    tags are only actionable through the authenticated capture endpoint;
    LEGACY_URL tags mirror the forwardable /tower/rfid/<code>/ URL.
    """

    token = models.CharField(
        max_length=64, unique=True, default=_generate_nfc_token, editable=False,
    )
    mode = models.CharField(
        max_length=16, choices=NFC_MODE_CHOICES, default=NFC_MODE_SECURE_TOKEN,
    )
    # Exactly one target: a Tower (capture) or a tower-bound Challenge
    # (routes into the challenge-submission flow). Enforced in clean().
    tower = models.ForeignKey(
        Tower, on_delete=models.CASCADE, null=True, blank=True,
        related_name='nfc_tags',
    )
    challenge = models.ForeignKey(
        Challenge, on_delete=models.CASCADE, null=True, blank=True,
        related_name='nfc_tags',
    )
    is_active = models.BooleanField(default=True)
    label = models.CharField(max_length=255, blank=True, default='')
    # Where the physical tag is concealed (inside a tree, behind wall
    # plaster, …) — staff-only provisioning note, never sent to players.
    hidden_hint = models.TextField(blank=True, default='')
    # Replay hardening (optional, NTAG 424 DNA-style rolling counter):
    # the highest counter accepted so far. Used only when the session's
    # effective nfc_replay_hardening is on.
    expected_counter = models.PositiveIntegerField(null=True, blank=True)
    last_counter = models.PositiveIntegerField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='nfc_tags_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'NfcTag({self.mode}, {self.label or self.token[:8]})'

    def clean(self):
        from django.core.exceptions import ValidationError
        if self.mode == NFC_MODE_SECURE_TOKEN:
            if bool(self.tower_id) == bool(self.challenge_id):
                raise ValidationError(
                    'A SECURE_TOKEN tag must target exactly one of a Tower '
                    'or a Challenge.',
                )
            if self.challenge_id and self.challenge.tower_id is None:
                raise ValidationError(
                    'A challenge-targeted tag needs a tower-bound challenge '
                    '(submissions record the tower the scan happened at).',
                )
        else:  # LEGACY_URL mirrors an RFID tower's public URL.
            if self.challenge_id or not self.tower_id:
                raise ValidationError(
                    'A LEGACY_URL tag must target a Tower (not a Challenge).',
                )
            if self.tower.category != Tower.CATEGORY_RFID or not self.tower.rfid_code:
                raise ValidationError(
                    'A LEGACY_URL tag mirrors an RFID-category tower and '
                    'needs that tower to carry an rfid_code.',
                )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    @property
    def target(self):
        return self.tower or self.challenge

    def capture_tower(self):
        """The Tower a confirmed scan captures / is measured against."""
        if self.tower_id:
            return self.tower
        return self.challenge.tower if self.challenge_id else None

    def app_link(self):
        """The app-link (Android App Link / iOS Universal Link) URL."""
        return f'{settings.BASE_URL}/nfc/{self.token}/'

    def ndef_payload(self):
        """The writable NDEF records for provisioning this tag.

        SECURE_TOKEN: an app-triggering URI record (the app-link, which
        doubles as the custom-scheme deep link target) plus an Android
        Application Record so Android routes the tap to the app; the
        token rides in the URI. LEGACY_URL: the existing public RFID URL.
        """
        package = getattr(settings, 'NFC_ANDROID_PACKAGE', 'ro.cercetador.app')
        if self.mode == NFC_MODE_SECURE_TOKEN:
            return {
                'mode': self.mode,
                'token': self.token,
                'records': [
                    {'type': 'uri', 'uri': self.app_link()},
                    {'type': 'android_application_record', 'package': package},
                ],
            }
        return {
            'mode': self.mode,
            'token': self.token,
            'records': [
                {
                    'type': 'uri',
                    'uri': f'{settings.BASE_URL}/tower/rfid/{self.tower.rfid_code}',
                },
            ],
        }


class TagScan(models.Model):
    """Audit record for every capture attempt reaching the NFC endpoint.

    Written for CONFIRMED, PENDING and every rejection flavor, so a
    runner can spot anomalies (forwarded tokens failing proximity,
    replayed counters) after the fact — audit is one leg of the
    accepted threat model.
    """

    OUTCOME_CONFIRMED = 'CONFIRMED'
    OUTCOME_PENDING = 'PENDING'
    OUTCOME_REJECTED_NO_TEAM = 'REJECTED_NO_TEAM'
    OUTCOME_REJECTED_INACTIVE = 'REJECTED_INACTIVE'
    OUTCOME_REJECTED_DISABLED = 'REJECTED_DISABLED'
    OUTCOME_REJECTED_APP = 'REJECTED_APP'
    OUTCOME_REJECTED_SCOPE = 'REJECTED_SCOPE'
    OUTCOME_REJECTED_REPLAY = 'REJECTED_REPLAY'
    OUTCOME_REJECTED_PROXIMITY = 'REJECTED_PROXIMITY'
    OUTCOME_REJECTED_STATE = 'REJECTED_STATE'
    OUTCOME_REJECTED_CODE = 'REJECTED_CODE'
    OUTCOME_CHOICES = [
        (OUTCOME_CONFIRMED, 'Confirmed capture'),
        (OUTCOME_PENDING, 'Pending (held / manual review)'),
        (OUTCOME_REJECTED_NO_TEAM, 'Rejected: no active team'),
        (OUTCOME_REJECTED_INACTIVE, 'Rejected: tag inactive'),
        (OUTCOME_REJECTED_DISABLED, 'Rejected: secure mode disabled'),
        (OUTCOME_REJECTED_APP, 'Rejected: app-origin marker missing'),
        (OUTCOME_REJECTED_SCOPE, 'Rejected: target outside session scope'),
        (OUTCOME_REJECTED_REPLAY, 'Rejected: replay counter'),
        (OUTCOME_REJECTED_PROXIMITY, 'Rejected: out of proximity'),
        (OUTCOME_REJECTED_STATE, 'Rejected: paused / locked out'),
        (OUTCOME_REJECTED_CODE, 'Rejected: challenge code validation'),
    ]

    tag = models.ForeignKey(NfcTag, on_delete=models.CASCADE, related_name='scans')
    player = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tag_scans',
    )
    membership = models.ForeignKey(
        'organize.TeamMembership', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tag_scans',
    )
    session = models.ForeignKey(
        'organize.Session', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='tag_scans',
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    outcome = models.CharField(max_length=32, choices=OUTCOME_CHOICES)
    lat = models.FloatField(null=True, blank=True)
    lng = models.FloatField(null=True, blank=True)
    accuracy = models.FloatField(null=True, blank=True)
    counter = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f'TagScan({self.tag_id}, {self.outcome}, {self.player})'


# ---------------------------------------------------------------------------
# mode-trail-discovery: trail structure + per-party route / progress
# ---------------------------------------------------------------------------

# Trail structures.
STRUCTURE_FIXED_ORDER = 'FIXED_ORDER'
STRUCTURE_GRAPH = 'GRAPH'
STRUCTURE_CIRCUIT = 'CIRCUIT'
STRUCTURE_CHOICES = [
    (STRUCTURE_FIXED_ORDER, 'Fixed order — linear 1→2→3→4'),
    (STRUCTURE_GRAPH, 'Graph — branching, the party chooses'),
    (STRUCTURE_CIRCUIT, 'Circuit — shared loop, per-party start offset'),
]

# Starting knowledge.
KNOWLEDGE_ALL_KNOWN = 'ALL_KNOWN'
KNOWLEDGE_ONE_KNOWN = 'ONE_KNOWN'
KNOWLEDGE_NONE_KNOWN = 'NONE_KNOWN'
KNOWLEDGE_CHOICES = [
    (KNOWLEDGE_ALL_KNOWN, 'All points known from the start'),
    (KNOWLEDGE_ONE_KNOWN, 'Only the start point known'),
    (KNOWLEDGE_NONE_KNOWN, 'Nothing known — discover the start'),
]

# Participation.
PARTICIPATION_TEAM = 'TEAM'
PARTICIPATION_SOLO = 'SOLO'
PARTICIPATION_CHOICES = [
    (PARTICIPATION_TEAM, 'Teams'),
    (PARTICIPATION_SOLO, 'Solo players'),
]


class Trail(models.Model):
    """The trail layer of a trail-mode Game (1:1).

    Steps/edges add an ordering/graph layer OVER repository Towers —
    the Tower stays a reusable library asset carrying no trail data.
    """

    game = models.OneToOneField(
        'organize.Game', on_delete=models.CASCADE, related_name='trail',
    )
    structure = models.CharField(
        max_length=16, choices=STRUCTURE_CHOICES, default=STRUCTURE_FIXED_ORDER,
    )
    starting_knowledge = models.CharField(
        max_length=16, choices=KNOWLEDGE_CHOICES, default=KNOWLEDGE_ONE_KNOWN,
    )
    participation = models.CharField(
        max_length=8, choices=PARTICIPATION_CHOICES, default=PARTICIPATION_TEAM,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Trail({self.game.slug}, {self.structure})'

    def ordered_steps(self):
        """The trail's global step order (FIXED_ORDER / CIRCUIT baseline)."""
        return list(self.steps.order_by('order', 'id'))

    def start_steps(self):
        steps = list(self.steps.filter(is_start=True).order_by('order', 'id'))
        if steps:
            return steps
        first = self.steps.order_by('order', 'id').first()
        return [first] if first else []

    def validate_structure(self):
        """Authoring validator: return a list of issue dicts (empty = OK).

        Checks: every step's Tower resolves through the Game's
        Collections; at least one start; for GRAPH, every non-start step
        reachable from a start, at least one finish reachable, and no
        dead-end (a non-finish step with no outgoing edge).
        """
        issues = []
        steps = list(self.steps.select_related('tower').order_by('order', 'id'))
        if not steps:
            issues.append({'code': 'no_steps', 'message': 'Trail has no steps.'})
            return issues

        game_tower_ids = set(self.game.towers().values_list('id', flat=True))
        for step in steps:
            if step.tower_id not in game_tower_ids:
                issues.append({
                    'code': 'tower_outside_collections',
                    'step_id': step.id,
                    'message': (
                        f'Step {step.id} is bound to tower "{step.tower.name}" '
                        "outside the Game's Collections."
                    ),
                })

        starts = [s for s in steps if s.is_start]
        if not starts and self.structure == STRUCTURE_GRAPH:
            issues.append({
                'code': 'no_start',
                'message': 'A GRAPH trail needs at least one is_start step.',
            })

        if self.structure == STRUCTURE_GRAPH:
            outgoing = {}
            for edge in self.edges.all():
                outgoing.setdefault(edge.from_step_id, []).append(edge.to_step_id)
            reachable = set()
            frontier = [s.id for s in (starts or steps[:1])]
            while frontier:
                current = frontier.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                frontier.extend(outgoing.get(current, []))
            for step in steps:
                if not step.is_start and step.id not in reachable:
                    issues.append({
                        'code': 'unreachable_step',
                        'step_id': step.id,
                        'message': f'Step {step.id} is not reachable from any start.',
                    })
                if not step.is_finish and not outgoing.get(step.id):
                    issues.append({
                        'code': 'dead_end',
                        'step_id': step.id,
                        'message': (
                            f'Step {step.id} is a dead-end: not a finish and '
                            'has no outgoing edge.'
                        ),
                    })
            finishes = {s.id for s in steps if s.is_finish}
            if not finishes:
                issues.append({
                    'code': 'no_finish',
                    'message': 'A GRAPH trail needs at least one is_finish step.',
                })
            elif not (finishes & reachable):
                issues.append({
                    'code': 'finish_unreachable',
                    'message': 'No finish step is reachable from a start.',
                })
        return issues


class TrailStep(models.Model):
    """A node of the trail, geofenced at a repository Tower."""

    trail = models.ForeignKey(Trail, on_delete=models.CASCADE, related_name='steps')
    tower = models.ForeignKey(Tower, on_delete=models.CASCADE, related_name='trail_steps')
    order = models.PositiveIntegerField(default=0)
    is_start = models.BooleanField(default=False)
    is_finish = models.BooleanField(default=False)
    # The unlock gate: an ordinary Challenge validated by its type
    # (challenge-types capability). NULL = read-only gate — arrival
    # within range unlocks the step immediately.
    gate_challenge = models.ForeignKey(
        Challenge, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='gates_trail_steps',
    )
    # Clue shown once this step is revealed (FIXED_ORDER / CIRCUIT link
    # clues live here on the *target* step; GRAPH branch clues live on
    # the edges).
    clue_text = models.TextField(blank=True, default='')
    # Creator-supplied out-of-band hint for a NONE_KNOWN start.
    start_hint = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['order', 'id']

    def __str__(self):
        return f'{self.trail} #{self.order} @ {self.tower.name}'


class TrailEdge(models.Model):
    """Directed clue-bearing link between two steps (GRAPH branches)."""

    trail = models.ForeignKey(Trail, on_delete=models.CASCADE, related_name='edges')
    from_step = models.ForeignKey(
        TrailStep, on_delete=models.CASCADE, related_name='outgoing_edges',
    )
    to_step = models.ForeignKey(
        TrailStep, on_delete=models.CASCADE, related_name='incoming_edges',
    )
    clue = models.TextField(blank=True, default='')

    class Meta:
        unique_together = (('from_step', 'to_step'),)

    def __str__(self):
        return f'{self.from_step_id} → {self.to_step_id}'


class TeamTrailRoute(models.Model):
    """A party's assigned route in one Session.

    The party is a Team (participation=TEAM) or a single player
    (participation=SOLO) — exactly one of `team` / `player` is set.
    `start_step` pins where the party begins; FIXED_ORDER / CIRCUIT
    routes may additionally pin an explicit ordered sequence through
    `TeamTrailRouteStep` rows (anti-collision orderings).
    """

    session = models.ForeignKey(
        'organize.Session', on_delete=models.CASCADE, related_name='trail_routes',
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, null=True, blank=True,
        related_name='trail_routes',
    )
    player = models.ForeignKey(
        'organize.UserProfile', on_delete=models.CASCADE, null=True, blank=True,
        related_name='trail_routes',
    )
    start_step = models.ForeignKey(
        TrailStep, on_delete=models.CASCADE, related_name='routes_starting_here',
    )
    finished_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'team'],
                condition=models.Q(team__isnull=False),
                name='unique_trail_route_per_team',
            ),
            models.UniqueConstraint(
                fields=['session', 'player'],
                condition=models.Q(player__isnull=False),
                name='unique_trail_route_per_player',
            ),
        ]

    def __str__(self):
        return f'Route({self.party_label()} @ {self.session})'

    def party_label(self):
        if self.team_id:
            return self.team.name
        return self.player.user.get_username() if self.player_id else '?'

    def sequence(self):
        """The party's ordered step list, or None for GRAPH free choice.

        Priority: explicit TeamTrailRouteStep rows; else CIRCUIT derives
        the shared cyclic order rotated to this party's start (wrapping
        to the step before it); else FIXED_ORDER follows the global
        ascending order. GRAPH pins only the start — the path emerges
        from the party's branch choices.
        """
        explicit = [rs.step for rs in self.route_steps.select_related('step').order_by('position')]
        if explicit:
            return explicit
        trail = self.start_step.trail
        if trail.structure == STRUCTURE_GRAPH:
            return None
        steps = trail.ordered_steps()
        if trail.structure == STRUCTURE_CIRCUIT and steps:
            ids = [s.id for s in steps]
            if self.start_step_id in ids:
                offset = ids.index(self.start_step_id)
                return steps[offset:] + steps[:offset]
        return steps


class TeamTrailRouteStep(models.Model):
    """Ordered through-row: one step at one position of a party's route."""

    route = models.ForeignKey(
        TeamTrailRoute, on_delete=models.CASCADE, related_name='route_steps',
    )
    step = models.ForeignKey(TrailStep, on_delete=models.CASCADE, related_name='+')
    position = models.PositiveIntegerField()

    class Meta:
        ordering = ['position']
        unique_together = (('route', 'position'), ('route', 'step'))

    def __str__(self):
        return f'{self.route} [{self.position}] {self.step_id}'


class TeamTrailProgress(models.Model):
    """Per-party, per-step trail progress — (session, party)-scoped.

    REVEALED → the party knows the point (it shows on its map);
    ARRIVED  → the party physically reached the geofence;
    UNLOCKED → the step's gate was completed (progression advances).
    """

    REVEALED = 'REVEALED'
    ARRIVED = 'ARRIVED'
    UNLOCKED = 'UNLOCKED'
    STATE_CHOICES = [
        (REVEALED, 'Revealed'),
        (ARRIVED, 'Arrived'),
        (UNLOCKED, 'Unlocked'),
    ]
    _STATE_RANK = {REVEALED: 0, ARRIVED: 1, UNLOCKED: 2}

    session = models.ForeignKey(
        'organize.Session', on_delete=models.CASCADE, related_name='trail_progress',
    )
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, null=True, blank=True,
        related_name='trail_progress',
    )
    player = models.ForeignKey(
        'organize.UserProfile', on_delete=models.CASCADE, null=True, blank=True,
        related_name='trail_progress',
    )
    step = models.ForeignKey(
        TrailStep, on_delete=models.CASCADE, related_name='progress',
    )
    state = models.CharField(max_length=8, choices=STATE_CHOICES, default=REVEALED)
    revealed_at = models.DateTimeField(null=True, blank=True)
    arrived_at = models.DateTimeField(null=True, blank=True)
    unlocked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'team', 'step'],
                condition=models.Q(team__isnull=False),
                name='unique_trail_progress_per_team_step',
            ),
            models.UniqueConstraint(
                fields=['session', 'player', 'step'],
                condition=models.Q(player__isnull=False),
                name='unique_trail_progress_per_player_step',
            ),
        ]

    def __str__(self):
        who = self.team or self.player
        return f'{who} @ step {self.step_id}: {self.state}'

    def advance(self, state, when=None):
        """Move forward to `state` (never backwards); stamp timestamps."""
        when = when or _now()
        if self._STATE_RANK[state] <= self._STATE_RANK.get(self.state, -1) and self.pk:
            return self
        stamp_fields = []
        for target, field in (
            (self.REVEALED, 'revealed_at'),
            (self.ARRIVED, 'arrived_at'),
            (self.UNLOCKED, 'unlocked_at'),
        ):
            if (
                self._STATE_RANK[target] <= self._STATE_RANK[state]
                and getattr(self, field) is None
            ):
                setattr(self, field, when)
                stamp_fields.append(field)
        self.state = state
        self.save(update_fields=['state'] + stamp_fields if self.pk else None)
        return self


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


class ScoreMultiplier(models.Model):
    """A time/place-based scoring modifier (score-multipliers capability).

    Multiplies a tower's or zone's worth (or every target, for GLOBAL
    scope) by `factor` while in effect. Owned by exactly one of a Game
    (template-level — applies to every Session of that game) or a single
    Session (run-level). Factors COMPOSE multiplicatively across scopes
    (global x zone / global x tower); with no rows the effective factor
    is exactly 1.0, preserving pre-change scoring byte-for-byte.

    Windows are typed to the multiplier type: SCHEDULED uses
    Session-relative offsets (resolved against `Session.start_time`, so
    a template arc replays on every run); MANUAL / RANDOM_BONUS use
    absolute `starts_at`/`ends_at` (unset bound = open on that side).
    The factor is applied at the evaluation instant — no time
    integration across windows (documented non-goal).
    """

    SCOPE_TOWER = 'TOWER'
    SCOPE_ZONE = 'ZONE'
    SCOPE_GLOBAL = 'GLOBAL'
    SCOPE_CHOICES = [
        (SCOPE_TOWER, 'One tower'),
        (SCOPE_ZONE, 'One zone'),
        (SCOPE_GLOBAL, 'Whole game'),
    ]

    TYPE_MANUAL = 'MANUAL'
    TYPE_SCHEDULED = 'SCHEDULED'
    TYPE_RANDOM_BONUS = 'RANDOM_BONUS'
    TYPE_CHOICES = [
        (TYPE_MANUAL, 'Manual — admin toggles is_active live'),
        (TYPE_SCHEDULED, 'Scheduled — Session-relative offset window'),
        (TYPE_RANDOM_BONUS, 'Random bonus — dropped live with an absolute window'),
    ]

    game = models.ForeignKey(
        'organize.Game',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='score_multipliers',
    )
    session = models.ForeignKey(
        'organize.Session',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='score_multipliers',
    )
    scope = models.CharField(max_length=8, choices=SCOPE_CHOICES, default=SCOPE_GLOBAL)
    tower = models.ForeignKey(
        Tower, on_delete=models.CASCADE, null=True, blank=True,
        related_name='score_multipliers',
    )
    zone = models.ForeignKey(
        Zone, on_delete=models.CASCADE, null=True, blank=True,
        related_name='score_multipliers',
    )
    multiplier_type = models.CharField(
        max_length=16, choices=TYPE_CHOICES, default=TYPE_MANUAL,
    )
    factor = models.FloatField(default=1.0)
    is_active = models.BooleanField(default=True)
    # SCHEDULED window: offsets from Session.start_time.
    window_start_offset = models.DurationField(null=True, blank=True)
    window_end_offset = models.DurationField(null=True, blank=True)
    # MANUAL / RANDOM_BONUS window: absolute instants.
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    # Player-facing announcement, e.g. 'Double points at Old Tower'.
    label = models.CharField(max_length=255, blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='score_multipliers_created',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        owner = self.session or self.game
        target = {
            self.SCOPE_TOWER: self.tower,
            self.SCOPE_ZONE: self.zone,
        }.get(self.scope, 'global')
        return f'x{self.factor} at {target} ({self.multiplier_type}, {owner})'

    def clean(self):
        super().clean()
        if bool(self.game_id) == bool(self.session_id):
            raise ValidationError(
                'Exactly one of game or session must be set.',
            )
        if self.factor is None or self.factor <= 0:
            raise ValidationError({'factor': 'factor must be greater than 0.'})
        if self.scope == self.SCOPE_TOWER:
            if self.tower_id is None or self.zone_id is not None:
                raise ValidationError(
                    'A TOWER-scoped multiplier needs a tower and no zone.',
                )
        elif self.scope == self.SCOPE_ZONE:
            if self.zone_id is None or self.tower_id is not None:
                raise ValidationError(
                    'A ZONE-scoped multiplier needs a zone and no tower.',
                )
        elif self.tower_id is not None or self.zone_id is not None:
            raise ValidationError(
                'A GLOBAL multiplier may not reference a tower or zone.',
            )
        # Windows are typed to the multiplier type (design decision).
        if self.multiplier_type == self.TYPE_SCHEDULED:
            if self.starts_at is not None or self.ends_at is not None:
                raise ValidationError(
                    'SCHEDULED multipliers use Session-relative offsets, '
                    'not absolute starts_at/ends_at.',
                )
        elif self.window_start_offset is not None or self.window_end_offset is not None:
            raise ValidationError(
                'Only SCHEDULED multipliers may use Session-relative offsets.',
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def resolved_window(self, session=None):
        """(start, end) instants for `session`; None means open on that side.

        SCHEDULED offsets resolve against the Session's `start_time`, so
        a Game-owned template arc replays on every run. Returns
        (None, None) never being in effect when a SCHEDULED multiplier
        has no session context.
        """
        if self.multiplier_type != self.TYPE_SCHEDULED:
            return self.starts_at, self.ends_at
        session = session or self.session
        if session is None:
            return None, None
        anchor = session.start_time
        start = anchor + self.window_start_offset if self.window_start_offset is not None else None
        end = anchor + self.window_end_offset if self.window_end_offset is not None else None
        return start, end

    def is_in_effect(self, at=None, session=None):
        """Whether this multiplier applies at instant `at` for `session`.

        In effect iff `is_active` AND `at` falls inside the resolved
        window (half-open [start, end); an unset bound is open).
        """
        if not self.is_active:
            return False
        if self.multiplier_type == self.TYPE_SCHEDULED and (session or self.session) is None:
            return False
        at = at or _now()
        start, end = self.resolved_window(session=session)
        if start is not None and at < start:
            return False
        if end is not None and at >= end:
            return False
        return True


def _effective_factor(session, scope, target_field, target, at=None):
    """Product of in-effect multipliers matching GLOBAL or the target.

    Draws from the union of the Session's own multipliers and its Game's
    multipliers; returns exactly 1.0 when none apply so scoring without
    multipliers is byte-for-byte identical to pre-change behavior.
    """
    if session is None:
        return 1.0
    at = at or _now()
    factor = 1.0
    candidates = ScoreMultiplier.objects.filter(
        Q(session=session) | Q(game_id=session.game_id),
        is_active=True,
    ).filter(
        Q(scope=ScoreMultiplier.SCOPE_GLOBAL)
        | Q(scope=scope, **{target_field: target}),
    )
    for multiplier in candidates:
        if multiplier.is_in_effect(at=at, session=session):
            factor *= multiplier.factor
    return factor


def effective_tower_factor(session, tower, at=None):
    """Effective score factor for `tower` in `session` at instant `at`."""
    return _effective_factor(
        session, ScoreMultiplier.SCOPE_TOWER, 'tower', tower, at=at,
    )


def effective_zone_factor(session, zone, at=None):
    """Effective score factor for `zone` in `session` at instant `at`."""
    return _effective_factor(
        session, ScoreMultiplier.SCOPE_ZONE, 'zone', zone, at=at,
    )


def active_multipliers_for_session(session, at=None):
    """Every multiplier in effect for `session` at instant `at`.

    The read-only feed behind the active-multiplier endpoints: the union
    of Session-owned and Game-owned rows, filtered to those currently in
    effect, so the map and scoreboard can announce them.
    """
    if session is None:
        return []
    at = at or _now()
    candidates = (
        ScoreMultiplier.objects
        .filter(Q(session=session) | Q(game_id=session.game_id), is_active=True)
        .select_related('tower', 'zone')
    )
    return [m for m in candidates if m.is_in_effect(at=at, session=session)]
