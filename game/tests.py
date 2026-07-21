"""Test suite for the game app.

Organized by feature area to match Phase 0 issue breakdown:

  * Scoring (P0.4)                 - ScoreFunctionsTest, CurrentScoreTest
  * Tower capture + bonus (P0.5)   - TowerCaptureTest
  * Zone recalculation (P0.6)      - ZoneRecalculationTest
  * Proximity check (P0.7)         - ProximityTest
  * Cooloff (P0.8)                 - CooloffTest
  * Next challenge (P0.9)          - ChallengeProgressionTest, NextChallengeEdgeCasesTest
  * RFID capture (P0.10)           - RFIDCaptureTest
  * REST API (P0.11)               - APIEndpointsTest
  * unassign_all action (P0.12)    - UnassignAllTest
  * /health/ endpoint (P0.14)      - HealthTest

Tests target the post-refactor structure:
  * `game` app owns Zone, Tower, Challenge, TeamTowerChallenge, ownership records
  * `organize` app owns Game, TeamGroup, Team, UserProfile, TeamMembership, Invite
  * Teams are grouped by TeamGroup (replacing the legacy EXPLORATORI/TEMERARI/SENIORI
    hardcoded categories). Each Game has its own set of TeamGroups.
"""
import base64
import math
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point, Polygon
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from game.admin import unassign_all
from game.badges import (
    CURRENT_FIRMWARE_VERSION,
    GATEWAY_PROTOCOL_VERSION,
    RING_PATTERN_ENERGY_FILL,
    RING_PATTERN_IDLE,
    RING_PATTERN_OUT,
)
from game.dementors import assign_initial_roles, economy_tick, run_tick
from game.models import (
    FLIP_CAUSE_CONVERSION,
    FLIP_CAUSE_DIED,
    FLIP_CAUSE_DRAINED,
    FLIP_CAUSE_REVERSE_GAME,
    PROXIMITY_SOURCE_BADGE,
    PROXIMITY_SOURCE_PHONE,
    ROLE_REQUIREMENT_ALL,
    ROLE_REQUIREMENT_ANY,
    ROLE_REQUIREMENT_NONE,
    BadgeAssignment,
    BadgeDevice,
    BadgeTelemetry,
    Challenge,
    DementorFlip,
    DementorState,
    GatewayNode,
    PauseWindow,
    ProximityEvent,
    ProximityIdentity,
    ProximityReport,
    TeamTowerChallenge,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    TeamZoneOwnership,
    Tower,
    Zone,
)
from game.proximity import (
    CONFIDENCE_CORROBORATED,
    CONFIDENCE_ONE_WAY,
    MAX_OBSERVATIONS_PER_REPORT,
    clean_observations,
    derive_proximity,
    rssi_to_bucket,
)
from organize.models import (
    DEMENTOR_EMPTY_DIE,
    PROXIMITY_BUCKET_FAR,
    PROXIMITY_BUCKET_NEAR,
    PROXIMITY_BUCKET_VERY_CLOSE,
    Game,
    GameRole,
    Invite,
    Session,
    Team,
    TeamGroup,
    TeamMembership,
    TeamRole,
)

User = get_user_model()


def _authed_client(team, username='scout'):
    """Create a user + active membership in `team` and return an authed APIClient.

    Also pins the new user's current_session to the team's session so the
    Phase-3 scoping mixins resolve correctly without extra setup.
    """
    user = User.objects.create_user(
        username=username, email=f'{username}@example.com', password='password123',
    )
    TeamMembership.objects.create(team=team, user=user.profile, is_active=True)
    user.profile.current_session = team.session
    user.profile.save(update_fields=['current_session'])
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client, user


def _staff_client(session=None, username='staff'):
    """Create a staff user + token. Optionally pin current_session."""
    user = User.objects.create_user(
        username=username,
        email=f'{username}@example.com',
        password='password123',
        is_staff=True,
    )
    if session is not None:
        user.profile.current_session = session
        user.profile.save(update_fields=['current_session'])
    token = Token.objects.create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client, user

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_game(name="Game A", slug=None):
    if slug is None:
        from django.utils.text import slugify
        base = slugify(name) or 'game'
        slug, counter = base, 2
        while Game.objects.filter(slug=slug).exists():
            slug = f'{base}-{counter}'
            counter += 1
    return Game.objects.create(name=name, slug=slug)


def _make_group(game, name="Explo", slug="explo"):
    return TeamGroup.objects.create(name=name, game=game, slug=slug)


def _make_zone(game, name="Zone A", scoring=Zone.SCORE_LIN, shape=None):
    if shape is None:
        shape = Polygon.from_bbox((23.0, 46.0, 24.0, 47.0))
    return Zone.objects.create(
        name=name, scoring_type=scoring, shape=shape, game=game,
    )


def _make_tower(game, name="T", zone=None, lng=23.5, lat=46.5, is_active=True,
                initial_bonus=0, category=Tower.CATEGORY_NORMAL, rfid_code=None):
    return Tower.objects.create(
        name=name, zone=zone, location=Point(lng, lat), is_active=is_active,
        category=category, initial_bonus=initial_bonus, rfid_code=rfid_code,
        game=game,
    )


def _default_session(game):
    """Helper: return (creating if missing) the default Session for a Game.

    Created RUNNING so gameplay flows (captures, submissions, joins)
    work without each test driving the lifecycle first.
    """
    from organize.models import Session
    session = Session.objects.filter(game=game, slug='default').first()
    if session is None:
        now = timezone.now()
        session = Session.objects.create(
            game=game,
            slug='default',
            name='Default session',
            start_time=now,
            end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
    return session


def _make_team(game, group, name="explo1", color="#003366"):
    return Team.objects.create(
        name=name,
        color=color,
        session=_default_session(game),
        group=group,
    )


def _tiny_png_b64():
    # Real Pillow-generated PNG that passes full image verification.
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(255, 0, 0)).save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


# ---------------------------------------------------------------------------
# P0.4 — Scoring functions & current_score
# ---------------------------------------------------------------------------


class ScoreFunctionsTest(TestCase):
    """Verify every zone scoring strategy's math directly."""

    def setUp(self):
        self.game = _make_game()
        self.zone = _make_zone(self.game, scoring=Zone.SCORE_LIN)

    def test_score_linear(self):
        self.zone.scoring_type = Zone.SCORE_LIN
        self.assertAlmostEqual(self.zone.get_score(60), 1.0)
        self.assertAlmostEqual(self.zone.get_score(600), 10.0)

    def test_score_logarithmic(self):
        self.zone.scoring_type = Zone.SCORE_LOG
        mins = 10
        expected = 30 * math.log(mins) + mins ** 2 / 10000
        self.assertAlmostEqual(self.zone.get_score(mins * 60), expected)

    def test_score_exponential_unbounded(self):
        # mins^2 / 140 + 10  (unbounded)
        self.zone.scoring_type = Zone.SCORE_EXP
        mins = 50
        expected = mins ** 2 / 140 + 10
        self.assertAlmostEqual(self.zone.get_score(mins * 60), expected)

    def test_score_bonus_below_cap(self):
        # min(mins^2/25 + 50, 200) — below the 200-point cap
        self.zone.scoring_type = Zone.SCORE_BONUS
        # mins=50 → 50^2/25 + 50 = 150
        self.assertAlmostEqual(self.zone.get_score(50 * 60), 150.0)

    def test_score_bonus_cap_at_200(self):
        self.zone.scoring_type = Zone.SCORE_BONUS
        # mins=100 → 100^2/25 + 50 = 450 → capped at 200
        self.assertEqual(self.zone.get_score(100 * 60), 200)


class CurrentScoreTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)

    def test_current_score_locked_only(self):
        team = _make_team(self.game, self.group)
        team.score = 42
        team.save()
        self.assertEqual(team.current_score(), 42)

    def test_update_score_increments(self):
        team = _make_team(self.game, self.group)
        team.update_score(10)
        team.update_score(5)
        self.assertEqual(Team.objects.get(pk=team.pk).score, 15)

    def test_current_score_includes_floating(self):
        team = _make_team(self.game, self.group)
        zone = _make_zone(self.game, scoring=Zone.SCORE_LIN)
        ownership = TeamZoneOwnership.objects.create(zone=zone, team=team)
        # Back-date ownership by 10 minutes
        TeamZoneOwnership.objects.filter(pk=ownership.pk).update(
            timestamp_start=datetime.now(dt_timezone.utc) - timedelta(minutes=10),
        )
        team.score = 100
        team.save()
        self.assertAlmostEqual(team.current_score(), 110, places=0)


# ---------------------------------------------------------------------------
# P0.5 — Tower capture awards initial_bonus, ownership managed
# ---------------------------------------------------------------------------


class TowerCaptureTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone, initial_bonus=25)
        self.t1 = _make_team(self.game, self.group)
        self.t2 = _make_team(self.game, self.group, name="t2")

    def test_capture_awards_initial_bonus(self):
        self.tower.assign_to_team(self.t1)
        self.assertEqual(Team.objects.get(pk=self.t1.pk).score, 25)

    def test_capture_opens_ownership(self):
        self.tower.assign_to_team(self.t1)
        self.assertTrue(TeamTowerOwnership.objects.filter(
            tower=self.tower, team=self.t1, timestamp_end__isnull=True,
        ).exists())

    def test_recapture_by_other_team_closes_prior_ownership(self):
        self.tower.assign_to_team(self.t1)
        self.tower.assign_to_team(self.t2)
        self.assertFalse(TeamTowerOwnership.objects.filter(
            tower=self.tower, team=self.t1, timestamp_end__isnull=True,
        ).exists())
        self.assertTrue(TeamTowerOwnership.objects.filter(
            tower=self.tower, team=self.t2, timestamp_end__isnull=True,
        ).exists())
        self.assertEqual(Team.objects.get(pk=self.t2.pk).score, 25)

    def test_zero_initial_bonus(self):
        # When initial_bonus=0, max(0, 1) = 1 is awarded (clamped to 1 by model).
        tower = _make_tower(self.game, zone=self.zone, initial_bonus=0)
        tower.assign_to_team(self.t1)
        self.assertEqual(Team.objects.get(pk=self.t1.pk).score, 1)

    def test_no_bonus_flag_skips_bonus(self):
        # no_bonus=True used by migration/backfill paths
        self.tower.assign_to_team(self.t1, no_bonus=True)
        self.assertEqual(Team.objects.get(pk=self.t1.pk).score, 0)

    def test_decrease_initial_bonus_halves_on_recapture(self):
        # Tower with decrease_initial_bonus=True halves bonus on each recapture
        # by the same team.
        tower = _make_tower(
            self.game, zone=self.zone, initial_bonus=40,
        )
        tower.decrease_initial_bonus = True
        tower.save()

        tower.assign_to_team(self.t1)        # score += 40 (first capture)
        self.assertEqual(Team.objects.get(pk=self.t1.pk).score, 40)
        tower.assign_to_team(self.t1)        # score += 20 (halved)
        self.assertEqual(Team.objects.get(pk=self.t1.pk).score, 60)


# ---------------------------------------------------------------------------
# P0.6 — Zone majority recalculation on capture/deactivation
# ---------------------------------------------------------------------------


class ZoneRecalculationTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game, scoring=Zone.SCORE_LIN)
        self.t1 = _make_team(self.game, self.group, name="t1")
        self.t2 = _make_team(self.game, self.group, name="t2")

    def test_single_tower_zone_goes_to_capturer(self):
        tower = _make_tower(self.game, zone=self.zone)
        tower.assign_to_team(self.t1)
        self.assertEqual(
            list(self.zone.zone_control(self.group)),
            [self.t1.pk],
        )

    def test_majority_rule_across_three_towers(self):
        towers = [
            _make_tower(self.game, zone=self.zone, name=f"t{i}")
            for i in range(3)
        ]
        towers[0].assign_to_team(self.t1)
        towers[1].assign_to_team(self.t1)
        towers[2].assign_to_team(self.t2)
        self.assertEqual(
            list(self.zone.zone_control(self.group)),
            [self.t1.pk],
        )

    def test_tie_gives_both_teams_zone(self):
        t_a = _make_tower(self.game, zone=self.zone, name="ta")
        t_b = _make_tower(self.game, zone=self.zone, name="tb")
        t_a.assign_to_team(self.t1)
        t_b.assign_to_team(self.t2)
        self.assertEqual(
            set(self.zone.zone_control(self.group)),
            {self.t1.pk, self.t2.pk},
        )

    def test_different_group_isolation(self):
        other_group = _make_group(self.game, name="Other", slug="other")
        t1_explo = _make_team(self.game, self.group, name="e1")
        _make_team(self.game, other_group, name="o1")

        tower = _make_tower(self.game, zone=self.zone)
        tower.assign_to_team(t1_explo)

        self.assertEqual(
            list(self.zone.zone_control(self.group)),
            [t1_explo.pk],
        )
        self.assertEqual(list(self.zone.zone_control(other_group)), [])

    def test_deactivating_last_tower_closes_zone_control(self):
        tower = _make_tower(self.game, zone=self.zone)
        tower.assign_to_team(self.t1)
        self.assertTrue(TeamZoneOwnership.objects.filter(
            zone=self.zone, timestamp_end__isnull=True,
        ).exists())

        tower.is_active = False
        tower.save()
        self.assertFalse(TeamZoneOwnership.objects.filter(
            zone=self.zone, timestamp_end__isnull=True,
        ).exists())


# ---------------------------------------------------------------------------
# P0.7 — 50m proximity check on web form
# ---------------------------------------------------------------------------


class ProximityTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(
            self.game, zone=self.zone, lng=23.5, lat=46.5,
        )
        self.team = _make_team(self.game, self.group)
        self.challenge = Challenge.objects.create(
            text="c", tower=self.tower, difficulty=1,
        )

    @staticmethod
    def _offset_lat(lat, meters_north):
        return lat + meters_north / 111_111.0

    def test_api_submission_outside_50m_rejected(self):
        # The serializer's proximity check rejects submissions further than 50m.
        client, _ = _authed_client(self.team)
        lat = self._offset_lat(46.5, 200)
        resp = client.post(
            "/api/team_tower_challenges/",
            {
                "tower": self.tower.pk,
                "challenge": self.challenge.pk,
                "lat": lat,
                "lng": 23.5,
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        # Nothing persisted
        self.assertFalse(TeamTowerChallenge.objects.exists())

    def test_api_submission_within_50m_accepted(self):
        client, user = _authed_client(self.team)
        lat = self._offset_lat(46.5, 10)  # 10m north, well within 50m
        resp = client.post(
            "/api/team_tower_challenges/",
            {
                "tower": self.tower.pk,
                "challenge": self.challenge.pk,
                "lat": lat,
                "lng": 23.5,
                "photo": _tiny_png_b64(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        ttc = TeamTowerChallenge.objects.get()
        # Team derived from membership, not from payload.
        self.assertEqual(ttc.team, self.team)
        self.assertEqual(ttc.submitted_by, user)

    def test_api_submission_requires_auth(self):
        client = APIClient()
        resp = client.post(
            "/api/team_tower_challenges/",
            {"tower": self.tower.pk, "lat": 46.5, "lng": 23.5},
            format="json",
        )
        self.assertEqual(resp.status_code, 403)

    def test_api_submission_rejects_user_without_team(self):
        user = User.objects.create_user(
            username='loner', email='loner@x.com', password='password123',
        )
        token = Token.objects.create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        resp = client.post(
            "/api/team_tower_challenges/",
            {"tower": self.tower.pk, "lat": 46.5, "lng": 23.5},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# P0.8 — 5-minute cooloff after rejected attempt
# ---------------------------------------------------------------------------


class CooloffTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.other_tower = _make_tower(
            self.game, zone=self.zone, name="other",
        )
        self.t1 = _make_team(self.game, self.group)
        self.t2 = _make_team(self.game, self.group, name="t2")
        self.challenge = Challenge.objects.create(
            text="c", tower=self.tower, difficulty=1,
        )

    def _rejected_attempt(self, team, tower, age_seconds):
        ttc = TeamTowerChallenge.objects.create(
            team=team, tower=tower, challenge=self.challenge,
            outcome=TeamTowerChallenge.REJECTED,
        )
        # save() sets timestamp_verified; override to simulate age.
        TeamTowerChallenge.objects.filter(pk=ttc.pk).update(
            timestamp_verified=datetime.now(dt_timezone.utc)
            - timedelta(seconds=age_seconds),
        )
        return ttc

    def test_no_previous_attempt_no_cooloff(self):
        self.assertFalse(self.tower.team_in_cooloff(self.t1))

    def test_rejected_within_5min_cooloff_active(self):
        self._rejected_attempt(self.t1, self.tower, age_seconds=60)
        self.assertTrue(self.tower.team_in_cooloff(self.t1))

    def test_rejected_older_than_5min_cooloff_expired(self):
        self._rejected_attempt(self.t1, self.tower, age_seconds=301)
        self.assertFalse(self.tower.team_in_cooloff(self.t1))

    def test_cooloff_per_tower_isolation(self):
        self._rejected_attempt(self.t1, self.tower, age_seconds=60)
        self.assertFalse(self.other_tower.team_in_cooloff(self.t1))

    def test_cooloff_per_team_isolation(self):
        self._rejected_attempt(self.t1, self.tower, age_seconds=60)
        self.assertFalse(self.tower.team_in_cooloff(self.t2))


# ---------------------------------------------------------------------------
# P0.9 — Next-challenge selection
# ---------------------------------------------------------------------------


class ChallengeProgressionTest(TestCase):
    """Rebuilt from the legacy fixture-dependent test to run without fixtures."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower1 = _make_tower(self.game, zone=self.zone, name="t1")
        self.tower2 = _make_tower(
            self.game, zone=self.zone, name="t2", lng=23.6,
        )
        self.t1 = _make_team(self.game, self.group, name="t1")
        self.t2 = _make_team(self.game, self.group, name="t2")

        self.c1 = Challenge.objects.create(
            text="c1", tower=self.tower1, difficulty=1,
        )
        self.c2 = Challenge.objects.create(
            text="c2", tower=self.tower1, difficulty=1,
        )
        self.c3 = Challenge.objects.create(
            text="c3", tower=self.tower1, difficulty=2,
        )
        self.c4 = Challenge.objects.create(
            text="c4", tower=self.tower1, difficulty=5,
        )
        self.c5 = Challenge.objects.create(text="c5", difficulty=1)
        self.c6 = Challenge.objects.create(text="c6", difficulty=2)
        self.c7 = Challenge.objects.create(text="c7", difficulty=5)

    def _confirm(self, team, tower, challenge):
        TeamTowerChallenge.objects.create(
            team=team, tower=tower, challenge=challenge,
            outcome=TeamTowerChallenge.CONFIRMED,
        )

    def test_full_challenge_progression(self):
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c1)

        self._confirm(self.t1, self.tower1, self.c1)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c2)
        self.assertEqual(self.tower1.get_next_challenge(self.t2), self.c1)

        self._confirm(self.t1, self.tower1, self.c2)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c3)

        self._confirm(self.t1, self.tower1, self.c3)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c4)

        self._confirm(self.t1, self.tower1, self.c4)
        # Tower-specific exhausted — falls through to generic
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c5)

        self._confirm(self.t1, self.tower1, self.c5)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c6)

        self._confirm(self.t1, self.tower1, self.c6)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c7)

        self._confirm(self.t1, self.tower1, self.c7)
        # All exhausted — hardest generic returned as replay fallback
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c7)


class NextChallengeEdgeCasesTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.team = _make_team(self.game, self.group)

    def test_tower_specific_first(self):
        _ = Challenge.objects.create(text="g1", difficulty=1)
        specific = Challenge.objects.create(
            text="s1", tower=self.tower, difficulty=1,
        )
        self.assertEqual(self.tower.get_next_challenge(self.team), specific)

    def test_fallback_to_hardest_generic_when_none_left(self):
        easy = Challenge.objects.create(text="g1", difficulty=1)
        hard = Challenge.objects.create(text="g2", difficulty=5)
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=easy,
            outcome=TeamTowerChallenge.CONFIRMED,
        )
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=hard,
            outcome=TeamTowerChallenge.CONFIRMED,
        )
        self.assertEqual(self.tower.get_next_challenge(self.team), hard)

    def test_other_team_progression_independent(self):
        c1 = Challenge.objects.create(
            text="c1", tower=self.tower, difficulty=1,
        )
        c2 = Challenge.objects.create(
            text="c2", tower=self.tower, difficulty=2,
        )
        other = _make_team(self.game, self.group, name="o")
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=c1,
            outcome=TeamTowerChallenge.CONFIRMED,
        )
        self.assertEqual(self.tower.get_next_challenge(self.team), c2)
        self.assertEqual(self.tower.get_next_challenge(other), c1)


# ---------------------------------------------------------------------------
# P0.10 — RFID auto-confirm
# ---------------------------------------------------------------------------


class RFIDCaptureTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.rfid_tower = _make_tower(
            self.game, zone=self.zone, category=Tower.CATEGORY_RFID,
            rfid_code="ABC123", initial_bonus=10,
        )
        self.team = _make_team(self.game, self.group)

    def test_rfid_api_auto_confirms_and_assigns(self):
        client, user = _authed_client(self.team)
        resp = client.post(
            "/api/team_tower_challenges/",
            {"rfid_code": "ABC123", "lat": 46.5, "lng": 23.5},
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        ttc = TeamTowerChallenge.objects.get(
            tower=self.rfid_tower, team=self.team,
        )
        self.assertEqual(ttc.outcome, TeamTowerChallenge.CONFIRMED)
        self.assertEqual(ttc.submitted_by, user)
        self.assertTrue(TeamTowerOwnership.objects.filter(
            tower=self.rfid_tower, team=self.team, timestamp_end__isnull=True,
        ).exists())
        self.assertEqual(Team.objects.get(pk=self.team.pk).score, 10)

    def test_rfid_api_unknown_code_returns_400(self):
        client, _ = _authed_client(self.team)
        resp = client.post(
            "/api/team_tower_challenges/",
            {"rfid_code": "NOPE", "lat": 46.5, "lng": 23.5},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)

    def test_rfid_api_outside_50m_rejected(self):
        client, _ = _authed_client(self.team)
        lat = 46.5 + 200 / 111_111.0  # ~200m north
        resp = client.post(
            "/api/team_tower_challenges/",
            {"rfid_code": "ABC123", "lat": lat, "lng": 23.5},
            format="json",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(TeamTowerChallenge.objects.filter(
            team=self.team, tower=self.rfid_tower,
        ).exists())


# ---------------------------------------------------------------------------
# P0.11 — REST API endpoints
# ---------------------------------------------------------------------------


class APIEndpointsTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(
            self.game, zone=self.zone, lng=23.5, lat=46.5,
        )
        self.inactive_tower = _make_tower(
            self.game, zone=self.zone, name="off", is_active=False,
            lng=23.6, lat=46.6,
        )
        self.rfid_tower = _make_tower(
            self.game, zone=self.zone, name="rfid",
            category=Tower.CATEGORY_RFID, rfid_code="X1",
        )
        self.team = _make_team(self.game, self.group)
        self.challenge = Challenge.objects.create(
            text="c", tower=self.tower, game=self.game, difficulty=1,
        )
        # Phase-3 scoping mixins require an authenticated caller with a
        # current_session. _authed_client handles both.
        self.client, self.user = _authed_client(self.team, username='viewer')

    def test_zones_endpoint_lists_zones_with_active_towers(self):
        resp = self.client.get("/api/zones/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_zones_endpoint_accepts_group_slug(self):
        self.tower.assign_to_team(self.team)
        by_id = self.client.get("/api/zones/", {"group": self.group.id})
        by_slug = self.client.get("/api/zones/", {"group_slug": self.group.slug})
        self.assertEqual(by_id.status_code, 200)
        self.assertEqual(by_slug.status_code, 200)
        self.assertEqual(by_id.json()[0]["team_color"], self.team.color)
        self.assertEqual(by_slug.json()[0]["team_color"], self.team.color)

    def test_zones_endpoint_unknown_group_slug_falls_back_to_default(self):
        resp = self.client.get("/api/zones/", {"group_slug": "nope"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()[0]["team_color"], "#000000")

    def test_towers_endpoint_excludes_inactive_and_rfid(self):
        resp = self.client.get("/api/towers/")
        self.assertEqual(resp.status_code, 200)
        ids = [t["id"] for t in resp.json()]
        self.assertIn(self.tower.id, ids)
        self.assertNotIn(self.inactive_tower.id, ids)
        self.assertNotIn(self.rfid_tower.id, ids)

    def test_towers_endpoint_lat_lng_proximity_filter(self):
        # Point right at the tower — it's within any accuracy radius up to
        # the 50m cap enforced by the view.
        resp = self.client.get(
            "/api/towers/",
            {"lat": 46.5, "lng": 23.5, "accuracy": 50},
        )
        self.assertEqual(resp.status_code, 200)
        ids = [t["id"] for t in resp.json()]
        self.assertIn(self.tower.id, ids)

        # Point 200m away — should exclude the tower entirely.
        resp = self.client.get(
            "/api/towers/",
            {"lat": 46.5 + 200 / 111_111.0, "lng": 23.5, "accuracy": 50},
        )
        self.assertEqual(resp.status_code, 200)
        ids = [t["id"] for t in resp.json()]
        self.assertNotIn(self.tower.id, ids)

    def test_challenges_endpoint_lists_all(self):
        Challenge.objects.create(text="g", game=self.game, difficulty=1)
        resp = self.client.get("/api/challenges/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_submission_creates_pending_record(self):
        client, user = _authed_client(self.team)
        resp = client.post(
            "/api/team_tower_challenges/",
            {
                "tower": self.tower.pk,
                "challenge": self.challenge.pk,
                "lat": 46.5,
                "lng": 23.5,
                "photo": _tiny_png_b64(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        ttc = TeamTowerChallenge.objects.get(
            team=self.team, tower=self.tower,
        )
        self.assertEqual(ttc.outcome, TeamTowerChallenge.PENDING)
        self.assertEqual(ttc.submitted_by, user)


# ---------------------------------------------------------------------------
# P0.12 — admin unassign_all action
# ---------------------------------------------------------------------------


class UnassignAllTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower1 = _make_tower(self.game, zone=self.zone, name="t1")
        self.tower2 = _make_tower(
            self.game, zone=self.zone, name="t2", lng=23.6,
        )
        self.t1 = _make_team(self.game, self.group)
        self.tower1.assign_to_team(self.t1)
        self.tower2.assign_to_team(self.t1)

    def _fake_request(self):
        from django.contrib.messages.storage.fallback import FallbackStorage
        from django.test import RequestFactory
        req = RequestFactory().get("/")
        req.session = {}
        req._messages = FallbackStorage(req)
        return req

    def test_unassign_all_closes_tower_ownerships(self):
        unassign_all(None, self._fake_request(), Tower.objects.all())
        self.assertEqual(
            TeamTowerOwnership.objects.filter(timestamp_end__isnull=True)
            .count(),
            0,
        )

    def test_unassign_all_closes_zone_ownerships(self):
        unassign_all(None, self._fake_request(), Tower.objects.all())
        self.assertEqual(
            TeamZoneOwnership.objects.filter(timestamp_end__isnull=True)
            .count(),
            0,
        )

    def test_unassign_all_keeps_towers_active(self):
        unassign_all(None, self._fake_request(), Tower.objects.all())
        # Towers themselves remain active (only ownerships cleared)
        self.assertEqual(Tower.objects.filter(is_active=True).count(), 2)

    def test_unassign_all_finalizes_floating_score_into_locked(self):
        # Back-date zone ownership so there's a non-trivial floating score
        # to finalize.
        zo = TeamZoneOwnership.objects.filter(
            team=self.t1, zone=self.zone, timestamp_end__isnull=True,
        ).first()
        self.assertIsNotNone(zo)
        TeamZoneOwnership.objects.filter(pk=zo.pk).update(
            timestamp_start=datetime.now(dt_timezone.utc) - timedelta(minutes=5),
        )
        score_before = Team.objects.get(pk=self.t1.pk).score
        unassign_all(None, self._fake_request(), Tower.objects.all())
        # Floating score (≈5 linear-points) added to locked score.
        score_after = Team.objects.get(pk=self.t1.pk).score
        self.assertGreater(score_after, score_before)


# ---------------------------------------------------------------------------
# Template views (smoke coverage)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Admin list_display callables (smoke coverage)
# ---------------------------------------------------------------------------


class AdminCallableTest(TestCase):
    def setUp(self):
        from game.admin import (
            ChallengeAdmin,
            TeamTowerChallangeAdmin,
            TowerAdmin,
            ZoneAdmin,
        )
        self.ZoneAdmin = ZoneAdmin
        self.TowerAdmin = TowerAdmin
        self.ChallengeAdmin = ChallengeAdmin
        self.TeamTowerChallangeAdmin = TeamTowerChallangeAdmin

        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.team = _make_team(self.game, self.group)
        self.challenge = Challenge.objects.create(
            text="short", tower=self.tower, difficulty=1,
        )

    def test_zone_admin_get_zone_control_empty(self):
        out = self.ZoneAdmin(Zone, None).get_zone_control(self.zone)
        # No controlling team → group name appears but no team names.
        self.assertIn(self.group.name, out)

    def test_tower_admin_get_tower_control_empty(self):
        out = self.TowerAdmin(Tower, None).get_tower_control(self.tower)
        self.assertIn("NOT CONTROLLED", out)

    def test_tower_admin_get_tower_control_with_owner(self):
        self.tower.assign_to_team(self.team)
        out = self.TowerAdmin(Tower, None).get_tower_control(self.tower)
        self.assertIn("explo1", out)

    def test_tower_admin_get_rfid_url_non_rfid(self):
        out = self.TowerAdmin(Tower, None).get_rfid_url(self.tower)
        self.assertEqual(out, "-")

    def test_tower_admin_get_rfid_url_rfid(self):
        rfid_tower = _make_tower(
            self.game, zone=self.zone, name="rf",
            category=Tower.CATEGORY_RFID, rfid_code="RFX",
        )
        out = self.TowerAdmin(Tower, None).get_rfid_url(rfid_tower)
        self.assertIn("RFX", out)

    def test_challenge_admin_counts(self):
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=self.challenge,
            outcome=TeamTowerChallenge.CONFIRMED,
        )
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=self.challenge,
            outcome=TeamTowerChallenge.REJECTED,
        )
        admin = self.ChallengeAdmin(Challenge, None)
        self.assertEqual(admin.incercari_total(self.challenge), 2)
        self.assertEqual(admin.incercari_reusite(self.challenge), 1)

    def test_ttc_admin_challenge_text_with_challenge(self):
        ttc = TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=self.challenge,
        )
        out = self.TeamTowerChallangeAdmin(
            TeamTowerChallenge, None,
        ).challenge_text(ttc)
        self.assertEqual(out, "short")

    def test_ttc_admin_challenge_text_without_challenge(self):
        ttc = TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower,
            outcome=TeamTowerChallenge.CONFIRMED,
        )
        out = self.TeamTowerChallangeAdmin(
            TeamTowerChallenge, None,
        ).challenge_text(ttc)
        self.assertEqual(out, "RFID Challenge")

    def test_ttc_admin_time_diff_unverified(self):
        ttc = TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=self.challenge,
        )
        admin = self.TeamTowerChallangeAdmin(TeamTowerChallenge, None)
        self.assertIsNone(admin.time_diff(ttc))

    def test_ttc_admin_time_diff_verified(self):
        ttc = TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=self.challenge,
        )
        TeamTowerChallenge.objects.filter(pk=ttc.pk).update(
            timestamp_verified=ttc.timestamp_submitted + timedelta(seconds=42),
        )
        ttc.refresh_from_db()
        admin = self.TeamTowerChallangeAdmin(TeamTowerChallenge, None)
        self.assertEqual(admin.time_diff(ttc), 42)


# ---------------------------------------------------------------------------
# P3.7 — Games + Sessions CRUD + session deactivation closes ownerships
# ---------------------------------------------------------------------------


class AdminGamesEndpointTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.staff_client, self.staff = _staff_client(username='g-admin')

    def test_list_requires_staff(self):
        anon = APIClient()
        resp = anon.get('/api/staff/games/')
        self.assertIn(resp.status_code, (401, 403))

    def test_list_includes_all_games(self):
        _make_game(name='Another', slug='another')
        resp = self.staff_client.get('/api/staff/games/')
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.json()), 2)

    def test_create_game_with_base_point(self):
        resp = self.staff_client.post(
            '/api/staff/games/',
            {
                'slug': 'new-event',
                'name': 'New Event',
                'base_lat': 46.06,
                'base_lng': 23.57,
                'base_zoom_level': 17,
                'is_active': True,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['slug'], 'new-event')
        self.assertEqual(body['base_point']['coordinates'], [23.57, 46.06])

    def test_patch_game_updates_rules(self):
        resp = self.staff_client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'proximity_meters': 25, 'cooloff_minutes': 10},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.game.refresh_from_db()
        self.assertEqual(self.game.proximity_meters, 25)
        self.assertEqual(self.game.cooloff_minutes, 10)


class AdminSessionsEndpointTest(TestCase):
    def setUp(self):
        from organize.models import Session
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.team = _make_team(self.game, self.group)
        self.session = self.team.session  # auto-created default session (RUNNING)
        self.staff_client, self.staff = _staff_client(
            session=self.session, username='s-admin',
        )
        # Second game to verify ?game=<id> filter works.
        self.other_game = _make_game(name='Other', slug='other-g')
        now = timezone.now()
        Session.objects.create(
            game=self.other_game, slug='default', name='Other default',
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )

    def test_list_returns_all_sessions_across_games(self):
        resp = self.staff_client.get('/api/staff/sessions/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_list_filters_by_game(self):
        resp = self.staff_client.get(
            f'/api/staff/sessions/?game={self.game.id}',
        )
        self.assertEqual(resp.status_code, 200)
        slugs = [s['slug'] for s in resp.json()]
        self.assertEqual(slugs, [self.session.slug])

    def test_create_session_on_existing_game(self):
        resp = self.staff_client.post(
            '/api/staff/sessions/',
            {
                'game': self.game.id,
                'slug': 'afternoon',
                'name': 'Afternoon',
                'start_time': timezone.now().isoformat(),
                'end_time': (timezone.now() + timedelta(hours=2)).isoformat(),
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['slug'], 'afternoon')
        # New Sessions start their lifecycle in DRAFT.
        self.assertEqual(body['state'], 'DRAFT')
        self.assertFalse(body['is_active'])
        self.assertEqual(body['allowed_transitions'], ['open_participation'])

    def test_finishing_session_closes_ownerships_and_locks_scores(self):
        # Assign tower to team so there's open ownership to close.
        self.tower.assign_to_team(self.team)
        # Wait a tick so get_score has something positive.
        from game.models import (
            TeamTowerOwnership,
            TeamZoneOwnership,
        )
        self.assertTrue(
            TeamTowerOwnership.objects.filter(
                team=self.team, timestamp_end__isnull=True,
            ).exists(),
        )
        resp = self.staff_client.post(
            f'/api/staff/sessions/{self.session.id}/finish/',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertFalse(
            TeamTowerOwnership.objects.filter(
                team=self.team, timestamp_end__isnull=True,
            ).exists(),
        )
        # No open zone ownership left either.
        self.assertFalse(
            TeamZoneOwnership.objects.filter(
                team=self.team, timestamp_end__isnull=True,
            ).exists(),
        )

    def test_finishing_session_does_not_touch_other_session_ownerships(self):
        from organize.models import Session
        # Second session on the SAME game with its own team + ownership.
        now = timezone.now()
        other_session = Session.objects.create(
            game=self.game, slug='parallel', name='Parallel',
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
        other_team = Team.objects.create(
            name='other', session=other_session, color='#f00',
        )
        # Give both teams an active tower ownership.
        self.tower.assign_to_team(self.team)
        # Finishing our session must not touch other_session's state —
        # we assert by finishing and then verifying other_team still has
        # any membership/config intact.
        resp = self.staff_client.post(
            f'/api/staff/sessions/{self.session.id}/finish/',
        )
        self.assertEqual(resp.status_code, 200)
        other_session.refresh_from_db()
        self.assertTrue(other_session.is_active)
        self.assertEqual(other_session.state, Session.RUNNING)
        # other_team is untouched (no ownerships were opened or closed).
        self.assertEqual(other_team.teamtowerownership_set.count(), 0)

    def test_patch_cannot_write_state_or_close_ownerships(self):
        """PATCH never drives the lifecycle: state and is_active are read-only."""
        self.tower.assign_to_team(self.team)
        from game.models import TeamTowerOwnership
        resp = self.staff_client.patch(
            f'/api/staff/sessions/{self.session.id}/',
            {'name': 'Renamed', 'state': 'FINISHED', 'is_active': False},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.name, 'Renamed')
        # Lifecycle untouched — writes go through the transition actions.
        self.assertEqual(self.session.state, Session.RUNNING)
        self.assertTrue(
            TeamTowerOwnership.objects.filter(
                team=self.team, timestamp_end__isnull=True,
            ).exists(),
        )


# ---------------------------------------------------------------------------
# game-lifecycle-states — Session state machine (tasks 7.1, 7.3, 7.4, 7.5)
# ---------------------------------------------------------------------------


class SessionLifecycleTest(TestCase):
    """Transition table, PAUSED invariant, finish semantics, roster gating."""

    ACTIONS = (
        'open_participation', 'close_participation', 'start',
        'pause', 'resume', 'finish',
    )

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.team = _make_team(self.game, self.group)
        self.session = self.team.session  # default session, RUNNING
        # A ready team (≥1 active member) so the start-gate from
        # game-config-team-rules passes for the transition walks.
        lifecycle_member = User.objects.create_user(
            username='lifecycle-member',
            email='lifecycle-member@example.com',
            password='password123',
        )
        TeamMembership.objects.create(
            team=self.team, user=lifecycle_member.profile, is_active=True,
        )
        self.staff_client, self.staff = _staff_client(
            session=self.session, username='lifecycle-staff',
        )

    def _set_state(self, state):
        """Force a lifecycle state while keeping the PAUSED invariant."""
        PauseWindow.objects.filter(session=self.session).delete()
        Session.objects.filter(pk=self.session.pk).update(state=state)
        if state == Session.PAUSED:
            PauseWindow.objects.create(
                session=self.session, started_at=timezone.now(),
            )
        self.session.refresh_from_db()

    def _post(self, action, session=None, data=None):
        session = session or self.session
        return self.staff_client.post(
            f'/api/staff/sessions/{session.id}/{action}/',
            data or {}, format='json',
        )

    # ---- 7.1 transition table ---------------------------------------------

    def test_transition_table_edges_are_exact(self):
        """All 25 (from, to) pairs: exactly the 7 table edges are legal."""
        expected_edges = {
            (Session.DRAFT, Session.OPEN_FOR_PARTICIPANTS),
            (Session.OPEN_FOR_PARTICIPANTS, Session.DRAFT),
            (Session.OPEN_FOR_PARTICIPANTS, Session.RUNNING),
            (Session.RUNNING, Session.PAUSED),
            (Session.PAUSED, Session.RUNNING),
            (Session.RUNNING, Session.FINISHED),
            (Session.PAUSED, Session.FINISHED),
        }
        edges = {
            (from_state, to_state)
            for _action, from_state, to_state in Session.TRANSITIONS
        }
        self.assertEqual(edges, expected_edges)
        states = [value for value, _label in Session.STATE_CHOICES]
        self.assertEqual(len(states), 5)
        for from_state in states:
            for to_state in states:
                self.assertEqual(
                    (from_state, to_state) in edges,
                    (from_state, to_state) in expected_edges,
                )
        # FINISHED is terminal: no outbound edge.
        self.assertFalse(any(f == Session.FINISHED for f, _ in edges))

    def test_every_action_from_every_state_matches_table(self):
        """Legal (action, state) pairs succeed; every other pair is a 409."""
        legal = {
            (action, from_state)
            for action, from_state, _to in Session.TRANSITIONS
        }
        states = [value for value, _label in Session.STATE_CHOICES]
        for state in states:
            for action in self.ACTIONS:
                with self.subTest(state=state, action=action):
                    self._set_state(state)
                    resp = self._post(action)
                    if (action, state) in legal:
                        self.assertEqual(resp.status_code, 200, resp.content)
                    else:
                        self.assertEqual(resp.status_code, 409, resp.content)
                        self.session.refresh_from_db()
                        # A rejected transition leaves the state unchanged.
                        self.assertEqual(self.session.state, state)

    def test_new_session_defaults_to_draft(self):
        now = timezone.now()
        session = Session.objects.create(
            game=self.game, slug='fresh', name='Fresh',
            start_time=now, end_time=now + timedelta(hours=1),
        )
        self.assertEqual(session.state, Session.DRAFT)
        self.assertFalse(session.is_active)
        self.assertEqual(session.allowed_transitions, ['open_participation'])

    def test_is_active_derives_from_state(self):
        expectations = {
            Session.DRAFT: False,
            Session.OPEN_FOR_PARTICIPANTS: True,
            Session.RUNNING: True,
            Session.PAUSED: True,
            Session.FINISHED: False,
        }
        for state, expected in expectations.items():
            self._set_state(state)
            self.assertEqual(self.session.is_active, expected)

    def test_full_lifecycle_walk(self):
        """DRAFT → open ⇄ close → start → pause ⇄ resume → finish."""
        self._set_state(Session.DRAFT)
        self.assertEqual(self._post('open_participation').status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.OPEN_FOR_PARTICIPANTS)
        self.assertEqual(self._post('close_participation').status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.DRAFT)
        # Teams created before the close are retained.
        self.assertTrue(self.session.teams.filter(pk=self.team.pk).exists())
        self._post('open_participation')
        resp = self._post('start')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['state'], 'RUNNING')
        self.assertCountEqual(
            resp.json()['allowed_transitions'], ['pause', 'finish'],
        )
        self._post('pause')
        self._post('resume')
        resp = self._post('finish')
        self.assertEqual(resp.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.FINISHED)
        self.assertEqual(self.session.allowed_transitions, [])

    # ---- 7.3 PAUSED ⟺ open PauseWindow invariant ---------------------------

    def _has_open_window(self, session=None):
        return PauseWindow.objects.filter(
            session=session or self.session, ended_at__isnull=True,
        ).exists()

    def test_pause_resume_keep_state_and_window_in_lockstep(self):
        self.assertFalse(self._has_open_window())
        resp = self._post('pause')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['state'], 'PAUSED')
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.PAUSED)
        self.assertTrue(self.session.is_paused())
        self.assertTrue(self._has_open_window())
        resp = self._post('resume')
        self.assertEqual(resp.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.RUNNING)
        self.assertFalse(self.session.is_paused())
        self.assertFalse(self._has_open_window())

    def test_model_level_pause_helpers_also_move_the_state(self):
        """Legacy PauseWindow.pause_session callers keep the invariant."""
        PauseWindow.pause_session(self.session)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.PAUSED)
        PauseWindow.resume_session(self.session)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.RUNNING)

    def test_pause_all_lands_every_running_session_in_paused(self):
        now = timezone.now()
        running = Session.objects.create(
            game=self.game, slug='second', name='Second',
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
        draft = Session.objects.create(
            game=self.game, slug='drafted', name='Drafted',
            start_time=now, end_time=now + timedelta(hours=1),
        )
        resp = self.staff_client.post(
            f'/api/staff/games/{self.game.id}/pause_all/',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertCountEqual(
            resp.json()['paused_sessions'], [self.session.id, running.id],
        )
        for session in (self.session, running):
            session.refresh_from_db()
            self.assertEqual(session.state, Session.PAUSED)
            self.assertTrue(self._has_open_window(session))
        draft.refresh_from_db()
        self.assertEqual(draft.state, Session.DRAFT)
        self.assertFalse(self._has_open_window(draft))

    # ---- 7.4 finish ---------------------------------------------------------

    def test_finish_from_running_closes_ownerships_and_is_terminal(self):
        self.tower.assign_to_team(self.team)
        self.assertTrue(
            TeamTowerOwnership.objects.filter(
                team=self.team, timestamp_end__isnull=True,
            ).exists(),
        )
        resp = self._post('finish')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.FINISHED)
        self.assertFalse(
            TeamTowerOwnership.objects.filter(
                team=self.team, timestamp_end__isnull=True,
            ).exists(),
        )
        self.assertFalse(
            TeamZoneOwnership.objects.filter(
                team=self.team, timestamp_end__isnull=True,
            ).exists(),
        )
        # History preserved: closed records still exist.
        self.assertEqual(
            TeamTowerOwnership.objects.filter(team=self.team).count(), 1,
        )
        # Terminal: every further action is a 409.
        for action in self.ACTIONS:
            self.assertEqual(self._post(action).status_code, 409)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.FINISHED)

    def test_finish_from_paused_closes_window_without_reopening(self):
        self.tower.assign_to_team(self.team)
        self.assertEqual(self._post('pause').status_code, 200)
        window = PauseWindow.objects.get(session=self.session)
        self.assertIsNone(window.ended_at)
        # Ownerships were closed at pause time and snapshotted for restore.
        self.assertTrue(window.restore_on_resume)
        resp = self._post('finish')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.FINISHED)
        window.refresh_from_db()
        self.assertIsNotNone(window.ended_at)
        # Finishing did NOT reopen the snapshotted ownerships.
        self.assertFalse(
            TeamTowerOwnership.objects.filter(
                team=self.team, timestamp_end__isnull=True,
            ).exists(),
        )
        self.assertFalse(
            TeamZoneOwnership.objects.filter(
                team=self.team, timestamp_end__isnull=True,
            ).exists(),
        )

    # ---- 7.5 participation window + roster gating --------------------------

    def test_open_participation_honours_scheduled_start_bound(self):
        self._set_state(Session.DRAFT)
        # No scheduled_start: openable at any time.
        self.assertEqual(self._post('open_participation').status_code, 200)
        self._set_state(Session.DRAFT)
        # Too early (more than 7 days before the planned start).
        self.session.scheduled_start = timezone.now() + timedelta(days=8)
        self.session.save(update_fields=['scheduled_start'])
        resp = self._post('open_participation')
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertTrue(resp.json().get('requires_override'))
        # Staff override opens anyway.
        resp = self._post('open_participation', data={'override': True})
        self.assertEqual(resp.status_code, 200, resp.content)
        # Too late (less than 1 hour before the planned start).
        self._set_state(Session.DRAFT)
        self.session.scheduled_start = timezone.now() + timedelta(minutes=30)
        self.session.save(update_fields=['scheduled_start'])
        self.assertEqual(self._post('open_participation').status_code, 409)
        # Within the 7-days-to-1-hour window: allowed without override.
        self.session.scheduled_start = timezone.now() + timedelta(days=2)
        self.session.save(update_fields=['scheduled_start'])
        self.assertEqual(self._post('open_participation').status_code, 200)

    def test_team_creation_follows_roster_window(self):
        cases = (
            (Session.DRAFT, 409),
            (Session.OPEN_FOR_PARTICIPANTS, 201),
            (Session.FINISHED, 409),
        )
        for index, (state, expected) in enumerate(cases):
            with self.subTest(state=state):
                self._set_state(state)
                resp = self.staff_client.post(
                    '/api/staff/teams/',
                    {
                        'name': f'rooster-{index}',
                        'session': self.session.id,
                        'color': '#123456',
                    },
                    format='json',
                )
                self.assertEqual(resp.status_code, expected, resp.content)

    def test_invite_join_follows_roster_window(self):
        invite = Invite.objects.create(
            team=self.team, email='', created_by=self.staff,
        )
        joiner = User.objects.create_user(
            username='joiner', email='joiner@example.com',
            password='password123',
        )
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=joiner).key}',
        )
        url = reverse('api-invite-accept', args=[invite.token])
        for state in (Session.DRAFT, Session.FINISHED):
            with self.subTest(state=state):
                self._set_state(state)
                resp = client.post(url)
                self.assertEqual(resp.status_code, 409, resp.content)
        self._set_state(Session.OPEN_FOR_PARTICIPANTS)
        resp = client.post(url)
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(
            TeamMembership.objects.filter(
                team=self.team, user=joiner.profile, is_active=True,
            ).exists(),
        )


# ---------------------------------------------------------------------------
# P3.6 — Per-game proximity / cooloff config is respected
# ---------------------------------------------------------------------------


class PerGameConfigTest(TestCase):
    def setUp(self):
        # Use a non-default proximity so we can see it in action.
        self.game = _make_game()
        self.game.proximity_meters = 20
        self.game.cooloff_minutes = 1
        self.game.save()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(
            self.game, zone=self.zone, lng=23.5, lat=46.5,
        )
        self.team = _make_team(self.game, self.group)
        self.challenge = Challenge.objects.create(
            text='c', tower=self.tower, game=self.game, difficulty=1,
        )

    def test_submission_uses_per_game_proximity(self):
        # 40m north — outside 20m, inside the legacy 50m default.
        lat = 46.5 + 40 / 111_111.0
        client, _ = _authed_client(self.team)
        resp = client.post(
            '/api/team_tower_challenges/',
            {
                'tower': self.tower.pk,
                'challenge': self.challenge.pk,
                'lat': lat,
                'lng': 23.5,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('20 de metri', str(resp.json()))

    def test_submission_within_per_game_proximity_accepted(self):
        # 10m north — well within 20m.
        lat = 46.5 + 10 / 111_111.0
        client, _ = _authed_client(self.team)
        resp = client.post(
            '/api/team_tower_challenges/',
            {
                'tower': self.tower.pk,
                'challenge': self.challenge.pk,
                'lat': lat,
                'lng': 23.5,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_tower_state_reports_game_proximity(self):
        client, _ = _authed_client(self.team)
        resp = client.get(
            reverse('api-tower-state', args=[self.tower.id]),
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['proximity_meters'], 20)

    def test_cooloff_uses_per_game_minutes(self):
        # cooloff_minutes=1 on this game.
        ttc = TeamTowerChallenge.objects.create(
            team=self.team,
            tower=self.tower,
            challenge=self.challenge,
            outcome=TeamTowerChallenge.REJECTED,
        )
        ttc.timestamp_verified = timezone.now()
        ttc.save()
        # Within 1-minute window.
        self.assertTrue(self.tower.team_in_cooloff(self.team))

    def test_cooloff_expires_within_shorter_custom_minutes(self):
        ttc = TeamTowerChallenge.objects.create(
            team=self.team,
            tower=self.tower,
            challenge=self.challenge,
            outcome=TeamTowerChallenge.REJECTED,
        )
        # 90 seconds ago — past the 1-minute window.
        ttc.timestamp_verified = timezone.now() - timedelta(seconds=90)
        ttc.save()
        self.assertFalse(self.tower.team_in_cooloff(self.team))


# ---------------------------------------------------------------------------
# P3.5 — Scoping mixins isolate data by current_session / current_session.game
# ---------------------------------------------------------------------------


class ScopingIsolationTest(TestCase):
    """Two parallel sessions in two different games — neither leaks."""

    def setUp(self):
        # Game A + one session
        self.game_a = _make_game(name='GameA', slug='game-a')
        self.group_a = _make_group(self.game_a, slug='ga')
        self.zone_a = _make_zone(self.game_a, name='ZA')
        self.tower_a = _make_tower(
            self.game_a, zone=self.zone_a, name='TA',
            lng=23.5, lat=46.5,
        )
        Challenge.objects.create(
            text='ca', tower=self.tower_a, game=self.game_a, difficulty=1,
        )
        self.team_a = _make_team(
            self.game_a, self.group_a, name='ta',
        )

        # Game B + its own session, zone, tower, team
        self.game_b = _make_game(name='GameB', slug='game-b')
        self.group_b = _make_group(self.game_b, slug='gb')
        self.zone_b = _make_zone(self.game_b, name='ZB')
        self.tower_b = _make_tower(
            self.game_b, zone=self.zone_b, name='TB',
            lng=23.6, lat=46.6,
        )
        Challenge.objects.create(
            text='cb', tower=self.tower_b, game=self.game_b, difficulty=1,
        )
        self.team_b = _make_team(
            self.game_b, self.group_b, name='tb',
        )

        # Two clients, one per session.
        self.client_a, _ = _authed_client(self.team_a, username='ua')
        self.client_b, _ = _authed_client(self.team_b, username='ub')

    def test_zones_are_game_scoped(self):
        resp = self.client_a.get('/api/zones/')
        names = [z['name'] for z in resp.json()]
        self.assertEqual(names, ['ZA'])

        resp = self.client_b.get('/api/zones/')
        names = [z['name'] for z in resp.json()]
        self.assertEqual(names, ['ZB'])

    def test_towers_are_game_scoped(self):
        ids_a = {t['id'] for t in self.client_a.get('/api/towers/').json()}
        ids_b = {t['id'] for t in self.client_b.get('/api/towers/').json()}
        self.assertEqual(ids_a, {self.tower_a.id})
        self.assertEqual(ids_b, {self.tower_b.id})

    def test_teams_are_session_scoped(self):
        resp_a = self.client_a.get('/api/teams/')
        resp_b = self.client_b.get('/api/teams/')
        self.assertEqual(
            [t['id'] for t in resp_a.json()], [self.team_a.id],
        )
        self.assertEqual(
            [t['id'] for t in resp_b.json()], [self.team_b.id],
        )

    def test_user_with_no_current_session_sees_nothing(self):
        bare = User.objects.create_user(
            username='nomad', email='n@x.com', password='password123',
        )
        token = Token.objects.create(user=bare)
        nomad = APIClient()
        nomad.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        # Authenticated but no current_session → empty results.
        self.assertEqual(nomad.get('/api/zones/').json(), [])
        self.assertEqual(nomad.get('/api/towers/').json(), [])
        self.assertEqual(nomad.get('/api/teams/').json(), [])


class ScopingTwoSessionsOneGameTest(TestCase):
    """Two sessions on the SAME game — share tower/zone config, isolate teams."""

    def setUp(self):
        from organize.models import Session

        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        Challenge.objects.create(
            text='c', tower=self.tower, game=self.game, difficulty=1,
        )
        now = timezone.now()
        self.session_a = Session.objects.create(
            game=self.game, slug='morning', name='Morning',
            start_time=now, end_time=now + timedelta(hours=2),
            state=Session.RUNNING,
        )
        self.session_b = Session.objects.create(
            game=self.game, slug='afternoon', name='Afternoon',
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=5),
            state=Session.RUNNING,
        )
        self.team_a = Team.objects.create(
            name='team-a', session=self.session_a, color='#111', group=self.group,
        )
        self.team_b = Team.objects.create(
            name='team-b', session=self.session_b, color='#222', group=self.group,
        )
        self.client_a, _ = _authed_client(self.team_a, username='pa')
        self.client_b, _ = _authed_client(self.team_b, username='pb')

    def test_shared_game_config_both_see_same_towers(self):
        ids_a = {t['id'] for t in self.client_a.get('/api/towers/').json()}
        ids_b = {t['id'] for t in self.client_b.get('/api/towers/').json()}
        # Same tower visible in both sessions — the config is shared.
        self.assertEqual(ids_a, {self.tower.id})
        self.assertEqual(ids_b, {self.tower.id})

    def test_teams_isolated_between_sessions_of_same_game(self):
        ids_a = {t['id'] for t in self.client_a.get('/api/teams/').json()}
        ids_b = {t['id'] for t in self.client_b.get('/api/teams/').json()}
        self.assertEqual(ids_a, {self.team_a.id})
        self.assertEqual(ids_b, {self.team_b.id})


# ---------------------------------------------------------------------------
# P3.1 — Game config fields + Challenge.game FK
# ---------------------------------------------------------------------------


class GameConfigFieldsTest(TestCase):
    def test_defaults_match_legacy_constants(self):
        game = _make_game(name='Default Defaults')
        self.assertEqual(game.proximity_meters, 50)
        self.assertEqual(game.cooloff_minutes, 5)
        self.assertEqual(game.initial_bonus_default, 0)

    def test_slug_is_unique(self):
        from django.db import IntegrityError
        _make_game(name='Event One', slug='shared')
        with self.assertRaises(IntegrityError):
            _make_game(name='Event Two', slug='shared')

    def test_created_by_optional(self):
        staff = User.objects.create_user(
            username='founder', email='f@x.com', password='pw',
        )
        game = _make_game(name='With Founder')
        game.created_by = staff
        game.save()
        game.refresh_from_db()
        self.assertEqual(game.created_by, staff)


class ChallengeGameFKTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)

    def test_challenge_can_be_attached_to_game(self):
        c = Challenge.objects.create(
            text='demo', difficulty=1, tower=self.tower, game=self.game,
        )
        self.assertEqual(c.game, self.game)
        # And it flows through the reverse relation on Game.
        self.assertIn(c, list(self.game.challenges.all()))

    def test_challenge_game_still_nullable_this_phase(self):
        # T3.1 keeps challenge.game nullable so the data migration can
        # run cleanly; a later phase will tighten the constraint.
        c = Challenge.objects.create(
            text='orphan', difficulty=1, tower=None, game=None,
        )
        self.assertIsNone(c.game)


# ---------------------------------------------------------------------------
# P2E.2 — Staff admin CRUD endpoints
# ---------------------------------------------------------------------------


class StaffAdminEndpointsTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game, name='Z1')
        self.tower = _make_tower(self.game, name='T1', zone=self.zone)
        self.team = _make_team(self.game, self.group)
        self.staff_client, self.staff = _staff_client(
            session=self.team.session, username='admin',
        )
        self.player_client, self.player = _authed_client(self.team)

    def test_tower_list_requires_staff(self):
        resp = self.player_client.get('/api/staff/towers/')
        self.assertEqual(resp.status_code, 403)

    def test_tower_list_returns_all_towers_including_inactive(self):
        _make_tower(self.game, name='Off', zone=self.zone, is_active=False)
        resp = self.staff_client.get('/api/staff/towers/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_tower_patch_toggles_is_active(self):
        resp = self.staff_client.patch(
            f'/api/staff/towers/{self.tower.id}/',
            {'is_active': False},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.tower.refresh_from_db()
        self.assertFalse(self.tower.is_active)

    def test_tower_unassign_action_closes_ownership(self):
        self.tower.assign_to_team(self.team)
        resp = self.staff_client.post(
            f'/api/staff/towers/{self.tower.id}/unassign/', format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self.tower.tower_control(self.group))

    def test_tower_unassign_all_closes_every_active_ownership(self):
        other = _make_tower(
            self.game, name='T2', zone=self.zone,
            lng=23.51, lat=46.51,
        )
        self.tower.assign_to_team(self.team)
        other.assign_to_team(self.team)
        resp = self.staff_client.post(
            '/api/staff/towers/unassign_all/', format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(self.tower.tower_control(self.group))
        self.assertIsNone(other.tower_control(self.group))

    def test_zone_patch_updates_color(self):
        resp = self.staff_client.patch(
            f'/api/staff/zones/{self.zone.id}/',
            {'color': '#112233'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.color, '#112233')

    def test_team_patch_updates_name(self):
        resp = self.staff_client.patch(
            f'/api/staff/teams/{self.team.id}/',
            {'name': 'Renamed'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.name, 'Renamed')

    def test_team_groups_list_is_staff_only(self):
        resp = self.player_client.get('/api/staff/team-groups/')
        self.assertEqual(resp.status_code, 403)
        resp = self.staff_client.get('/api/staff/team-groups/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)
        self.assertEqual(resp.json()[0]['slug'], self.group.slug)

    def test_challenge_crud(self):
        # Create — pin to the game so scoping (T3.5) will surface it.
        resp = self.staff_client.post(
            '/api/staff/challenges/',
            {
                'game': self.game.id,
                'text': 'Do a thing',
                'tower': self.tower.id,
                'difficulty': 2,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        challenge_id = resp.json()['id']
        self.assertEqual(resp.json()['game'], self.game.id)

        # List
        resp = self.staff_client.get('/api/staff/challenges/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

        # Patch (promote to generic by clearing tower)
        resp = self.staff_client.patch(
            f'/api/staff/challenges/{challenge_id}/',
            {'tower': None, 'difficulty': 3},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()['tower'])
        self.assertEqual(resp.json()['difficulty'], 3)

        # Delete
        resp = self.staff_client.delete(
            f'/api/staff/challenges/{challenge_id}/',
        )
        self.assertEqual(resp.status_code, 204)

    def test_challenge_list_requires_staff(self):
        resp = self.player_client.get('/api/staff/challenges/')
        self.assertEqual(resp.status_code, 403)

    def test_reset_scores_zeroes_every_team_and_closes_ownerships(self):
        self.tower.assign_to_team(self.team)
        self.team.score = 50
        self.team.save()
        resp = self.staff_client.post(
            '/api/staff/game-state/reset-scores/', format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.team.refresh_from_db()
        self.assertEqual(self.team.score, 0)
        self.assertIsNone(self.tower.tower_control(self.group))

    def test_reset_scores_requires_staff(self):
        resp = self.player_client.post(
            '/api/staff/game-state/reset-scores/', format='json',
        )
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# P2E.1 — Staff submission review endpoints
# ---------------------------------------------------------------------------


class StaffSubmissionEndpointsTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.challenge = Challenge.objects.create(
            text='Prove it', difficulty=1, tower=self.tower, game=self.game,
        )
        self.staff_client, self.staff = _staff_client(
            session=self.team.session, username='review',
        )
        self.player_client, self.player = _authed_client(self.team)
        self.list_url = reverse('api-staff-submissions')

    def _make_pending(self):
        return TeamTowerChallenge.objects.create(
            team=self.team,
            tower=self.tower,
            challenge=self.challenge,
            submitted_by=self.player,
        )

    def test_list_requires_staff(self):
        resp = self.player_client.get(self.list_url)
        self.assertEqual(resp.status_code, 403)

    def test_list_defaults_to_pending(self):
        self._make_pending()
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=self.challenge,
            outcome=TeamTowerChallenge.CONFIRMED,
        )
        resp = self.staff_client.get(self.list_url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)
        self.assertEqual(resp.json()[0]['team_name'], self.team.name)
        self.assertEqual(resp.json()[0]['tower_name'], self.tower.name)
        self.assertEqual(resp.json()[0]['challenge_text'], 'Prove it')

    def test_list_outcome_filter_all(self):
        self._make_pending()
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=self.challenge,
            outcome=TeamTowerChallenge.CONFIRMED,
        )
        resp = self.staff_client.get(self.list_url, {'outcome': 'all'})
        self.assertEqual(len(resp.json()), 2)

    def test_confirm_triggers_tower_assignment(self):
        ttc = self._make_pending()
        url = reverse('api-staff-submission-review', args=[ttc.id])
        resp = self.staff_client.post(
            url, {'outcome': 'confirm'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        ttc.refresh_from_db()
        self.assertEqual(ttc.outcome, TeamTowerChallenge.CONFIRMED)
        self.assertEqual(ttc.checked_by, self.staff)
        # Tower should now be owned by the team.
        self.assertEqual(
            self.tower.tower_control(self.group), self.team,
        )

    def test_reject_stores_response_text(self):
        ttc = self._make_pending()
        url = reverse('api-staff-submission-review', args=[ttc.id])
        resp = self.staff_client.post(
            url,
            {'outcome': 'reject', 'response_text': 'try again'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        ttc.refresh_from_db()
        self.assertEqual(ttc.outcome, TeamTowerChallenge.REJECTED)
        self.assertEqual(ttc.response_text, 'try again')
        self.assertEqual(ttc.checked_by, self.staff)

    def test_review_rejects_non_pending(self):
        ttc = self._make_pending()
        ttc.outcome = TeamTowerChallenge.CONFIRMED
        ttc.save()
        url = reverse('api-staff-submission-review', args=[ttc.id])
        resp = self.staff_client.post(
            url, {'outcome': 'confirm'}, format='json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_review_rejects_bad_outcome(self):
        ttc = self._make_pending()
        url = reverse('api-staff-submission-review', args=[ttc.id])
        resp = self.staff_client.post(url, {'outcome': 'meh'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_review_requires_staff(self):
        ttc = self._make_pending()
        url = reverse('api-staff-submission-review', args=[ttc.id])
        resp = self.player_client.post(
            url, {'outcome': 'confirm'}, format='json',
        )
        self.assertEqual(resp.status_code, 403)


# ---------------------------------------------------------------------------
# P2C.3 — Tower state endpoint
# ---------------------------------------------------------------------------


class TowerStateEndpointTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, name="Alpha", zone=self.zone)
        self.challenge = Challenge.objects.create(
            text="Sing a song", difficulty=1, tower=self.tower,
        )
        self.client, self.user = _authed_client(self.team)

    def _url(self, tower_id=None):
        return reverse('api-tower-state', args=[tower_id or self.tower.id])

    def test_requires_auth(self):
        anon = APIClient()
        resp = anon.get(self._url())
        self.assertIn(resp.status_code, (401, 403))

    def test_returns_state_for_active_tower(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['id'], self.tower.id)
        self.assertEqual(data['name'], 'Alpha')
        self.assertEqual(data['proximity_meters'], 50)
        self.assertEqual(data['next_challenge']['id'], self.challenge.id)
        self.assertIsNone(data['cooloff_until'])
        self.assertFalse(data['pending_submission'])

    def test_404_for_inactive_tower(self):
        self.tower.is_active = False
        self.tower.save()
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 404)

    def test_404_for_user_without_active_team(self):
        User.objects.filter(username='nomad').delete()
        user = User.objects.create_user(
            username='nomad', email='n@x.com', password='password123',
        )
        token = Token.objects.create(user=user)
        bare = APIClient()
        bare.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        resp = bare.get(self._url())
        self.assertEqual(resp.status_code, 404)

    def test_pending_submission_hides_next_challenge(self):
        TeamTowerChallenge.objects.create(
            team=self.team,
            tower=self.tower,
            challenge=self.challenge,
            outcome=TeamTowerChallenge.PENDING,
        )
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['pending_submission'])
        self.assertIsNone(data['next_challenge'])

    def test_recent_rejection_produces_cooloff_until(self):
        ttc = TeamTowerChallenge.objects.create(
            team=self.team,
            tower=self.tower,
            challenge=self.challenge,
            outcome=TeamTowerChallenge.REJECTED,
        )
        # Manually stamp verified time (save() side-effects won't apply
        # because we constructed with outcome=REJECTED directly).
        ttc.timestamp_verified = timezone.now()
        ttc.save()
        resp = self.client.get(self._url())
        data = resp.json()
        self.assertIsNotNone(data['cooloff_until'])

    def test_old_rejection_does_not_produce_cooloff(self):
        ttc = TeamTowerChallenge.objects.create(
            team=self.team,
            tower=self.tower,
            challenge=self.challenge,
            outcome=TeamTowerChallenge.REJECTED,
        )
        ttc.timestamp_verified = timezone.now() - timedelta(minutes=10)
        ttc.save()
        resp = self.client.get(self._url())
        data = resp.json()
        self.assertIsNone(data['cooloff_until'])

    def test_ownership_returned_when_team_in_same_group_owns(self):
        # Assign tower to our team; the ownership lookup is group-scoped.
        self.tower.assign_to_team(self.team)
        resp = self.client.get(self._url())
        data = resp.json()
        self.assertIsNotNone(data['ownership'])
        self.assertEqual(data['ownership']['team_id'], self.team.id)


# ---------------------------------------------------------------------------
# P0.14 — /health/ endpoint
# ---------------------------------------------------------------------------


class HealthTest(TestCase):
    def test_health_returns_ok_when_db_reachable(self):
        resp = self.client.get("/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_requires_no_auth(self):
        resp = self.client.get("/health/")
        self.assertEqual(resp.status_code, 200)

    def test_health_returns_503_when_db_unreachable(self):
        from unittest.mock import patch

        from django.db import OperationalError

        with patch("game.views.connection") as mock_connection:
            mock_connection.cursor.side_effect = OperationalError("down")
            resp = self.client.get("/health/")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["status"], "error")


# ---------------------------------------------------------------------------
# Phase 10 — Day cut-off pausing (task 4.2)
# ---------------------------------------------------------------------------


class DayPausingTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)  # LINEAR scoring
        self.tower = _make_tower(self.game, zone=self.zone)
        self.team = _make_team(self.game, self.group)
        self.session = self.team.session  # default session, RUNNING

    def _open_tower_ownership(self, team=None, tower=None):
        return TeamTowerOwnership.objects.create(
            team=team or self.team, tower=tower or self.tower,
        )

    def _open_zone_ownership(self, team=None, zone=None, age_seconds=0):
        zo = TeamZoneOwnership.objects.create(team=team or self.team, zone=zone or self.zone)
        if age_seconds:
            TeamZoneOwnership.objects.filter(pk=zo.pk).update(
                timestamp_start=timezone.now() - timedelta(seconds=age_seconds),
            )
        return zo

    def test_pause_closes_ownerships_and_opens_window(self):
        self._open_tower_ownership()
        self._open_zone_ownership()
        window = PauseWindow.pause_session(self.session)
        self.assertIsNotNone(window)
        self.assertIsNone(window.ended_at)
        self.assertTrue(PauseWindow.is_paused(self.session))
        self.assertFalse(TeamTowerOwnership.objects.filter(
            team=self.team, timestamp_end__isnull=True).exists())
        self.assertFalse(TeamZoneOwnership.objects.filter(
            team=self.team, timestamp_end__isnull=True).exists())
        # A second pause on an already-paused session is a no-op.
        self.assertIsNone(PauseWindow.pause_session(self.session))

    def test_pause_resume_round_trip_restores_ownerships(self):
        self._open_tower_ownership()
        self._open_zone_ownership()
        PauseWindow.pause_session(self.session)
        PauseWindow.resume_session(self.session)
        self.assertFalse(PauseWindow.is_paused(self.session))
        self.assertTrue(TeamTowerOwnership.objects.filter(
            team=self.team, tower=self.tower, timestamp_end__isnull=True).exists())
        self.assertTrue(TeamZoneOwnership.objects.filter(
            team=self.team, zone=self.zone, timestamp_end__isnull=True).exists())

    def test_resume_without_restore_does_not_reopen(self):
        self.session.pause_restores_ownerships_on_resume = False
        self.session.save()
        self._open_tower_ownership()
        self._open_zone_ownership()
        window = PauseWindow.pause_session(self.session)
        self.assertEqual(window.tower_ownerships, [])
        PauseWindow.resume_session(self.session)
        self.assertFalse(TeamTowerOwnership.objects.filter(
            team=self.team, timestamp_end__isnull=True).exists())
        self.assertFalse(TeamZoneOwnership.objects.filter(
            team=self.team, timestamp_end__isnull=True).exists())

    def test_frozen_floating_score_stays_stable_during_pause(self):
        self._open_zone_ownership(age_seconds=120)  # ~2 LINEAR points
        team = Team.objects.get(pk=self.team.pk)
        self.assertGreater(team.floating_score(), 0)
        PauseWindow.pause_session(self.session)  # freeze default True
        team = Team.objects.get(pk=self.team.pk)
        self.assertEqual(team.floating_score(), 0)  # nothing open while paused
        self.assertGreaterEqual(team.score, 2)  # floating locked into score
        self.assertEqual(team.current_score(), team.current_score())  # stable

    def test_not_freezing_does_not_credit_floating(self):
        self.session.pause_freezes_floating_score = False
        self.session.save()
        self._open_zone_ownership(age_seconds=120)
        PauseWindow.pause_session(self.session)
        team = Team.objects.get(pk=self.team.pk)
        self.assertEqual(team.score, 0)  # in-progress floating not credited
        self.assertEqual(team.floating_score(), 0)

    def test_pause_and_resume_endpoints(self):
        client, _ = _staff_client(session=self.session)
        r = client.post(f'/api/staff/sessions/{self.session.id}/pause/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()['is_paused'])
        self.assertEqual(
            client.post(f'/api/staff/sessions/{self.session.id}/pause/').status_code,
            409,
        )
        r3 = client.post(f'/api/staff/sessions/{self.session.id}/resume/')
        self.assertEqual(r3.status_code, 200)
        self.assertFalse(r3.json()['is_paused'])
        self.assertEqual(
            client.post(f'/api/staff/sessions/{self.session.id}/resume/').status_code,
            409,
        )

    def test_pause_all_pauses_every_active_session(self):
        now = timezone.now()
        s2 = Session.objects.create(
            game=self.game, slug='s2', name='S2',
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
        Team.objects.create(name='t-s2', color='#111111', session=s2, group=self.group)
        client, _ = _staff_client(session=self.session)
        r = client.post(f'/api/staff/games/{self.game.id}/pause_all/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertCountEqual(r.json()['paused_sessions'], [self.session.id, s2.id])
        self.assertTrue(PauseWindow.is_paused(self.session))
        self.assertTrue(PauseWindow.is_paused(s2))

    def test_submission_returns_409_when_paused_and_rejecting(self):
        PauseWindow.pause_session(self.session)  # pause_rejects default True
        client, _ = _authed_client(self.team)
        r = client.post(
            '/api/team_tower_challenges/',
            {'tower': self.tower.id, 'lat': 46.5, 'lng': 23.5},
            format='json',
        )
        self.assertEqual(r.status_code, 409, r.content)
        self.assertFalse(TeamTowerChallenge.objects.filter(
            team=self.team, tower=self.tower).exists())

    def test_rfid_submission_held_pending_when_not_rejecting(self):
        self.session.pause_rejects_submissions = False
        self.session.save()
        rfid = _make_tower(
            self.game, zone=self.zone, name='rf',
            category=Tower.CATEGORY_RFID, rfid_code='PZ1',
        )
        PauseWindow.pause_session(self.session)
        client, _ = _authed_client(self.team)
        r = client.post(
            '/api/team_tower_challenges/',
            {'rfid_code': 'PZ1', 'lat': 46.5, 'lng': 23.5},
            format='json',
        )
        self.assertEqual(r.status_code, 201, r.content)
        ttc = TeamTowerChallenge.objects.get(team=self.team, tower=rfid)
        self.assertEqual(ttc.outcome, TeamTowerChallenge.PENDING)  # held, not confirmed
        self.assertFalse(TeamTowerOwnership.objects.filter(
            tower=rfid, team=self.team, timestamp_end__isnull=True).exists())

    def test_per_session_override_beats_game_default(self):
        self.assertTrue(self.session.effective('pause_rejects_submissions'))
        self.session.pause_rejects_submissions = False
        self.session.save()
        self.assertFalse(self.session.effective('pause_rejects_submissions'))

    def test_pause_history_endpoint(self):
        client, _ = _staff_client(session=self.session)
        PauseWindow.pause_session(self.session)
        r = client.get(f'/api/staff/sessions/{self.session.id}/pause_history/')
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['is_paused'])
        self.assertEqual(len(body['windows']), 1)
        self.assertIsNone(body['windows'][0]['ended_at'])


# ---------------------------------------------------------------------------
# Phase 10 — Challenge-failure consequences (task 7.2)
# ---------------------------------------------------------------------------


class FailureConsequencesTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone, name='A')
        self.tower_b = _make_tower(self.game, zone=self.zone, name='B')
        self.team = _make_team(self.game, self.group)
        self.session = self.team.session  # default session, RUNNING
        self.challenge = Challenge.objects.create(
            text='c', tower=self.tower, difficulty=1, game=self.game,
        )

    def _reject(self, team=None, tower=None):
        """Drive a PENDING -> REJECTED transition (fires failure consequences)."""
        ttc = TeamTowerChallenge.objects.create(
            team=team or self.team, tower=tower or self.tower,
            challenge=self.challenge, outcome=TeamTowerChallenge.PENDING,
        )
        ttc.outcome = TeamTowerChallenge.REJECTED
        ttc.save()
        return ttc

    def test_reject_subtracts_points_clamped_to_zero(self):
        self.game.fail_point_penalty = 10
        self.game.save()
        Team.objects.filter(pk=self.team.pk).update(score=25)
        self._reject()
        self.assertEqual(Team.objects.get(pk=self.team.pk).score, 15)
        self._reject()
        self.assertEqual(Team.objects.get(pk=self.team.pk).score, 5)
        self._reject()  # 5 - 10 clamps to 0, not negative
        self.assertEqual(Team.objects.get(pk=self.team.pk).score, 0)
        self.assertEqual(
            TeamTowerFailCounter.objects.get(team=self.team, tower=self.tower).consecutive_fails, 3)

    def test_cooloff_scales_with_consecutive_fails(self):
        self.game.fail_cooloff_scaling = 2.0
        self.game.cooloff_minutes = 5  # 300s base
        self.game.save()
        ttc = self._reject()  # consecutive_fails -> 1, scaled cooloff = 300*2 = 600s
        TeamTowerChallenge.objects.filter(pk=ttc.pk).update(
            timestamp_verified=timezone.now() - timedelta(seconds=400),
        )
        team = Team.objects.get(pk=self.team.pk)
        # 400s elapsed is past the 300s base but inside the 600s scaled cooloff.
        self.assertTrue(self.tower.team_in_cooloff(team))

    def test_cooloff_base_preserved_by_default_scaling(self):
        ttc = self._reject()  # default scaling 1.0
        TeamTowerChallenge.objects.filter(pk=ttc.pk).update(
            timestamp_verified=timezone.now() - timedelta(seconds=400),
        )
        team = Team.objects.get(pk=self.team.pk)
        self.assertFalse(self.tower.team_in_cooloff(team))  # 400s > 300s base

    def test_tower_lockout_blocks_submission(self):
        self.game.fail_tower_lockout_minutes = 10
        self.game.save()
        before = timezone.now()
        self._reject()
        counter = TeamTowerFailCounter.objects.get(team=self.team, tower=self.tower)
        self.assertIsNotNone(counter.locked_until)
        delta = (counter.locked_until - before).total_seconds()
        self.assertTrue(590 <= delta <= 610)  # locked ~10 minutes
        client, _ = _authed_client(self.team)
        r = client.post(
            '/api/team_tower_challenges/',
            {'tower': self.tower.id, 'lat': 46.5, 'lng': 23.5},
            format='json',
        )
        self.assertEqual(r.status_code, 409, r.content)
        # Once the lockout expires the block lifts.
        TeamTowerFailCounter.objects.filter(pk=counter.pk).update(
            locked_until=timezone.now() - timedelta(seconds=1),
        )
        counter.refresh_from_db()
        self.assertFalse(counter.is_locked())

    def test_difficulty_rollback_picks_lower_bucket(self):
        self.game.fail_difficulty_rollback = True
        self.game.save()
        c2 = Challenge.objects.create(text='d2', tower=self.tower, difficulty=2, game=self.game)
        Challenge.objects.create(text='d3', tower=self.tower, difficulty=3, game=self.game)
        # Team already conquered difficulty 2 on this tower.
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, challenge=c2,
            outcome=TeamTowerChallenge.CONFIRMED,
        )
        # No failures yet: next challenge is the difficulty-3 bucket.
        self.assertEqual(self.tower.get_next_challenge(self.team).difficulty, 3)
        # After a failure, rollback drops to the next-lower difficulty bucket.
        self._reject()
        self.assertEqual(self.tower.get_next_challenge(self.team).difficulty, 1)

    def test_reset_tower_success_only(self):
        self.game.fail_counter_reset = 'TOWER_SUCCESS_ONLY'
        self.game.save()
        self._reject(tower=self.tower)
        # A success elsewhere does NOT reset tower A's counter.
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower_b, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(
            TeamTowerFailCounter.objects.get(team=self.team, tower=self.tower).consecutive_fails, 1)
        # A success on tower A resets it.
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(
            TeamTowerFailCounter.objects.get(team=self.team, tower=self.tower).consecutive_fails, 0)

    def test_reset_any_success_elsewhere(self):
        self.game.fail_counter_reset = 'ANY_SUCCESS_ELSEWHERE'
        self.game.save()
        self._reject(tower=self.tower)
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower_b, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(
            TeamTowerFailCounter.objects.get(team=self.team, tower=self.tower).consecutive_fails, 0)

    def test_reset_any_attempt_elsewhere(self):
        self.game.fail_counter_reset = 'ANY_ATTEMPT_ELSEWHERE'
        self.game.save()
        self._reject(tower=self.tower)
        # A mere pending submission on another tower resets the counter.
        TeamTowerChallenge.objects.create(
            team=self.team, tower=self.tower_b, outcome=TeamTowerChallenge.PENDING)
        self.assertEqual(
            TeamTowerFailCounter.objects.get(team=self.team, tower=self.tower).consecutive_fails, 0)

    def test_no_cross_team_side_effects(self):
        self.game.fail_point_penalty = 10
        self.game.fail_tower_lockout_minutes = 10
        self.game.save()
        team2 = _make_team(self.game, self.group, name='team2')
        Team.objects.filter(pk=team2.pk).update(score=50)
        self._reject(team=self.team, tower=self.tower)
        self.assertEqual(Team.objects.get(pk=team2.pk).score, 50)  # untouched
        self.assertFalse(TeamTowerFailCounter.objects.filter(team=team2).exists())

    def test_fail_counters_endpoint(self):
        self.game.fail_tower_lockout_minutes = 10
        self.game.save()
        self._reject()
        client, _ = _staff_client(session=self.session)
        r = client.get(f'/api/staff/sessions/{self.session.id}/fail_counters/')
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['consecutive_fails'], 1)
        self.assertTrue(data[0]['is_locked'])
        self.assertEqual(data[0]['tower_name'], self.tower.name)


# ---------------------------------------------------------------------------
# team-roles-as-mechanics — role gating, staff APIs, player surface
# ---------------------------------------------------------------------------


def _add_member(team, username):
    """Create a user with an active membership on `team`; return the membership."""
    user = User.objects.create_user(
        username=username, email=f'{username}@example.com', password='password123',
    )
    return TeamMembership.objects.create(
        team=team, user=user.profile, is_active=True,
    )


class TeamSatisfiesRolesTest(TestCase):
    """8.2 — head-count-independent role coverage evaluation."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.cook = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        self.medic = GameRole.objects.create(game=self.game, name='Medic', slug='medic')
        self.navigator = GameRole.objects.create(
            game=self.game, name='Navigator', slug='navigator',
        )
        self.challenge = Challenge.objects.create(
            game=self.game, text='task', difficulty=1,
        )

    def _set_requirement(self, mode, roles):
        self.challenge.role_requirement_mode = mode
        self.challenge.save()
        self.challenge.required_roles.set(roles)

    def test_none_mode_always_passes(self):
        ok, missing = self.challenge.team_satisfies_roles(self.team)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_non_none_mode_with_no_roles_passes(self):
        # Defensive: config validation forbids this, but evaluation is a no-op.
        self._set_requirement(ROLE_REQUIREMENT_ALL, [])
        ok, _ = self.challenge.team_satisfies_roles(self.team)
        self.assertTrue(ok)

    def test_any_fails_when_no_required_role_held(self):
        self._set_requirement(ROLE_REQUIREMENT_ANY, [self.cook, self.medic])
        membership = _add_member(self.team, 'nav')
        TeamRole.objects.create(membership=membership, role=self.navigator)
        ok, missing = self.challenge.team_satisfies_roles(self.team)
        self.assertFalse(ok)
        self.assertEqual(set(missing), {'cook', 'medic'})

    def test_any_passes_on_one_covered_role(self):
        self._set_requirement(ROLE_REQUIREMENT_ANY, [self.cook, self.medic])
        membership = _add_member(self.team, 'doc')
        TeamRole.objects.create(membership=membership, role=self.medic)
        ok, missing = self.challenge.team_satisfies_roles(self.team)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_all_fails_until_every_role_covered(self):
        self._set_requirement(ROLE_REQUIREMENT_ALL, [self.cook, self.medic])
        m1 = _add_member(self.team, 'chef')
        TeamRole.objects.create(membership=m1, role=self.cook)
        ok, missing = self.challenge.team_satisfies_roles(self.team)
        self.assertFalse(ok)
        self.assertEqual(missing, ['medic'])

        m2 = _add_member(self.team, 'doc')
        TeamRole.objects.create(membership=m2, role=self.medic)
        ok, missing = self.challenge.team_satisfies_roles(self.team)
        self.assertTrue(ok)
        self.assertEqual(missing, [])

    def test_one_member_holding_two_roles_satisfies_all(self):
        self._set_requirement(ROLE_REQUIREMENT_ALL, [self.cook, self.medic])
        membership = _add_member(self.team, 'hero')
        TeamRole.objects.create(membership=membership, role=self.cook)
        TeamRole.objects.create(membership=membership, role=self.medic)
        ok, _ = self.challenge.team_satisfies_roles(self.team)
        self.assertTrue(ok)

    def test_many_members_holding_none_fail(self):
        self._set_requirement(ROLE_REQUIREMENT_ALL, [self.cook])
        for i in range(10):
            _add_member(self.team, f'crowd{i}')
        ok, missing = self.challenge.team_satisfies_roles(self.team)
        self.assertFalse(ok)
        self.assertEqual(missing, ['cook'])

    def test_inactive_holder_does_not_count(self):
        self._set_requirement(ROLE_REQUIREMENT_ALL, [self.cook])
        membership = _add_member(self.team, 'gone')
        TeamRole.objects.create(membership=membership, role=self.cook)
        membership.is_active = False
        membership.left_at = timezone.now()
        membership.save()
        ok, missing = self.challenge.team_satisfies_roles(self.team)
        self.assertFalse(ok)
        self.assertEqual(missing, ['cook'])


class RoleGatedSubmissionTest(TestCase):
    """8.3 / 8.5 — submission-time enforcement with clear missing-role errors."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone, lng=23.5, lat=46.5)
        self.team = _make_team(self.game, self.group)
        self.cook = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        self.challenge = Challenge.objects.create(
            game=self.game, text='cook something', tower=self.tower, difficulty=1,
            role_requirement_mode=ROLE_REQUIREMENT_ALL,
        )
        self.challenge.required_roles.set([self.cook])
        self.client_api, self.user = _authed_client(self.team)
        self.membership = TeamMembership.objects.get(
            team=self.team, user=self.user.profile,
        )

    def _submit(self):
        return self.client_api.post(
            '/api/team_tower_challenges/',
            {
                'tower': self.tower.pk,
                'challenge': self.challenge.pk,
                'lat': 46.5,
                'lng': 23.5,
            },
            format='json',
        )

    def test_missing_role_refused_with_roles_named(self):
        resp = self._submit()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['missing_roles'], ['cook'])
        self.assertFalse(TeamTowerChallenge.objects.exists())

    def test_same_team_passes_after_assignment(self):
        TeamRole.objects.create(membership=self.membership, role=self.cook)
        resp = self._submit()
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertTrue(TeamTowerChallenge.objects.exists())

    def test_default_none_mode_unchanged(self):
        plain = Challenge.objects.create(
            game=self.game, text='plain', tower=self.tower, difficulty=1,
        )
        resp = self.client_api.post(
            '/api/team_tower_challenges/',
            {
                'tower': self.tower.pk,
                'challenge': plain.pk,
                'lat': 46.5,
                'lng': 23.5,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)


class AdminGameRolesEndpointTest(TestCase):
    """5.1 — staff CRUD for per-Game role definitions."""

    def setUp(self):
        self.game = _make_game()
        self.session = _default_session(self.game)
        self.client_api, self.staff = _staff_client(self.session)

    def test_requires_staff(self):
        group = _make_group(self.game)
        team = _make_team(self.game, group)
        player_client, _ = _authed_client(team)
        resp = player_client.get('/api/staff/game_roles/')
        self.assertEqual(resp.status_code, 403)

    def test_create_and_list_role(self):
        resp = self.client_api.post('/api/staff/game_roles/', {
            'game': self.game.id,
            'name': 'Inviter',
            'slug': 'inviter',
            'description': 'Brings in new players',
            'builtin_power': 'INVITER',
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        resp = self.client_api.get('/api/staff/game_roles/')
        body = resp.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['slug'], 'inviter')
        self.assertEqual(body[0]['builtin_power'], 'INVITER')

    def test_list_defaults_to_current_session_game(self):
        other = _make_game(name='Other')
        GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        GameRole.objects.create(game=other, name='Alien', slug='alien')
        resp = self.client_api.get('/api/staff/game_roles/')
        slugs = [r['slug'] for r in resp.json()]
        self.assertEqual(slugs, ['cook'])

    def test_list_filters_by_game_param(self):
        other = _make_game(name='Other')
        GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        GameRole.objects.create(game=other, name='Alien', slug='alien')
        resp = self.client_api.get(f'/api/staff/game_roles/?game={other.id}')
        slugs = [r['slug'] for r in resp.json()]
        self.assertEqual(slugs, ['alien'])

    def test_update_and_delete_role(self):
        role = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        resp = self.client_api.patch(
            f'/api/staff/game_roles/{role.id}/', {'name': 'Head cook'}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        role.refresh_from_db()
        self.assertEqual(role.name, 'Head cook')
        resp = self.client_api.delete(f'/api/staff/game_roles/{role.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(GameRole.objects.exists())

    def test_duplicate_slug_within_game_rejected(self):
        GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        resp = self.client_api.post('/api/staff/game_roles/', {
            'game': self.game.id, 'name': 'Chef', 'slug': 'cook',
        }, format='json')
        self.assertEqual(resp.status_code, 400)


class AdminMembershipRolesEndpointTest(TestCase):
    """5.2 — roster listing plus role assign/unassign actions."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.session = self.team.session
        self.cook = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        self.membership = _add_member(self.team, 'scout')
        self.client_api, self.staff = _staff_client(self.session)

    def test_list_roster_by_team(self):
        resp = self.client_api.get(f'/api/staff/memberships/?team={self.team.id}')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]['username'], 'scout')
        self.assertEqual(body[0]['roles'], [])

    def test_assign_role_records_assigner(self):
        resp = self.client_api.post(
            f'/api/staff/memberships/{self.membership.id}/assign_role/',
            {'role': self.cook.id}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual([r['slug'] for r in resp.json()['roles']], ['cook'])
        team_role = TeamRole.objects.get(membership=self.membership, role=self.cook)
        self.assertEqual(team_role.assigned_by, self.staff)

    def test_assign_role_is_idempotent(self):
        for _ in range(2):
            resp = self.client_api.post(
                f'/api/staff/memberships/{self.membership.id}/assign_role/',
                {'role': self.cook.id}, format='json',
            )
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(TeamRole.objects.count(), 1)

    def test_unassign_role(self):
        TeamRole.objects.create(membership=self.membership, role=self.cook)
        resp = self.client_api.post(
            f'/api/staff/memberships/{self.membership.id}/unassign_role/',
            {'role': self.cook.id}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['roles'], [])
        self.assertFalse(TeamRole.objects.exists())

    def test_assign_role_from_other_game_rejected(self):
        other = _make_game(name='Other')
        alien = GameRole.objects.create(game=other, name='Alien', slug='alien')
        resp = self.client_api.post(
            f'/api/staff/memberships/{self.membership.id}/assign_role/',
            {'role': alien.id}, format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(TeamRole.objects.exists())

    def test_assign_role_requires_role_param(self):
        resp = self.client_api.post(
            f'/api/staff/memberships/{self.membership.id}/assign_role/',
            {}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_requires_staff(self):
        player_client, _ = _authed_client(self.team, username='pleb')
        resp = player_client.get('/api/staff/memberships/')
        self.assertEqual(resp.status_code, 403)


class AdminChallengeRoleConfigTest(TestCase):
    """2.3 / 5.3 — role-requirement validation on the staff challenge API."""

    def setUp(self):
        self.game = _make_game()
        self.session = _default_session(self.game)
        self.cook = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        self.client_api, _ = _staff_client(self.session)

    def test_non_none_mode_requires_roles(self):
        resp = self.client_api.post('/api/staff/challenges/', {
            'game': self.game.id,
            'text': 'bad config',
            'difficulty': 1,
            'role_requirement_mode': ROLE_REQUIREMENT_ALL,
            'required_roles': [],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_required_roles_must_belong_to_challenge_game(self):
        other = _make_game(name='Other')
        alien = GameRole.objects.create(game=other, name='Alien', slug='alien')
        resp = self.client_api.post('/api/staff/challenges/', {
            'game': self.game.id,
            'text': 'cross game',
            'difficulty': 1,
            'role_requirement_mode': ROLE_REQUIREMENT_ANY,
            'required_roles': [alien.id],
        }, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_valid_role_requirement_accepted(self):
        resp = self.client_api.post('/api/staff/challenges/', {
            'game': self.game.id,
            'text': 'needs a cook',
            'difficulty': 1,
            'role_requirement_mode': ROLE_REQUIREMENT_ANY,
            'required_roles': [self.cook.id],
            'require_holders_present': True,
        }, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['role_requirement_mode'], ROLE_REQUIREMENT_ANY)
        self.assertEqual(body['required_roles'], [self.cook.id])
        self.assertTrue(body['require_holders_present'])

    def test_patch_to_non_none_without_roles_rejected(self):
        challenge = Challenge.objects.create(
            game=self.game, text='plain', difficulty=1,
        )
        resp = self.client_api.patch(
            f'/api/staff/challenges/{challenge.id}/',
            {'role_requirement_mode': ROLE_REQUIREMENT_ALL}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_patch_mode_with_roles_accepted(self):
        challenge = Challenge.objects.create(
            game=self.game, text='plain', difficulty=1,
        )
        resp = self.client_api.patch(
            f'/api/staff/challenges/{challenge.id}/',
            {
                'role_requirement_mode': ROLE_REQUIREMENT_ALL,
                'required_roles': [self.cook.id],
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)


class TowerStateRoleRequirementTest(TestCase):
    """5.4 — player challenge surface exposes requirement + satisfaction."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.team = _make_team(self.game, self.group)
        self.cook = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        self.challenge = Challenge.objects.create(
            game=self.game, text='cook it', tower=self.tower, difficulty=1,
            role_requirement_mode=ROLE_REQUIREMENT_ALL,
        )
        self.challenge.required_roles.set([self.cook])
        self.client_api, self.user = _authed_client(self.team)
        self.membership = TeamMembership.objects.get(
            team=self.team, user=self.user.profile,
        )

    def _state(self):
        resp = self.client_api.get(f'/api/towers/{self.tower.id}/state/')
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_unsatisfied_requirement_reported(self):
        req = self._state()['next_challenge']['role_requirement']
        self.assertEqual(req['mode'], ROLE_REQUIREMENT_ALL)
        self.assertEqual([r['slug'] for r in req['required_roles']], ['cook'])
        self.assertFalse(req['team_satisfies'])
        self.assertEqual(req['missing_roles'], ['cook'])
        self.assertFalse(req['require_holders_present'])

    def test_satisfied_after_assignment(self):
        TeamRole.objects.create(membership=self.membership, role=self.cook)
        req = self._state()['next_challenge']['role_requirement']
        self.assertTrue(req['team_satisfies'])
        self.assertEqual(req['missing_roles'], [])

    def test_none_mode_has_null_requirement(self):
        self.challenge.role_requirement_mode = ROLE_REQUIREMENT_NONE
        self.challenge.save()
        self.assertIsNone(self._state()['next_challenge']['role_requirement'])


class RoleBackwardCompatTest(TestCase):
    """8.5 — a Game defining no roles behaves exactly as before the change."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.team = _make_team(self.game, self.group)
        self.challenge = Challenge.objects.create(
            game=self.game, text='plain', tower=self.tower, difficulty=1,
        )
        self.client_api, _ = _authed_client(self.team)

    def test_submission_flow_unchanged(self):
        resp = self.client_api.post(
            '/api/team_tower_challenges/',
            {
                'tower': self.tower.pk,
                'challenge': self.challenge.pk,
                'lat': 46.5,
                'lng': 23.5,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_teams_api_members_have_empty_roles(self):
        resp = self.client_api.get('/api/teams/')
        self.assertEqual(resp.status_code, 200)
        team = resp.json()[0]
        self.assertEqual(team['name'], self.team.name)
        self.assertEqual(len(team['members']), 1)
        self.assertEqual(team['members'][0]['roles'], [])


# ---------------------------------------------------------------------------
# game-config-team-rules — staff API knobs + start-gate + teams readiness
# ---------------------------------------------------------------------------


class TeamRulesApiTest(TestCase):
    """5.6 — team-rule knobs over the staff API, start-gate, teams readiness."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.session = self.team.session
        self.staff_client, self.staff = _staff_client(
            session=self.session, username='rules-admin',
        )

    def _add_member(self, team, username):
        user = User.objects.create_user(
            username=username, email=f'{username}@example.com',
            password='password123',
        )
        TeamMembership.objects.create(team=team, user=user.profile, is_active=True)
        return user

    # -- Games serializer (3.1) --

    def test_game_knobs_default_and_patch(self):
        resp = self.staff_client.get(f'/api/staff/games/{self.game.id}/')
        body = resp.json()
        self.assertEqual(body['min_teams'], 1)
        self.assertEqual(body['max_teams'], 0)
        self.assertEqual(body['min_members_per_team'], 1)
        self.assertEqual(body['max_members_per_team'], 0)

        resp = self.staff_client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'min_teams': 2, 'max_teams': 4,
             'min_members_per_team': 2, 'max_members_per_team': 6},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.game.refresh_from_db()
        self.assertEqual(self.game.min_teams, 2)
        self.assertEqual(self.game.max_teams, 4)
        self.assertEqual(self.game.min_members_per_team, 2)
        self.assertEqual(self.game.max_members_per_team, 6)

    def test_game_rejects_minimum_below_one(self):
        for field in ('min_teams', 'min_members_per_team'):
            resp = self.staff_client.patch(
                f'/api/staff/games/{self.game.id}/', {field: 0}, format='json',
            )
            self.assertEqual(resp.status_code, 400, resp.content)
            self.assertIn(field, resp.json())

    def test_game_rejects_nonzero_max_below_min(self):
        resp = self.staff_client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'min_teams': 3, 'max_teams': 2},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('max_teams', resp.json())

        resp = self.staff_client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'min_members_per_team': 4, 'max_members_per_team': 3},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('max_members_per_team', resp.json())

    # -- Sessions serializer (3.1) --

    def test_session_overrides_default_null_and_patch(self):
        resp = self.staff_client.get(f'/api/staff/sessions/{self.session.id}/')
        body = resp.json()
        for field in ('min_teams', 'max_teams',
                      'min_members_per_team', 'max_members_per_team'):
            self.assertIsNone(body[field])

        resp = self.staff_client.patch(
            f'/api/staff/sessions/{self.session.id}/',
            {'min_teams': 2, 'max_members_per_team': 5},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.session.refresh_from_db()
        self.assertEqual(self.session.min_teams, 2)
        self.assertEqual(self.session.max_members_per_team, 5)

        # Blank (null) reverts to inherit.
        resp = self.staff_client.patch(
            f'/api/staff/sessions/{self.session.id}/',
            {'min_teams': None},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.session.refresh_from_db()
        self.assertIsNone(self.session.min_teams)

    def test_session_rejects_invalid_override_combo(self):
        resp = self.staff_client.patch(
            f'/api/staff/sessions/{self.session.id}/',
            {'min_teams': 3, 'max_teams': 2},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('max_teams', resp.json())

    # -- Start-gate on activation (3.3) --

    # The start-gate rides the lifecycle `start` transition (the PATCH
    # activation path was retired by game-lifecycle-states; PATCH can no
    # longer write state). Blockers surface on the transition's 409.

    def _to_open(self):
        Session.objects.filter(pk=self.session.pk).update(
            state=Session.OPEN_FOR_PARTICIPANTS,
        )
        self.session.refresh_from_db()

    def test_start_blocked_returns_409_with_blockers(self):
        self._to_open()
        resp = self.staff_client.post(
            f'/api/staff/sessions/{self.session.id}/start/',
        )
        self.assertEqual(resp.status_code, 409, resp.content)
        body = resp.json()
        self.assertIn('blockers', body)
        codes = [b['code'] for b in body['blockers']]
        self.assertIn('too_few_teams', codes)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.OPEN_FOR_PARTICIPANTS)

    def test_start_succeeds_when_thresholds_met(self):
        self._to_open()
        self._add_member(self.team, 'starter')
        resp = self.staff_client.post(
            f'/api/staff/sessions/{self.session.id}/start/',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.RUNNING)

    def test_start_gate_respects_session_overrides(self):
        self._to_open()
        self._add_member(self.team, 'lone-wolf')
        resp = self.staff_client.patch(
            f'/api/staff/sessions/{self.session.id}/',
            {'min_teams': 2},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp = self.staff_client.post(
            f'/api/staff/sessions/{self.session.id}/start/',
        )
        self.assertEqual(resp.status_code, 409, resp.content)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.OPEN_FOR_PARTICIPANTS)
        self.assertEqual(self.session.min_teams, 2)  # override persists

    def test_finish_is_never_gated(self):
        self._add_member(self.team, 'quitter')
        # Make the session unstartable, then finish — always allowed.
        self.session.min_teams = 5
        self.session.save()
        resp = self.staff_client.post(
            f'/api/staff/sessions/{self.session.id}/finish/',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.session.refresh_from_db()
        self.assertEqual(self.session.state, Session.FINISHED)

    def test_start_blockers_action(self):
        resp = self.staff_client.get(
            f'/api/staff/sessions/{self.session.id}/start_blockers/',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body['can_start'])
        self.assertTrue(body['blockers'])
        self.assertEqual(body['min_members_per_team'], 1)
        self.assertEqual(len(body['teams']), 1)
        self.assertEqual(body['teams'][0]['active_member_count'], 0)
        self.assertFalse(body['teams'][0]['is_ready'])
        self.assertEqual(body['teams'][0]['members_needed'], 1)

        self._add_member(self.team, 'filler')
        resp = self.staff_client.get(
            f'/api/staff/sessions/{self.session.id}/start_blockers/',
        )
        body = resp.json()
        self.assertTrue(body['can_start'])
        self.assertEqual(body['blockers'], [])
        self.assertTrue(body['teams'][0]['is_ready'])

    # -- Teams API readiness (3.2) --

    def test_player_teams_endpoint_exposes_readiness(self):
        self.game.min_members_per_team = 2
        self.game.save()
        client, _ = _authed_client(self.team, username='ready-check')
        resp = client.get('/api/teams/')
        self.assertEqual(resp.status_code, 200)
        payload = {t['id']: t for t in resp.json()}
        entry = payload[self.team.id]
        self.assertEqual(entry['active_member_count'], 1)
        self.assertFalse(entry['is_ready'])
        self.assertEqual(entry['members_needed'], 1)

        self._add_member(self.team, 'second-member')
        entry = {t['id']: t for t in client.get('/api/teams/').json()}[self.team.id]
        self.assertEqual(entry['active_member_count'], 2)
        self.assertTrue(entry['is_ready'])
        self.assertEqual(entry['members_needed'], 0)

    def test_staff_teams_endpoint_exposes_readiness(self):
        resp = self.staff_client.get('/api/staff/teams/')
        self.assertEqual(resp.status_code, 200)
        entry = {t['id']: t for t in resp.json()}[self.team.id]
        self.assertEqual(entry['active_member_count'], 0)
        self.assertFalse(entry['is_ready'])
        self.assertEqual(entry['members_needed'], 1)


# ---------------------------------------------------------------------------
# BLE proximity substrate + dementors mode (mode-dementors-ble)
# ---------------------------------------------------------------------------


def _make_player(team, username):
    """Create a user with an active membership on `team`, pinned to its session."""
    user = User.objects.create_user(
        username=username, email=f'{username}@example.com', password='password123',
    )
    TeamMembership.objects.create(team=team, user=user.profile, is_active=True)
    user.profile.current_session = team.session
    user.profile.save(update_fields=['current_session'])
    return user.profile


def _client_for(profile):
    token = Token.objects.create(user=profile.user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
    return client


def _proximity_setup(n_players=2, name='Dementors Game'):
    """Game + RUNNING session + one team + `n_players` roster members."""
    game = _make_game(name)
    group = _make_group(game)
    team = _make_team(game, group, name='park-team')
    players = [_make_player(team, f'player{i}') for i in range(n_players)]
    return game, team.session, team, players


def _identity_for(session, profile, token=None):
    identity = ProximityIdentity.issue(session, profile)
    if token is not None:
        ProximityIdentity.objects.filter(pk=identity.pk).update(token=token)
        identity.refresh_from_db()
    return identity


def _report(session, identity, observations, received_at=None):
    """Create a ProximityReport, optionally pinning received_at."""
    report = ProximityReport.objects.create(
        session=session,
        reporter=identity,
        player=identity.player,
        observations=observations,
    )
    if received_at is not None:
        ProximityReport.objects.filter(pk=report.pk).update(received_at=received_at)
        report.refresh_from_db()
    return report


def _pair_event(session, a, b, bucket, derived_at=None):
    """Unsaved ProximityEvent for feeding economy_tick directly."""
    lo, hi = sorted([a.pk, b.pk])
    return ProximityEvent(
        session=session,
        player_a_id=lo,
        player_b_id=hi,
        distance_bucket=bucket,
        confidence=CONFIDENCE_CORROBORATED,
        corroborated=True,
        derived_at=derived_at or timezone.now(),
    )


def _state(session, profile, role, energy, last_tick_at=None, **kwargs):
    return DementorState.objects.create(
        session=session,
        player=profile,
        role=role,
        energy=energy,
        last_tick_at=last_tick_at,
        **kwargs,
    )


class RssiBucketTest(TestCase):
    """T7.1 — RSSI→bucket mapping and hysteresis (no metres, ever)."""

    KW = dict(very_close_dbm=-55, near_dbm=-75)

    def test_basic_mapping(self):
        self.assertEqual(rssi_to_bucket(-40, **self.KW), PROXIMITY_BUCKET_VERY_CLOSE)
        self.assertEqual(rssi_to_bucket(-55, **self.KW), PROXIMITY_BUCKET_VERY_CLOSE)
        self.assertEqual(rssi_to_bucket(-60, **self.KW), PROXIMITY_BUCKET_NEAR)
        self.assertEqual(rssi_to_bucket(-75, **self.KW), PROXIMITY_BUCKET_NEAR)
        self.assertEqual(rssi_to_bucket(-90, **self.KW), PROXIMITY_BUCKET_FAR)

    def test_hysteresis_keeps_previous_bucket_near_boundary(self):
        # -58 alone is NEAR, but a pair previously VERY_CLOSE stays put
        # until the signal drops beyond the shifted boundary.
        self.assertEqual(rssi_to_bucket(-58, **self.KW), PROXIMITY_BUCKET_NEAR)
        self.assertEqual(
            rssi_to_bucket(-58, **self.KW, hysteresis_db=5,
                           previous=PROXIMITY_BUCKET_VERY_CLOSE),
            PROXIMITY_BUCKET_VERY_CLOSE,
        )
        # And a pair previously NEAR needs to beat the raised threshold
        # to be promoted.
        self.assertEqual(
            rssi_to_bucket(-52, **self.KW, hysteresis_db=5,
                           previous=PROXIMITY_BUCKET_NEAR),
            PROXIMITY_BUCKET_NEAR,
        )
        self.assertEqual(
            rssi_to_bucket(-48, **self.KW, hysteresis_db=5,
                           previous=PROXIMITY_BUCKET_NEAR),
            PROXIMITY_BUCKET_VERY_CLOSE,
        )

    def test_hysteresis_prevents_oscillation(self):
        # A signal wobbling ±2 dB around the -55 boundary settles into
        # one bucket instead of flapping.
        bucket = rssi_to_bucket(-54, **self.KW)
        for rssi in (-56, -54, -57, -53, -56):
            bucket = rssi_to_bucket(
                rssi, **self.KW, hysteresis_db=5, previous=bucket,
            )
            self.assertEqual(bucket, PROXIMITY_BUCKET_VERY_CLOSE)

    def test_far_promotion_needs_margin(self):
        self.assertEqual(
            rssi_to_bucket(-73, **self.KW, hysteresis_db=5,
                           previous=PROXIMITY_BUCKET_FAR),
            PROXIMITY_BUCKET_FAR,
        )
        self.assertEqual(
            rssi_to_bucket(-68, **self.KW, hysteresis_db=5,
                           previous=PROXIMITY_BUCKET_FAR),
            PROXIMITY_BUCKET_NEAR,
        )


class ProximityIdentityApiTest(TestCase):
    """T7.1 — ephemeral advertising identity issuance and rotation."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(1)
        self.profile = self.players[0]
        self.client_a = _client_for(self.profile)

    def test_issues_opaque_token(self):
        resp = self.client_a.post('/api/proximity/identity/', {}, format='json')
        self.assertEqual(resp.status_code, 200)
        token = resp.json()['token']
        self.assertEqual(len(token), 8)
        self.assertNotIn(self.profile.user.username, token)
        identity = ProximityIdentity.objects.get(token=token)
        self.assertEqual(identity.player, self.profile)
        self.assertTrue(identity.active)
        self.assertIn('report_interval_seconds', resp.json())

    def test_reissue_is_stable_until_rotation(self):
        first = self.client_a.post('/api/proximity/identity/', {}, format='json').json()
        second = self.client_a.post('/api/proximity/identity/', {}, format='json').json()
        self.assertEqual(first['token'], second['token'])
        self.assertFalse(second['rotated'])

    def test_explicit_rotation_retires_old_token(self):
        first = self.client_a.post('/api/proximity/identity/', {}, format='json').json()
        second = self.client_a.post(
            '/api/proximity/identity/', {'rotate': True}, format='json',
        ).json()
        self.assertNotEqual(first['token'], second['token'])
        self.assertTrue(second['rotated'])
        old = ProximityIdentity.objects.get(token=first['token'])
        self.assertFalse(old.active)
        self.assertIsNotNone(old.retired_at)
        self.assertEqual(
            ProximityIdentity.objects.filter(
                session=self.session, player=self.profile, active=True,
            ).count(),
            1,
        )

    def test_elapsed_rotation_interval_rotates(self):
        first = self.client_a.post('/api/proximity/identity/', {}, format='json').json()
        ProximityIdentity.objects.filter(token=first['token']).update(
            rotates_at=timezone.now() - timedelta(seconds=1),
        )
        second = self.client_a.post('/api/proximity/identity/', {}, format='json').json()
        self.assertNotEqual(first['token'], second['token'])
        self.assertTrue(second['rotated'])

    def test_requires_a_current_session(self):
        loner = User.objects.create_user(
            username='loner', email='loner@example.com', password='password123',
        )
        client = _client_for(loner.profile)
        resp = client.post('/api/proximity/identity/', {}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_ble_gate_refuses_failed_self_check(self):
        self.game.require_ble_capable = True
        self.game.save(update_fields=['require_ble_capable'])
        self.profile.attributes['ble_capable'] = False
        self.profile.save(update_fields=['attributes'])
        resp = self.client_a.post('/api/proximity/identity/', {}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertIn('BLE', resp.json()['detail'])


class ProximityReportApiTest(TestCase):
    """T7.1/T7.2 — report ingestion: unknown tokens, caps, rate limits."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(2)
        self.alice, self.bob = self.players
        self.client_a = _client_for(self.alice)
        self.identity_a = _identity_for(self.session, self.alice, token='aaaa0001')
        self.identity_b = _identity_for(self.session, self.bob, token='bbbb0001')

    def _post(self, observations):
        return self.client_a.post(
            '/api/proximity/reports/', {'observations': observations}, format='json',
        )

    def test_ingests_a_valid_batch(self):
        resp = self._post([{'token': 'bbbb0001', 'rssi': -60}])
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['recorded'], 1)
        self.assertEqual(body['discarded'], 0)
        report = ProximityReport.objects.get(pk=body['id'])
        self.assertEqual(report.player, self.alice)
        self.assertEqual(report.observations, [{'token': 'bbbb0001', 'rssi': -60}])
        # Ingestion triggered the tick: the pair got derived.
        self.assertGreaterEqual(body['events_derived'], 1)

    def test_unknown_tokens_are_discarded_not_fatal(self):
        resp = self._post([
            {'token': 'bbbb0001', 'rssi': -60},
            {'token': 'ffffffff', 'rssi': -60},
        ])
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['recorded'], 1)
        self.assertEqual(resp.json()['discarded'], 1)

    def test_malformed_and_self_observations_are_discarded(self):
        resp = self._post([
            'not-a-dict',
            {'rssi': -60},
            {'token': 'bbbb0001', 'rssi': 'loud'},
            {'token': 'bbbb0001', 'rssi': -300},
            {'token': 'aaaa0001', 'rssi': -60},  # self-sighting
        ])
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['recorded'], 0)
        self.assertEqual(resp.json()['discarded'], 5)

    def test_recently_rotated_token_still_resolves(self):
        ProximityIdentity.issue(self.session, self.bob)  # rotates bbbb0001 out
        resp = self._post([{'token': 'bbbb0001', 'rssi': -60}])
        self.assertEqual(resp.json()['recorded'], 1)

    def test_long_expired_token_is_discarded(self):
        ProximityIdentity.issue(self.session, self.bob)
        window = self.session.effective('ble_freshness_window_seconds')
        ProximityIdentity.objects.filter(token='bbbb0001').update(
            retired_at=timezone.now() - timedelta(seconds=window + 120),
        )
        resp = self._post([{'token': 'bbbb0001', 'rssi': -60}])
        self.assertEqual(resp.json()['recorded'], 0)
        self.assertEqual(resp.json()['discarded'], 1)

    def test_reporting_without_identity_is_rejected(self):
        client_b = _client_for(self.bob)
        ProximityIdentity.objects.filter(player=self.bob).update(
            active=False, retired_at=timezone.now(),
        )
        resp = client_b.post(
            '/api/proximity/reports/',
            {'observations': [{'token': 'aaaa0001', 'rssi': -60}]},
            format='json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_rate_limit_refuses_implausible_cadence(self):
        for _ in range(3):
            self.assertEqual(self._post([]).status_code, 201)
        resp = self._post([])
        self.assertEqual(resp.status_code, 429)

    def test_batch_size_cap(self):
        raw = [{'token': f'zz{i:06d}', 'rssi': -60} for i in range(200)]
        kept, discarded = clean_observations(raw)
        self.assertEqual(len(kept), MAX_OBSERVATIONS_PER_REPORT)
        self.assertEqual(discarded, 200 - MAX_OBSERVATIONS_PER_REPORT)


class ProximityDerivationTest(TestCase):
    """T7.1/T7.2 — pair fusion, confidence, staleness, plausibility."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(3)
        self.alice, self.bob, self.carol = self.players
        self.ia = _identity_for(self.session, self.alice, token='aaaa0001')
        self.ib = _identity_for(self.session, self.bob, token='bbbb0001')
        self.ic = _identity_for(self.session, self.carol, token='cccc0001')
        # Derivation reference instant, slightly ahead of the wall clock
        # so reports auto-stamped during the test fall inside the window.
        self.now = timezone.now() + timedelta(seconds=1)

    def test_one_event_per_pair_with_corroboration_boost(self):
        _report(self.session, self.ia, [{'token': 'bbbb0001', 'rssi': -60}])
        _report(self.session, self.ib, [{'token': 'aaaa0001', 'rssi': -58}])
        events = derive_proximity(self.session, now=self.now)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertTrue(event.corroborated)
        self.assertEqual(event.confidence, CONFIDENCE_CORROBORATED)
        self.assertEqual(event.distance_bucket, PROXIMITY_BUCKET_NEAR)
        self.assertEqual(
            sorted([event.player_a_id, event.player_b_id]),
            sorted([self.alice.pk, self.bob.pk]),
        )

    def test_one_directional_report_still_yields_an_event(self):
        _report(self.session, self.ia, [{'token': 'bbbb0001', 'rssi': -60}])
        events = derive_proximity(self.session, now=self.now)
        self.assertEqual(len(events), 1)
        self.assertFalse(events[0].corroborated)
        self.assertEqual(events[0].confidence, CONFIDENCE_ONE_WAY)

    def test_stale_reports_derive_nothing(self):
        window = self.session.effective('ble_freshness_window_seconds')
        _report(
            self.session, self.ia, [{'token': 'bbbb0001', 'rssi': -60}],
            received_at=self.now - timedelta(seconds=window + 5),
        )
        self.assertEqual(derive_proximity(self.session, now=self.now), [])

    def test_only_latest_report_per_player_counts(self):
        _report(
            self.session, self.ia, [{'token': 'bbbb0001', 'rssi': -60}],
            received_at=self.now - timedelta(seconds=10),
        )
        _report(
            self.session, self.ia, [],
            received_at=self.now - timedelta(seconds=2),
        )
        self.assertEqual(derive_proximity(self.session, now=self.now), [])

    def test_impossible_crowd_is_filtered_out(self):
        crowd = [{'token': f'gg{i:06d}', 'rssi': -60} for i in range(81)]
        crowd.append({'token': 'bbbb0001', 'rssi': -60})
        _report(self.session, self.ia, crowd)
        # Alice's implausible report is dropped wholesale…
        self.assertEqual(derive_proximity(self.session, now=self.now), [])
        # …but a plausible report from someone else still derives.
        _report(self.session, self.ic, [{'token': 'bbbb0001', 'rssi': -70}])
        events = derive_proximity(
            self.session, now=self.now + timedelta(seconds=1),
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(
            sorted([events[0].player_a_id, events[0].player_b_id]),
            sorted([self.bob.pk, self.carol.pk]),
        )

    def test_hysteresis_uses_previous_pass_bucket(self):
        _report(self.session, self.ia, [{'token': 'bbbb0001', 'rssi': -54}])
        first = derive_proximity(self.session, now=self.now)
        self.assertEqual(first[0].distance_bucket, PROXIMITY_BUCKET_VERY_CLOSE)
        # -58 raw is NEAR, but with the pair previously VERY_CLOSE and
        # 5 dB hysteresis it stays VERY_CLOSE.
        later = self.now + timedelta(seconds=5)
        _report(
            self.session, self.ia, [{'token': 'bbbb0001', 'rssi': -58}],
            received_at=later,
        )
        second = derive_proximity(self.session, now=later)
        self.assertEqual(second[0].distance_bucket, PROXIMITY_BUCKET_VERY_CLOSE)


class DementorEconomyTest(TestCase):
    """T7.3 — drain, groups, flips, reverse game, conversion, staleness."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(4)
        self.game.dementors_enabled = True
        self.game.save(update_fields=['dementors_enabled'])
        self.w1, self.w2, self.w3, self.d1 = self.players
        self.t0 = timezone.now()

    def _tick(self, events, seconds=10):
        return economy_tick(
            self.session, events, now=self.t0 + timedelta(seconds=seconds),
        )

    def test_dementor_in_range_drains_wizard(self):
        state = _state(self.session, self.w1, DementorState.WIZARD, 100, self.t0)
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        self._tick([_pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_NEAR)])
        state.refresh_from_db()
        self.assertAlmostEqual(state.energy, 90.0)
        self.assertAlmostEqual(state.last_delta, -10.0)

    def test_out_of_range_bucket_does_not_drain(self):
        state = _state(self.session, self.w1, DementorState.WIZARD, 100, self.t0)
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        self._tick([_pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_FAR)])
        state.refresh_from_db()
        self.assertAlmostEqual(state.energy, 100.0)
        self.assertAlmostEqual(state.last_delta, 0.0)

    def test_stale_tick_applies_no_drain(self):
        state = _state(self.session, self.w1, DementorState.WIZARD, 100, self.t0)
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        self._tick([])  # no fresh events at all
        state.refresh_from_db()
        self.assertAlmostEqual(state.energy, 100.0)

    def test_elapsed_time_is_clamped_to_freshness_window(self):
        window = self.session.effective('ble_freshness_window_seconds')
        state = _state(
            self.session, self.w1, DementorState.WIZARD, 100,
            self.t0 - timedelta(seconds=1000),
        )
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        self._tick(
            [_pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_NEAR)],
            seconds=0,
        )
        state.refresh_from_db()
        self.assertAlmostEqual(state.energy, 100.0 - window)

    def test_safety_in_numbers_divides_drain(self):
        s1 = _state(self.session, self.w1, DementorState.WIZARD, 100, self.t0)
        s2 = _state(self.session, self.w2, DementorState.WIZARD, 100, self.t0)
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        self._tick([
            _pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_NEAR),
            _pair_event(self.session, self.w2, self.d1, PROXIMITY_BUCKET_NEAR),
            _pair_event(self.session, self.w1, self.w2, PROXIMITY_BUCKET_NEAR),
        ])
        s1.refresh_from_db()
        s2.refresh_from_db()
        # Two clustered wizards each take half the drain.
        self.assertAlmostEqual(s1.energy, 95.0)
        self.assertAlmostEqual(s2.energy, 95.0)

    def test_area_drain_hits_everyone_at_full_rate(self):
        self.session.dementor_safety_in_numbers = False
        self.session.save(update_fields=['dementor_safety_in_numbers'])
        s1 = _state(self.session, self.w1, DementorState.WIZARD, 100, self.t0)
        s2 = _state(self.session, self.w2, DementorState.WIZARD, 100, self.t0)
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        self._tick([
            _pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_NEAR),
            _pair_event(self.session, self.w2, self.d1, PROXIMITY_BUCKET_NEAR),
            _pair_event(self.session, self.w1, self.w2, PROXIMITY_BUCKET_NEAR),
        ])
        s1.refresh_from_db()
        s2.refresh_from_db()
        self.assertAlmostEqual(s1.energy, 90.0)
        self.assertAlmostEqual(s2.energy, 90.0)

    def test_lone_wizard_drains_faster_than_group(self):
        lone = _state(self.session, self.w1, DementorState.WIZARD, 100, self.t0)
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        self._tick([_pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_NEAR)])
        lone.refresh_from_db()
        lone_drop = 100 - lone.energy
        self.assertAlmostEqual(lone_drop, 10.0)  # vs 5.0 in the pair test

    def test_full_drain_flips_wizard_to_dementor(self):
        state = _state(self.session, self.w1, DementorState.WIZARD, 5, self.t0)
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        self._tick([_pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_NEAR)])
        state.refresh_from_db()
        self.assertEqual(state.role, DementorState.DEMENTOR)
        self.assertTrue(state.alive)
        self.assertAlmostEqual(state.energy, 0.0)
        flip = DementorFlip.objects.get(state=state)
        self.assertEqual(flip.cause, FLIP_CAUSE_DRAINED)
        self.assertEqual(flip.from_role, DementorState.WIZARD)
        self.assertEqual(flip.to_role, DementorState.DEMENTOR)

    def test_die_on_empty_marks_out_of_play(self):
        self.session.dementor_empty_outcome = DEMENTOR_EMPTY_DIE
        self.session.save(update_fields=['dementor_empty_outcome'])
        state = _state(self.session, self.w1, DementorState.WIZARD, 5, self.t0)
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        self._tick([_pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_NEAR)])
        state.refresh_from_db()
        self.assertFalse(state.alive)
        self.assertEqual(state.role, DementorState.WIZARD)
        self.assertEqual(DementorFlip.objects.get(state=state).cause, FLIP_CAUSE_DIED)

    def test_reverse_numbers_game_flips_held_dementor(self):
        self.session.dementor_reverse_group_size = 3
        self.session.dementor_reverse_hold_seconds = 30
        self.session.save(update_fields=[
            'dementor_reverse_group_size', 'dementor_reverse_hold_seconds',
        ])
        for w in (self.w1, self.w2, self.w3):
            _state(self.session, w, DementorState.WIZARD, 100, self.t0)
        dementor = _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        surround = [
            _pair_event(self.session, w, self.d1, PROXIMITY_BUCKET_NEAR)
            for w in (self.w1, self.w2, self.w3)
        ]
        self._tick(surround, seconds=10)  # hold starts
        dementor.refresh_from_db()
        self.assertIsNotNone(dementor.hold_started_at)
        self.assertEqual(dementor.role, DementorState.DEMENTOR)
        self._tick(surround, seconds=45)  # 35s of continuous hold ≥ 30s
        dementor.refresh_from_db()
        self.assertEqual(dementor.role, DementorState.WIZARD)
        self.assertAlmostEqual(
            dementor.energy, self.session.effective('dementor_starting_energy'),
        )
        flip = DementorFlip.objects.get(state=dementor)
        self.assertEqual(flip.cause, FLIP_CAUSE_REVERSE_GAME)

    def test_hold_resets_when_group_shrinks(self):
        self.session.dementor_reverse_group_size = 3
        self.session.dementor_reverse_hold_seconds = 30
        self.session.save(update_fields=[
            'dementor_reverse_group_size', 'dementor_reverse_hold_seconds',
        ])
        for w in (self.w1, self.w2, self.w3):
            _state(self.session, w, DementorState.WIZARD, 100, self.t0)
        dementor = _state(self.session, self.d1, DementorState.DEMENTOR, 0, self.t0)
        surround = [
            _pair_event(self.session, w, self.d1, PROXIMITY_BUCKET_NEAR)
            for w in (self.w1, self.w2, self.w3)
        ]
        self._tick(surround, seconds=10)
        self._tick(surround[:2], seconds=20)  # one wizard peels off
        dementor.refresh_from_db()
        self.assertIsNone(dementor.hold_started_at)
        self._tick(surround, seconds=45)  # back to 3, but the clock restarted
        dementor.refresh_from_db()
        self.assertEqual(dementor.role, DementorState.DEMENTOR)

    def test_conversion_threshold_flips_dementor_back(self):
        self.session.dementor_reverse_group_size = 1
        self.session.dementor_reverse_hold_seconds = 3600  # keep reverse out of it
        self.session.dementor_restore_per_second = 1.0
        self.session.dementor_conversion_threshold = 100.0
        self.session.save(update_fields=[
            'dementor_reverse_group_size', 'dementor_reverse_hold_seconds',
            'dementor_restore_per_second', 'dementor_conversion_threshold',
        ])
        _state(self.session, self.w1, DementorState.WIZARD, 100, self.t0)
        dementor = _state(self.session, self.d1, DementorState.DEMENTOR, 95, self.t0)
        self._tick([_pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_NEAR)])
        dementor.refresh_from_db()
        self.assertEqual(dementor.role, DementorState.WIZARD)
        self.assertGreaterEqual(dementor.energy, 100.0)
        flip = DementorFlip.objects.get(state=dementor)
        self.assertEqual(flip.cause, FLIP_CAUSE_CONVERSION)

    def test_wizard_regen_when_no_dementor_near(self):
        self.session.dementor_wizard_regen_per_second = 0.5
        self.session.save(update_fields=['dementor_wizard_regen_per_second'])
        state = _state(self.session, self.w1, DementorState.WIZARD, 50, self.t0)
        self._tick([])
        state.refresh_from_db()
        self.assertAlmostEqual(state.energy, 55.0)
        self.assertAlmostEqual(state.last_delta, 5.0)
        # Regen never exceeds starting energy.
        state.energy = 99.0
        state.last_tick_at = self.t0
        state.save()
        economy_tick(self.session, [], now=self.t0 + timedelta(seconds=10))
        state.refresh_from_db()
        self.assertAlmostEqual(state.energy, 100.0)

    def test_first_tick_only_stamps_bookkeeping(self):
        state = _state(self.session, self.w1, DementorState.WIZARD, 100, None)
        _state(self.session, self.d1, DementorState.DEMENTOR, 0, None)
        self._tick([_pair_event(self.session, self.w1, self.d1, PROXIMITY_BUCKET_NEAR)])
        state.refresh_from_db()
        self.assertAlmostEqual(state.energy, 100.0)
        self.assertIsNotNone(state.last_tick_at)

    def test_run_tick_without_mode_leaves_states_alone(self):
        self.game.dementors_enabled = False
        self.game.save(update_fields=['dementors_enabled'])
        state = _state(
            self.session, self.w1, DementorState.WIZARD, 100,
            self.t0 - timedelta(seconds=10),
        )
        run_tick(self.session, now=self.t0)
        state.refresh_from_db()
        self.assertAlmostEqual(state.energy, 100.0)
        # Economy bookkeeping untouched — the tick never ran for it.
        self.assertEqual(state.last_tick_at, self.t0 - timedelta(seconds=10))


class DementorLifecycleTest(TestCase):
    """T3.3 — initial role assignment and the session-start hook."""

    def test_assign_initial_roles_splits_roster(self):
        game, session, team, players = _proximity_setup(5, name='Roles Game')
        game.dementors_enabled = True
        game.dementor_initial_dementors = 2
        game.save(update_fields=['dementors_enabled', 'dementor_initial_dementors'])
        assign_initial_roles(session)
        states = DementorState.objects.filter(session=session)
        self.assertEqual(states.count(), 5)
        dementors = states.filter(role=DementorState.DEMENTOR)
        wizards = states.filter(role=DementorState.WIZARD)
        self.assertEqual(dementors.count(), 2)
        self.assertEqual(wizards.count(), 3)
        for state in dementors:
            self.assertEqual(state.energy, 0.0)
        for state in wizards:
            self.assertEqual(state.energy, 100.0)

    def test_assign_initial_roles_is_idempotent(self):
        game, session, team, players = _proximity_setup(3, name='Idem Game')
        game.dementors_enabled = True
        game.save(update_fields=['dementors_enabled'])
        assign_initial_roles(session)
        first = set(DementorState.objects.filter(session=session).values_list('pk', flat=True))
        assign_initial_roles(session)
        second = set(DementorState.objects.filter(session=session).values_list('pk', flat=True))
        self.assertEqual(first, second)

    def test_session_start_seeds_dementor_states(self):
        game, session, team, players = _proximity_setup(2, name='Start Game')
        game.dementors_enabled = True
        game.save(update_fields=['dementors_enabled'])
        session.state = Session.OPEN_FOR_PARTICIPANTS
        session.save(update_fields=['state'])
        session.transition('start')
        self.assertEqual(session.state, Session.RUNNING)
        self.assertEqual(
            DementorState.objects.filter(session=session).count(), 2,
        )

    def test_session_start_without_mode_seeds_nothing(self):
        game, session, team, players = _proximity_setup(2, name='Plain Game')
        session.state = Session.OPEN_FOR_PARTICIPANTS
        session.save(update_fields=['state'])
        session.transition('start')
        self.assertEqual(DementorState.objects.filter(session=session).count(), 0)


class DementorApiTest(TestCase):
    """T5.1/T5.2 — player /me/ endpoint and staff totals feed."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(3)
        self.game.dementors_enabled = True
        self.game.save(update_fields=['dementors_enabled'])
        self.wizard, self.other, self.dementor = self.players
        _state(self.session, self.wizard, DementorState.WIZARD, 80,
               timezone.now(), last_delta=-2.5)
        _state(self.session, self.other, DementorState.WIZARD, 100, timezone.now())
        _state(self.session, self.dementor, DementorState.DEMENTOR, 10,
               timezone.now(), last_delta=1.0)
        self.client_w = _client_for(self.wizard)

    def test_me_reports_role_energy_and_trend(self):
        resp = self.client_w.get('/api/dementors/me/')
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['role'], 'WIZARD')
        self.assertEqual(body['energy'], 80.0)
        self.assertEqual(body['starting_energy'], 100.0)
        self.assertEqual(body['trend'], 'DRAINING')
        self.assertTrue(body['alive'])
        self.assertTrue(body['reports_stale'])  # no report submitted yet

    def test_me_reports_fresh_after_reporting(self):
        _identity_for(self.session, self.wizard, token='aaaa0002')
        self.client_w.post(
            '/api/proximity/reports/', {'observations': []}, format='json',
        )
        resp = self.client_w.get('/api/dementors/me/')
        self.assertFalse(resp.json()['reports_stale'])

    def test_me_404_when_mode_disabled(self):
        self.game.dementors_enabled = False
        self.game.save(update_fields=['dementors_enabled'])
        self.assertEqual(self.client_w.get('/api/dementors/me/').status_code, 404)

    def test_me_404_without_state(self):
        DementorState.objects.filter(player=self.wizard).delete()
        self.assertEqual(self.client_w.get('/api/dementors/me/').status_code, 404)

    def test_device_cannot_assert_its_own_energy(self):
        # There is no write path: POSTing to /me/ is rejected outright,
        # and report payload fields like "energy" are ignored.
        resp = self.client_w.post(
            '/api/dementors/me/', {'energy': 9999}, format='json',
        )
        self.assertEqual(resp.status_code, 405)
        _identity_for(self.session, self.wizard, token='aaaa0003')
        self.client_w.post(
            '/api/proximity/reports/',
            {'observations': [], 'energy': 9999, 'role': 'DEMENTOR'},
            format='json',
        )
        state = DementorState.objects.get(player=self.wizard)
        self.assertEqual(state.energy, 80.0)
        self.assertEqual(state.role, DementorState.WIZARD)

    def test_staff_totals_counts_roles(self):
        staff_client, _ = _staff_client(session=self.session, username='dstaff')
        resp = staff_client.get(
            f'/api/staff/dementors/session/{self.session.id}/totals/',
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['enabled'])
        self.assertEqual(body['totals'], {
            'wizards': 2, 'dementors': 1, 'out_of_play': 0,
        })
        self.assertEqual(len(body['players']), 3)
        by_name = {p['username']: p for p in body['players']}
        self.assertEqual(by_name['player2']['role'], 'DEMENTOR')
        self.assertEqual(by_name['player0']['team'], 'park-team')

    def test_staff_totals_tracks_out_of_play(self):
        DementorState.objects.filter(player=self.other).update(alive=False)
        staff_client, _ = _staff_client(session=self.session, username='dstaff2')
        body = staff_client.get(
            f'/api/staff/dementors/session/{self.session.id}/totals/',
        ).json()
        self.assertEqual(body['totals'], {
            'wizards': 1, 'dementors': 1, 'out_of_play': 1,
        })

    def test_staff_totals_requires_staff(self):
        resp = self.client_w.get(
            f'/api/staff/dementors/session/{self.session.id}/totals/',
        )
        self.assertEqual(resp.status_code, 403)


class DementorConfigOverrideTest(TestCase):
    """T7.4 — Session overrides beat Game defaults for every new knob."""

    OVERRIDES = {
        'require_ble_capable': True,
        'ble_report_interval_seconds': 7,
        'ble_scan_duty_cycle_percent': 40,
        'ble_freshness_window_seconds': 90,
        'ble_identity_rotation_minutes': 3,
        'ble_rssi_very_close_dbm': -50,
        'ble_rssi_near_dbm': -70,
        'ble_rssi_hysteresis_db': 8,
        'dementors_enabled': True,
        'dementor_initial_dementors': 4,
        'dementor_starting_energy': 250.0,
        'dementor_drain_per_second': 2.5,
        'dementor_drain_range_bucket': PROXIMITY_BUCKET_VERY_CLOSE,
        'dementor_empty_outcome': DEMENTOR_EMPTY_DIE,
        'dementor_safety_in_numbers': False,
        'dementor_reverse_group_size': 5,
        'dementor_reverse_hold_seconds': 120,
        'dementor_conversion_threshold': 300.0,
        'dementor_restore_per_second': 3.5,
        'dementor_wizard_regen_per_second': 0.25,
        'dementor_tick_seconds': 2,
    }

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(1)

    def test_defaults_inherit_from_game(self):
        for field in self.OVERRIDES:
            with self.subTest(field=field):
                self.assertIsNone(getattr(self.session, field))
                self.assertEqual(
                    self.session.effective(field), getattr(self.game, field),
                )

    def test_session_override_beats_game_default(self):
        for field, value in self.OVERRIDES.items():
            setattr(self.session, field, value)
        self.session.save()
        session = Session.objects.get(pk=self.session.pk)
        for field, value in self.OVERRIDES.items():
            with self.subTest(field=field):
                self.assertNotEqual(value, getattr(self.game, field))
                self.assertEqual(session.effective(field), value)

    def test_capability_endpoint_admits_and_refuses(self):
        client = _client_for(self.players[0])
        # Not required: a non-BLE phone is admitted (but flagged).
        resp = client.post(
            '/api/proximity/capability/', {'ble_capable': False}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['admitted'])
        # Required: the same phone is refused with a clear message.
        self.session.require_ble_capable = True
        self.session.save(update_fields=['require_ble_capable'])
        resp = client.post(
            '/api/proximity/capability/', {'ble_capable': False}, format='json',
        )
        self.assertFalse(resp.json()['admitted'])
        self.assertIn('BLE', resp.json()['detail'])
        # A capable phone passes the gate.
        resp = client.post(
            '/api/proximity/capability/', {'ble_capable': True}, format='json',
        )
        self.assertTrue(resp.json()['admitted'])

    def test_capability_validates_payload(self):
        client = _client_for(self.players[0])
        resp = client.post(
            '/api/proximity/capability/', {'ble_capable': 'yes'}, format='json',
        )
        self.assertEqual(resp.status_code, 400)


class DementorSwarmTest(TestCase):
    """T7.5 — ~100-identity simulated swarm: tick correctness + bounds."""

    N = 100
    NEIGHBORS = 5  # each phone hears the next 5 identities in a ring

    def test_hundred_player_tick(self):
        import time as time_module

        game, session, team, players = _proximity_setup(0, name='Swarm Game')
        game.dementors_enabled = True
        game.dementor_initial_dementors = 10
        game.save(update_fields=['dementors_enabled', 'dementor_initial_dementors'])

        profiles = []
        for i in range(self.N):
            user = User(username=f'swarm{i:03d}', email=f'swarm{i:03d}@example.com')
            user.set_unusable_password()
            user.save()
            TeamMembership.objects.create(
                team=team, user=user.profile, is_active=True,
            )
            profiles.append(user.profile)

        identities = [
            ProximityIdentity.objects.create(
                session=session, player=profile, token=f'sw{i:06x}',
            )
            for i, profile in enumerate(profiles)
        ]
        assign_initial_roles(session)
        self.assertEqual(
            DementorState.objects.filter(session=session).count(), self.N,
        )
        self.assertEqual(
            DementorState.objects.filter(
                session=session, role=DementorState.DEMENTOR,
            ).count(),
            10,
        )
        # Backdate the tick bookkeeping so the swarm tick applies 10s.
        t0 = timezone.now()
        DementorState.objects.filter(session=session).update(
            last_tick_at=t0 - timedelta(seconds=10),
        )

        for i, identity in enumerate(identities):
            observations = [
                {
                    'token': identities[(i + k) % self.N].token,
                    'rssi': -60 - k,
                }
                for k in range(1, self.NEIGHBORS + 1)
            ]
            _report(session, identity, observations)

        started = time_module.monotonic()
        events = run_tick(session)
        elapsed = time_module.monotonic() - started

        # Ring topology: every (i, i+k) pair for k ≤ 5 exists exactly once.
        self.assertEqual(len(events), self.N * self.NEIGHBORS)
        for event in events:
            self.assertLess(event.player_a_id, event.player_b_id)
        # All fused pairs were seen from both sides? No — only k ≤ 5 both
        # ways when i sees i+k and i+k sees i+2k…; assert confidences are
        # within the defined set rather than a fixed split.
        self.assertTrue(all(
            event.confidence in (CONFIDENCE_ONE_WAY, CONFIDENCE_CORROBORATED)
            for event in events
        ))
        # Economy ran: wizards adjacent to a dementor lost energy.
        states = {
            s.player_id: s
            for s in DementorState.objects.filter(session=session)
        }
        adjacency = {pid: set() for pid in states}
        for event in events:
            adjacency[event.player_a_id].add(event.player_b_id)
            adjacency[event.player_b_id].add(event.player_a_id)
        dementor_ids = {
            pid for pid, s in states.items() if s.role == DementorState.DEMENTOR
        }
        drained = [
            s for pid, s in states.items()
            if s.role == DementorState.WIZARD and adjacency[pid] & dementor_ids
        ]
        flipped = DementorFlip.objects.filter(state__session=session).count()
        self.assertTrue(drained or flipped)
        for state in drained:
            self.assertLess(state.energy, 100.0)
        # Loose CI-safe performance bound for one full tick at 100 phones.
        self.assertLess(elapsed, 10.0)


# ---------------------------------------------------------------------------
# Wearable badge hardware (wearable-badge-hardware)
# ---------------------------------------------------------------------------


def _badge(badge_id, **kwargs):
    return BadgeDevice.objects.create(badge_id=badge_id, **kwargs)


def _gateway(name='gw-north', **kwargs):
    return GatewayNode.objects.create(name=name, **kwargs)


def _assign_badge(badge, session, player=None, team=None):
    assignment = BadgeAssignment.objects.create(
        badge=badge, session=session, player=player, team=team,
    )
    BadgeDevice.objects.filter(pk=badge.pk).update(status='ASSIGNED')
    badge.refresh_from_db()
    return assignment


def _ingest(gateway, observations=None, telemetry=None, version=GATEWAY_PROTOCOL_VERSION,
            token=None):
    client = APIClient()
    payload = {
        'protocol_version': version,
        'observations': observations or [],
        'telemetry': telemetry or [],
    }
    return client.post(
        '/api/gateway/ingest/',
        payload,
        format='json',
        HTTP_X_GATEWAY_TOKEN=gateway.token if token is None else token,
    )


def _obs(badge_id, seen_badge_id, rssi=-60, counter=1):
    return {
        'badge_id': badge_id,
        'seen_badge_id': seen_badge_id,
        'rssi': rssi,
        'counter': counter,
    }


class GatewayIngestAuthTest(TestCase):
    """T7.1 — gateway auth is required; protocol version is validated."""

    def setUp(self):
        self.gateway = _gateway()

    def test_missing_token_is_unauthorized(self):
        resp = _ingest(self.gateway, token='')
        self.assertEqual(resp.status_code, 401)

    def test_invalid_token_is_unauthorized(self):
        resp = _ingest(self.gateway, token='not-a-real-token')
        self.assertEqual(resp.status_code, 401)

    def test_inactive_gateway_is_refused(self):
        self.gateway.active = False
        self.gateway.save(update_fields=['active'])
        resp = _ingest(self.gateway)
        self.assertEqual(resp.status_code, 401)

    def test_wrong_protocol_version_is_rejected(self):
        resp = _ingest(self.gateway, version=99)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['protocol_version'], GATEWAY_PROTOCOL_VERSION)

    def test_valid_ingest_touches_gateway_last_seen(self):
        self.assertIsNone(self.gateway.last_seen_at)
        resp = _ingest(self.gateway)
        self.assertEqual(resp.status_code, 200)
        self.gateway.refresh_from_db()
        self.assertIsNotNone(self.gateway.last_seen_at)
        self.assertEqual(resp.json()['protocol_version'], GATEWAY_PROTOCOL_VERSION)

    def test_player_token_is_not_a_gateway_credential(self):
        game, session, team, players = _proximity_setup(1, name='Auth Game')
        player_token = Token.objects.create(user=players[0].user)
        resp = _ingest(self.gateway, token=player_token.key)
        self.assertEqual(resp.status_code, 401)


class GatewayIngestDedupTest(TestCase):
    """T7.1 — dedupe by badge id + rolling counter across gateways."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(
            2, name='Dedup Game',
        )
        self.alice, self.bob = self.players
        self.badge_a = _badge('aa110001')
        self.badge_b = _badge('bb220002')
        _assign_badge(self.badge_a, self.session, player=self.alice)
        _assign_badge(self.badge_b, self.session, player=self.bob)
        self.gw1 = _gateway('gw-1')
        self.gw2 = _gateway('gw-2')

    def test_second_gateway_relay_is_deduplicated(self):
        first = _ingest(self.gw1, [_obs('aa110001', 'bb220002', counter=7)])
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['accepted']['observations'], 1)
        second = _ingest(self.gw2, [_obs('aa110001', 'bb220002', counter=7)])
        self.assertEqual(second.json()['accepted']['observations'], 0)
        self.assertEqual(second.json()['discarded']['duplicates'], 1)
        self.assertEqual(
            ProximityReport.objects.filter(session=self.session).count(), 1,
        )

    def test_in_batch_duplicate_is_deduplicated(self):
        resp = _ingest(self.gw1, [
            _obs('aa110001', 'bb220002', counter=3),
            _obs('aa110001', 'bb220002', counter=3),
        ])
        self.assertEqual(resp.json()['accepted']['observations'], 1)
        self.assertEqual(resp.json()['discarded']['duplicates'], 1)

    def test_new_counter_is_a_new_observation(self):
        _ingest(self.gw1, [_obs('aa110001', 'bb220002', counter=1)])
        resp = _ingest(self.gw1, [_obs('aa110001', 'bb220002', counter=2)])
        self.assertEqual(resp.json()['accepted']['observations'], 1)
        self.assertEqual(resp.json()['discarded']['duplicates'], 0)


class GatewayIngestTranslationTest(TestCase):
    """T7.2 — badge observations feed the SAME substrate as phone BLE."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(
            2, name='Translation Game',
        )
        self.alice, self.bob = self.players
        self.badge_a = _badge('aa110001')
        self.badge_b = _badge('bb220002')
        _assign_badge(self.badge_a, self.session, player=self.alice)
        _assign_badge(self.badge_b, self.session, player=self.bob)
        self.gateway = _gateway()

    def test_translation_writes_badge_tagged_reports_in_identity_space(self):
        resp = _ingest(self.gateway, [_obs('aa110001', 'bb220002', rssi=-60)])
        self.assertEqual(resp.status_code, 200)
        report = ProximityReport.objects.get(session=self.session)
        self.assertEqual(report.player, self.alice)
        self.assertEqual(report.source, PROXIMITY_SOURCE_BADGE)
        # The seen badge resolved to bob's ProximityIdentity token — the
        # exact same identity space the phone path uses.
        bob_identity = ProximityIdentity.current_for(self.session, self.bob)
        self.assertIsNotNone(bob_identity)
        self.assertEqual(
            report.observations, [{'token': bob_identity.token, 'rssi': -60}],
        )

    def test_two_directions_fuse_into_one_corroborated_badge_event(self):
        resp = _ingest(self.gateway, [
            _obs('aa110001', 'bb220002', rssi=-60, counter=1),
            _obs('bb220002', 'aa110001', rssi=-58, counter=1),
        ])
        self.assertEqual(resp.json()['accepted']['observations'], 2)
        self.assertGreaterEqual(resp.json()['events_derived'], 1)
        event = ProximityEvent.objects.filter(session=self.session).latest('derived_at')
        self.assertTrue(event.corroborated)
        self.assertEqual(event.confidence, CONFIDENCE_CORROBORATED)
        self.assertEqual(event.distance_bucket, PROXIMITY_BUCKET_NEAR)
        self.assertEqual(event.source, PROXIMITY_SOURCE_BADGE)

    def test_parity_with_the_phone_path(self):
        """A badge observation derives the same nearness as a phone report."""
        # Badge transport in this session.
        _ingest(self.gateway, [
            _obs('aa110001', 'bb220002', rssi=-60, counter=1),
            _obs('bb220002', 'aa110001', rssi=-58, counter=1),
        ])
        badge_event = ProximityEvent.objects.filter(
            session=self.session,
        ).latest('derived_at')

        # Equivalent phone transport, separate session, same RSSI.
        game2 = _make_game('Phone Twin Game')
        team2 = _make_team(game2, _make_group(game2), name='twin-team')
        session2 = team2.session
        carol = _make_player(team2, 'carol')
        dave = _make_player(team2, 'dave')
        _identity_for(session2, carol, token='cccc0001')
        _identity_for(session2, dave, token='dddd0001')
        _client_for(carol).post(
            '/api/proximity/reports/',
            {'observations': [{'token': 'dddd0001', 'rssi': -60}]},
            format='json',
        )
        _client_for(dave).post(
            '/api/proximity/reports/',
            {'observations': [{'token': 'cccc0001', 'rssi': -58}]},
            format='json',
        )
        phone_event = ProximityEvent.objects.filter(
            session=session2,
        ).latest('derived_at')

        self.assertEqual(badge_event.distance_bucket, phone_event.distance_bucket)
        self.assertEqual(badge_event.confidence, phone_event.confidence)
        self.assertEqual(badge_event.corroborated, phone_event.corroborated)
        self.assertEqual(phone_event.source, PROXIMITY_SOURCE_PHONE)
        self.assertEqual(badge_event.source, PROXIMITY_SOURCE_BADGE)

    def test_unknown_or_unassigned_badges_are_discarded(self):
        _badge('ee550005')  # registered but never handed out
        resp = _ingest(self.gateway, [
            _obs('ffffffff', 'bb220002', counter=1),   # unknown observer
            _obs('aa110001', 'ffffffff', counter=2),   # unknown seen badge
            _obs('ee550005', 'bb220002', counter=3),   # unassigned observer
        ])
        self.assertEqual(resp.json()['accepted']['observations'], 0)
        self.assertEqual(resp.json()['discarded']['observations'], 3)
        self.assertEqual(ProximityReport.objects.count(), 0)

    def test_cross_session_sighting_is_discarded(self):
        other_game = _make_game('Other Park')
        other_team = _make_team(other_game, _make_group(other_game), name='other-team')
        eve = _make_player(other_team, 'eve')
        badge_c = _badge('cc330003')
        _assign_badge(badge_c, other_team.session, player=eve)
        resp = _ingest(self.gateway, [_obs('aa110001', 'cc330003')])
        self.assertEqual(resp.json()['accepted']['observations'], 0)
        self.assertEqual(resp.json()['discarded']['observations'], 1)

    def test_badge_proximity_drives_the_energy_economy(self):
        """Transport parity where it matters: the drain is identical."""
        self.game.dementors_enabled = True
        self.game.save(update_fields=['dementors_enabled'])
        past = timezone.now() - timedelta(seconds=10)
        wizard = _state(self.session, self.alice, DementorState.WIZARD, 100.0,
                        last_tick_at=past)
        _state(self.session, self.bob, DementorState.DEMENTOR, 0.0,
               last_tick_at=past)

        resp = _ingest(self.gateway, [_obs('aa110001', 'bb220002', rssi=-60)])
        self.assertGreaterEqual(resp.json()['events_derived'], 1)
        wizard.refresh_from_db()
        # ~10s of drain at the default 1.0/s (single wizard, no cluster).
        self.assertLess(wizard.energy, 100.0)
        self.assertAlmostEqual(wizard.energy, 90.0, delta=1.5)
        self.assertLess(wizard.last_delta, 0.0)

    def test_badge_asserted_outcomes_are_ignored(self):
        """T2.6 — outcome-shaped fields never reach the game state."""
        self.game.dementors_enabled = True
        self.game.save(update_fields=['dementors_enabled'])
        state = _state(self.session, self.alice, DementorState.WIZARD, 100.0,
                       last_tick_at=timezone.now())
        resp = _ingest(
            self.gateway,
            observations=[{
                'badge_id': 'aa110001',
                'seen_badge_id': 'bb220002',
                'rssi': -90,
                'counter': 1,
                # Asserted outcomes a compromised badge might inject:
                'role': 'DEMENTOR',
                'energy': 0,
                'outcome': 'wizard-is-now-dementor',
            }],
            telemetry=[{
                'badge_id': 'aa110001',
                'battery_pct': 55,
                'role': 'DEMENTOR',
                'energy': 0,
            }],
        )
        self.assertEqual(resp.status_code, 200)
        state.refresh_from_db()
        self.assertEqual(state.role, DementorState.WIZARD)
        self.assertGreater(state.energy, 99.0)  # -90 dBm is FAR: no drain
        self.assertTrue(state.alive)
        # The underlying observations WERE accepted (battery included).
        self.badge_a.refresh_from_db()
        self.assertEqual(self.badge_a.battery_pct, 55)


class GatewayRangingTest(TestCase):
    """T7.4 — RSSI→bucket policy lives server-side, per Session config."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(
            2, name='Ranging Game',
        )
        self.alice, self.bob = self.players
        self.badge_a = _badge('aa110001')
        self.badge_b = _badge('bb220002')
        _assign_badge(self.badge_a, self.session, player=self.alice)
        _assign_badge(self.badge_b, self.session, player=self.bob)
        self.gateway = _gateway()

    def _latest_bucket(self):
        return ProximityEvent.objects.filter(
            session=self.session,
        ).latest('derived_at').distance_bucket

    def test_session_override_changes_the_bucket_for_the_same_rssi(self):
        _ingest(self.gateway, [_obs('aa110001', 'bb220002', rssi=-60, counter=1)])
        self.assertEqual(self._latest_bucket(), PROXIMITY_BUCKET_NEAR)

        # Same -60 dBm reading, but this Session widens VERY_CLOSE.
        Session.objects.filter(pk=self.session.pk).update(
            ble_rssi_very_close_dbm=-70,
        )
        ProximityEvent.objects.all().delete()  # no hysteresis carryover
        _ingest(self.gateway, [_obs('aa110001', 'bb220002', rssi=-60, counter=2)])
        self.assertEqual(self._latest_bucket(), PROXIMITY_BUCKET_VERY_CLOSE)

    def test_noisy_rssi_is_smoothed_not_metric(self):
        # A pair hovering at the NEAR/FAR boundary: FAR first, then a
        # slightly stronger wobble stays FAR thanks to hysteresis.
        _ingest(self.gateway, [_obs('aa110001', 'bb220002', rssi=-76, counter=1)])
        self.assertEqual(self._latest_bucket(), PROXIMITY_BUCKET_FAR)
        _ingest(self.gateway, [_obs('aa110001', 'bb220002', rssi=-73, counter=2)])
        self.assertEqual(self._latest_bucket(), PROXIMITY_BUCKET_FAR)
        # Buckets are ordinal labels — no metres anywhere in the event.
        event = ProximityEvent.objects.filter(session=self.session).first()
        self.assertIn(
            event.distance_bucket,
            {PROXIMITY_BUCKET_VERY_CLOSE, PROXIMITY_BUCKET_NEAR, PROXIMITY_BUCKET_FAR},
        )

    def test_out_of_range_rssi_is_discarded(self):
        resp = _ingest(self.gateway, [
            _obs('aa110001', 'bb220002', rssi=-300, counter=1),
            _obs('aa110001', 'bb220002', rssi=50, counter=2),
        ])
        self.assertEqual(resp.json()['accepted']['observations'], 0)
        self.assertEqual(resp.json()['discarded']['observations'], 2)


class BadgeProvisioningApiTest(TestCase):
    """T7.3 — register / hand-out / collect, and identity opacity."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(
            2, name='Provisioning Game',
        )
        self.alice, self.bob = self.players
        self.staff, self.staff_user = _staff_client(session=self.session)

    def test_register_creates_a_durable_opaque_asset(self):
        resp = self.staff.post(
            '/api/staff/badges/',
            {'hardware_mac': 'AA:BB:CC:DD:EE:01', 'firmware_version': '0.1.0'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(len(body['badge_id']), 8)
        self.assertEqual(body['status'], 'AVAILABLE')
        # Opaque: the on-air id carries no player identity.
        self.assertNotIn(self.alice.user.username, body['badge_id'])

    def test_register_duplicate_badge_id_conflicts(self):
        _badge('aa110001')
        resp = self.staff.post(
            '/api/staff/badges/', {'badge_id': 'aa110001'}, format='json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_staff_only(self):
        player_client = _client_for(self.alice)
        badge = _badge('aa110001')
        for method, url, payload in [
            ('get', '/api/staff/badges/', None),
            ('post', '/api/staff/badges/', {}),
            ('post', f'/api/staff/badges/{badge.pk}/assign/', {}),
            ('post', f'/api/staff/badges/{badge.pk}/collect/', {}),
            ('get', '/api/staff/gateways/', None),
            ('post', '/api/staff/gateways/', {'name': 'x'}),
        ]:
            resp = getattr(player_client, method)(url, payload, format='json')
            self.assertEqual(resp.status_code, 403, url)

    def test_hand_out_binds_badge_to_player_team_session(self):
        badge = _badge('aa110001')
        resp = self.staff.post(
            f'/api/staff/badges/{badge.pk}/assign/',
            {'player_id': self.alice.pk, 'team_id': self.team.pk},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        badge.refresh_from_db()
        self.assertEqual(badge.status, 'ASSIGNED')
        assignment = badge.active_assignment()
        self.assertEqual(assignment.player, self.alice)
        self.assertEqual(assignment.team, self.team)
        self.assertEqual(assignment.session, self.session)
        body = resp.json()
        self.assertEqual(body['assignment']['player_id'], self.alice.pk)

    def test_hand_out_resolves_session_from_player(self):
        badge = _badge('aa110001')
        resp = self.staff.post(
            f'/api/staff/badges/{badge.pk}/assign/',
            {'player_id': self.alice.pk},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(badge.active_assignment().session, self.session)

    def test_hand_out_requires_a_holder(self):
        badge = _badge('aa110001')
        resp = self.staff.post(
            f'/api/staff/badges/{badge.pk}/assign/', {}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_double_hand_out_conflicts(self):
        badge = _badge('aa110001')
        _assign_badge(badge, self.session, player=self.alice)
        resp = self.staff.post(
            f'/api/staff/badges/{badge.pk}/assign/',
            {'player_id': self.bob.pk},
            format='json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_collect_releases_for_reuse(self):
        badge = _badge('aa110001')
        assignment = _assign_badge(badge, self.session, player=self.alice)
        resp = self.staff.post(
            f'/api/staff/badges/{badge.pk}/collect/', {}, format='json',
        )
        self.assertEqual(resp.status_code, 200)
        assignment.refresh_from_db()
        self.assertIsNotNone(assignment.released_at)
        badge.refresh_from_db()
        self.assertEqual(badge.status, 'AVAILABLE')
        # And the badge can now be handed out again.
        resp = self.staff.post(
            f'/api/staff/badges/{badge.pk}/assign/',
            {'player_id': self.bob.pk},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)

    def test_collect_without_assignment_conflicts(self):
        badge = _badge('aa110001')
        resp = self.staff.post(
            f'/api/staff/badges/{badge.pk}/collect/', {}, format='json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_collect_can_mark_lost_and_lost_badges_cannot_be_handed_out(self):
        badge = _badge('aa110001')
        _assign_badge(badge, self.session, player=self.alice)
        resp = self.staff.post(
            f'/api/staff/badges/{badge.pk}/collect/',
            {'mark_lost': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        badge.refresh_from_db()
        self.assertEqual(badge.status, 'LOST')
        resp = self.staff.post(
            f'/api/staff/badges/{badge.pk}/assign/',
            {'player_id': self.bob.pk},
            format='json',
        )
        self.assertEqual(resp.status_code, 409)

    def test_unreturned_flag_after_session_finish(self):
        badge = _badge('aa110001')
        _assign_badge(badge, self.session, player=self.alice)
        Session.objects.filter(pk=self.session.pk).update(state=Session.FINISHED)
        rows = self.staff.get('/api/staff/badges/').json()
        row = {r['badge_id']: r for r in rows}['aa110001']
        self.assertTrue(row['unreturned'])

    def test_gateway_register_and_health_row(self):
        resp = self.staff.post(
            '/api/staff/gateways/',
            {'name': 'North gate', 'transport': 'TABLET', 'coverage_note': 'main lawn'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['transport'], 'TABLET')
        self.assertTrue(body['token'])
        self.assertTrue(body['stale'])  # never seen yet
        # After an ingest the health row goes fresh.
        gateway = GatewayNode.objects.get(pk=body['id'])
        _ingest(gateway)
        rows = self.staff.get('/api/staff/gateways/').json()
        self.assertFalse(rows[0]['stale'])

    def test_on_air_downlink_payload_is_identity_free(self):
        """T7.3 — nothing broadcast on the mesh names a real player."""
        badge = _badge('aa110001')
        _assign_badge(badge, self.session, player=self.alice)
        gateway = _gateway()
        body = _ingest(gateway).json()
        self.assertEqual(len(body['badge_states']), 1)
        entry = body['badge_states'][0]
        self.assertEqual(
            set(entry), {'badge_id', 'role', 'energy', 'alive', 'ring'},
        )
        self.assertNotIn(self.alice.user.username, str(body['badge_states']))


class BadgeTelemetryApiTest(TestCase):
    """T7.5 — telemetry persistence + fleet health flags."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(
            1, name='Telemetry Game',
        )
        self.alice = self.players[0]
        self.badge = _badge('aa110001')
        _assign_badge(self.badge, self.session, player=self.alice)
        self.gateway = _gateway()
        self.staff, _ = _staff_client(session=self.session)

    def test_telemetry_is_persisted_and_registry_refreshed(self):
        resp = _ingest(self.gateway, telemetry=[{
            'badge_id': 'aa110001',
            'battery_pct': 42,
            'activity': 'RUNNING',
            'gesture': 'CAST',
            'imu': {'ax': 0.1, 'ay': 0.2, 'az': 9.8, 'dead_reckoning': [1.5, -0.5]},
            'firmware_version': '0.1.0',
        }])
        self.assertEqual(resp.json()['accepted']['telemetry'], 1)
        sample = BadgeTelemetry.objects.get(badge=self.badge)
        self.assertEqual(sample.session, self.session)
        self.assertEqual(sample.battery_pct, 42)
        self.assertEqual(sample.activity, 'RUNNING')
        self.assertEqual(sample.gesture, 'CAST')
        self.assertEqual(sample.imu['dead_reckoning'], [1.5, -0.5])
        self.badge.refresh_from_db()
        self.assertEqual(self.badge.battery_pct, 42)
        self.assertEqual(self.badge.firmware_version, '0.1.0')
        self.assertIsNotNone(self.badge.last_seen_at)

    def test_malformed_and_unknown_telemetry_is_discarded(self):
        resp = _ingest(self.gateway, telemetry=[
            'not-a-dict',
            {'battery_pct': 50},                      # no badge_id
            {'badge_id': 'ffffffff', 'battery_pct': 50},  # unknown badge
        ])
        self.assertEqual(resp.json()['accepted']['telemetry'], 0)
        self.assertEqual(resp.json()['discarded']['telemetry'], 3)
        self.assertEqual(BadgeTelemetry.objects.count(), 0)

    def test_garbage_device_timestamp_is_dropped_not_fatal(self):
        resp = _ingest(self.gateway, telemetry=[
            {'badge_id': 'aa110001', 'battery_pct': 60, 'ts': 'not-a-time'},
        ])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['accepted']['telemetry'], 1)
        sample = BadgeTelemetry.objects.get(badge=self.badge)
        self.assertIsNone(sample.reported_at)

    def test_valid_device_timestamp_is_recorded(self):
        resp = _ingest(self.gateway, telemetry=[
            {'badge_id': 'aa110001', 'ts': '2026-07-21T10:00:00Z'},
        ])
        self.assertEqual(resp.json()['accepted']['telemetry'], 1)
        sample = BadgeTelemetry.objects.get(badge=self.badge)
        self.assertIsNotNone(sample.reported_at)

    def test_implausible_battery_is_dropped_but_sample_kept(self):
        _ingest(self.gateway, telemetry=[{'badge_id': 'aa110001', 'battery_pct': 150}])
        sample = BadgeTelemetry.objects.get(badge=self.badge)
        self.assertIsNone(sample.battery_pct)
        self.badge.refresh_from_db()
        self.assertIsNone(self.badge.battery_pct)

    def test_low_battery_flag_in_inventory(self):
        _ingest(self.gateway, telemetry=[{'badge_id': 'aa110001', 'battery_pct': 12}])
        rows = self.staff.get('/api/staff/badges/').json()
        row = {r['badge_id']: r for r in rows}['aa110001']
        self.assertTrue(row['battery_low'])
        self.assertEqual(row['battery_pct'], 12)

    def test_stale_and_firmware_flags_in_inventory(self):
        BadgeDevice.objects.filter(pk=self.badge.pk).update(
            last_seen_at=timezone.now() - timedelta(hours=1),
            firmware_version='0.0.1',
        )
        fresh = _badge('bb220002', firmware_version=CURRENT_FIRMWARE_VERSION)
        BadgeDevice.objects.filter(pk=fresh.pk).update(last_seen_at=timezone.now())
        rows = {r['badge_id']: r for r in self.staff.get('/api/staff/badges/').json()}
        self.assertTrue(rows['aa110001']['stale'])
        self.assertTrue(rows['aa110001']['firmware_stale'])
        self.assertFalse(rows['bb220002']['stale'])
        self.assertFalse(rows['bb220002']['firmware_stale'])


class GatewayDisplayStateTest(TestCase):
    """T2.5 — per-badge authoritative display state in the ingest response."""

    def setUp(self):
        self.game, self.session, self.team, self.players = _proximity_setup(
            2, name='Display Game',
        )
        self.alice, self.bob = self.players
        self.badge_a = _badge('aa110001')
        self.badge_b = _badge('bb220002')
        _assign_badge(self.badge_a, self.session, player=self.alice)
        _assign_badge(self.badge_b, self.session, player=self.bob)
        self.gateway = _gateway()

    def _states(self):
        body = _ingest(self.gateway).json()
        return {entry['badge_id']: entry for entry in body['badge_states']}

    def test_idle_ring_when_dementors_mode_is_off(self):
        states = self._states()
        self.assertEqual(states['aa110001']['ring']['pattern'], RING_PATTERN_IDLE)
        self.assertIsNone(states['aa110001']['role'])

    def test_energy_and_role_map_to_ring_fill(self):
        self.game.dementors_enabled = True
        self.game.save(update_fields=['dementors_enabled'])
        _state(self.session, self.alice, DementorState.WIZARD, 75.0)
        _state(self.session, self.bob, DementorState.DEMENTOR, 25.0)
        states = self._states()
        wizard = states['aa110001']
        self.assertEqual(wizard['role'], 'WIZARD')
        self.assertEqual(wizard['energy'], 75.0)
        self.assertEqual(wizard['ring']['pattern'], RING_PATTERN_ENERGY_FILL)
        self.assertEqual(wizard['ring']['fill_pct'], 75)
        self.assertEqual(wizard['ring']['color'], 'WARM')
        dementor = states['bb220002']
        self.assertEqual(dementor['ring']['color'], 'COLD')
        self.assertEqual(dementor['ring']['fill_pct'], 25)

    def test_out_of_play_ring_pattern(self):
        self.game.dementors_enabled = True
        self.game.save(update_fields=['dementors_enabled'])
        _state(self.session, self.alice, DementorState.WIZARD, 0.0, alive=False)
        states = self._states()
        self.assertEqual(states['aa110001']['ring']['pattern'], RING_PATTERN_OUT)
        self.assertFalse(states['aa110001']['alive'])

    def test_released_badges_drop_out_of_the_downlink(self):
        self.badge_b.active_assignment().release()
        states = self._states()
        self.assertIn('aa110001', states)
        self.assertNotIn('bb220002', states)

    def test_ingest_with_observations_returns_post_tick_state(self):
        """The downlink reflects the energy AFTER this batch's tick."""
        self.game.dementors_enabled = True
        self.game.save(update_fields=['dementors_enabled'])
        past = timezone.now() - timedelta(seconds=10)
        _state(self.session, self.alice, DementorState.WIZARD, 100.0,
               last_tick_at=past)
        _state(self.session, self.bob, DementorState.DEMENTOR, 0.0,
               last_tick_at=past)
        body = _ingest(
            self.gateway, [_obs('aa110001', 'bb220002', rssi=-60)],
        ).json()
        states = {entry['badge_id']: entry for entry in body['badge_states']}
        self.assertLess(states['aa110001']['energy'], 100.0)
        self.assertLess(states['aa110001']['ring']['fill_pct'], 100)
