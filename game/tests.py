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
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from game.admin import unassign_all
from game.models import (
    ROLE_REQUIREMENT_ALL,
    ROLE_REQUIREMENT_ANY,
    ROLE_REQUIREMENT_NONE,
    Challenge,
    Collection,
    PauseWindow,
    TeamTowerChallenge,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    TeamZoneOwnership,
    Tower,
    TowerLock,
    Zone,
)
from organize.models import (
    TOWER_LOCK_FREE_FOR_ALL,
    TOWER_LOCK_ON_INITIATE,
    Game,
    GameCollaborator,
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


def _game_collection(game):
    """Return (creating + linking if needed) the Game's default Collection.

    Post points-repository, geometry reaches a Game only through
    Collections, so the fixture helpers attach every Zone/Tower they
    create to a per-game default collection.
    """
    collection = game.collections.order_by('pk').first()
    if collection is None:
        collection = Collection.objects.create(
            name=f'{game.name} map', slug=f'{game.slug}-map',
        )
        game.collections.add(collection)
    return collection


def _make_zone(game, name="Zone A", scoring=Zone.SCORE_LIN, shape=None):
    if shape is None:
        shape = Polygon.from_bbox((23.0, 46.0, 24.0, 47.0))
    zone = Zone.objects.create(name=name, scoring_type=scoring, shape=shape)
    _game_collection(game).zones.add(zone)
    return zone


def _make_tower(game, name="T", zone=None, lng=23.5, lat=46.5, is_active=True,
                initial_bonus=0, category=Tower.CATEGORY_NORMAL, rfid_code=None):
    tower = Tower.objects.create(
        name=name, zone=zone, location=Point(lng, lat), is_active=is_active,
        category=category, initial_bonus=initial_bonus, rfid_code=rfid_code,
    )
    _game_collection(game).towers.add(tower)
    return tower


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
# Points repository & collections (change: points-repository-and-collections)
# ---------------------------------------------------------------------------


class CollectionModelTest(TestCase):
    """Task 1.1 — Collection fields + membership semantics."""

    def test_collection_fields(self):
        user = User.objects.create_user(
            username='curator', email='c@x.com', password='pw',
        )
        collection = Collection.objects.create(
            name='Old town', slug='old-town',
            description='Historic centre points', created_by=user,
        )
        self.assertEqual(str(collection), 'Old town')
        self.assertEqual(collection.slug, 'old-town')
        self.assertEqual(collection.created_by, user)
        self.assertIsNotNone(collection.created_at)

    def test_slug_is_unique(self):
        from django.db import IntegrityError
        Collection.objects.create(name='A', slug='same')
        with self.assertRaises(IntegrityError):
            Collection.objects.create(name='B', slug='same')

    def test_membership_removal_keeps_repository_rows(self):
        collection = Collection.objects.create(name='Map', slug='map')
        zone = Zone.objects.create(
            name='Z', scoring_type=Zone.SCORE_LIN,
            shape=Polygon.from_bbox((23.0, 46.0, 24.0, 47.0)),
        )
        tower = Tower.objects.create(
            name='T', zone=zone, location=Point(23.5, 46.5),
            is_active=True, category=Tower.CATEGORY_NORMAL,
        )
        collection.zones.add(zone)
        collection.towers.add(tower)

        collection.towers.remove(tower)
        collection.zones.remove(zone)
        # Orphan library assets survive with no collection memberships.
        tower.refresh_from_db()
        zone.refresh_from_db()
        self.assertEqual(tower.collections.count(), 0)
        self.assertEqual(zone.collections.count(), 0)

    def test_asset_may_belong_to_multiple_collections(self):
        tower = Tower.objects.create(
            name='T', location=Point(23.5, 46.5),
            is_active=True, category=Tower.CATEGORY_NORMAL,
        )
        c1 = Collection.objects.create(name='One', slug='one')
        c2 = Collection.objects.create(name='Two', slug='two')
        c1.towers.add(tower)
        c2.towers.add(tower)
        self.assertEqual(tower.collections.count(), 2)


class GeometryResolverTest(TestCase):
    """Tasks 1.2 / 1.3 — Game and Session geometry resolvers."""

    def test_game_resolvers_return_collection_members(self):
        game = _make_game(name='Resolver Game')
        zone = _make_zone(game)
        tower = _make_tower(game, zone=zone)
        self.assertEqual(list(game.towers()), [tower])
        self.assertEqual(list(game.zones()), [zone])

    def test_distinct_union_across_multiple_collections(self):
        game = _make_game(name='Union Game')
        t1 = _make_tower(game, name='T1')
        # A second collection holding a new tower AND the first tower.
        extra = Collection.objects.create(name='Extra map', slug='extra-map')
        t2 = Tower.objects.create(
            name='T2', location=Point(23.6, 46.6),
            is_active=True, category=Tower.CATEGORY_NORMAL,
        )
        extra.towers.add(t1, t2)
        game.collections.add(extra)
        towers = list(game.towers())
        self.assertEqual(len(towers), 2)  # t1 not duplicated
        self.assertEqual(set(towers), {t1, t2})

    def test_game_without_collections_sees_no_geometry(self):
        game = _make_game(name='Bare Game')
        self.assertEqual(game.towers().count(), 0)
        self.assertEqual(game.zones().count(), 0)

    def test_session_resolvers_delegate_to_game(self):
        game = _make_game(name='Delegate Game')
        zone = _make_zone(game)
        tower = _make_tower(game, zone=zone)
        session = _default_session(game)
        self.assertEqual(list(session.towers()), [tower])
        self.assertEqual(list(session.zones()), [zone])


class SharedCollectionTest(TestCase):
    """Task 6.2 — two Games linking the same Collection share rows by PK,
    while ownership records stay per-Session."""

    def setUp(self):
        self.game_a = _make_game(name='Shared A', slug='shared-a')
        self.game_b = _make_game(name='Shared B', slug='shared-b')
        self.zone = _make_zone(self.game_a, name='SharedZone')
        self.tower = _make_tower(self.game_a, zone=self.zone, name='SharedTower')
        # Link Game A's collection into Game B too — one map, two games.
        self.collection = self.game_a.collections.first()
        self.game_b.collections.add(self.collection)
        self.group_a = _make_group(self.game_a, slug='sa')
        self.group_b = _make_group(self.game_b, slug='sb')
        self.team_a = _make_team(self.game_a, self.group_a, name='team-sa')
        self.team_b = _make_team(self.game_b, self.group_b, name='team-sb')
        self.client_a, _ = _authed_client(self.team_a, username='shared-a')
        self.client_b, _ = _authed_client(self.team_b, username='shared-b')

    def test_both_games_resolve_identical_tower_rows(self):
        self.assertEqual(
            list(self.game_a.towers().values_list('pk', flat=True)),
            list(self.game_b.towers().values_list('pk', flat=True)),
        )
        ids_a = {t['id'] for t in self.client_a.get('/api/towers/').json()}
        ids_b = {t['id'] for t in self.client_b.get('/api/towers/').json()}
        self.assertEqual(ids_a, {self.tower.id})
        self.assertEqual(ids_b, {self.tower.id})

    def test_both_games_resolve_identical_zone_rows(self):
        names_a = [z['name'] for z in self.client_a.get('/api/zones/').json()]
        names_b = [z['name'] for z in self.client_b.get('/api/zones/').json()]
        self.assertEqual(names_a, ['SharedZone'])
        self.assertEqual(names_b, ['SharedZone'])

    def test_ownership_never_leaks_between_games(self):
        self.tower.assign_to_team(self.team_a)
        self.assertEqual(self.tower.tower_control(self.group_a), self.team_a)
        # Game B's group sees the shared tower as uncontrolled.
        self.assertIsNone(self.tower.tower_control(self.group_b))
        # And no ownership rows exist for Game B's session.
        self.assertFalse(
            TeamTowerOwnership.objects.filter(
                team__session=self.team_b.session,
            ).exists(),
        )


class CollectionAPITest(TestCase):
    """Tasks 4.1 / 4.2 / 4.3 — collections CRUD, membership, repository
    scoping and usage reporting."""

    def setUp(self):
        self.game = _make_game(name='Repo Game')
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game, name='RZ')
        self.tower = _make_tower(self.game, name='RT', zone=self.zone)
        self.collection = self.game.collections.first()
        self.team = _make_team(self.game, self.group)
        self.staff_client, self.staff = _staff_client(
            session=self.team.session, username='repo-admin',
        )
        self.player_client, _ = _authed_client(self.team, username='repo-player')

    def test_collections_require_staff(self):
        self.assertEqual(
            self.player_client.get('/api/staff/collections/').status_code, 403,
        )

    def test_collection_crud(self):
        resp = self.staff_client.post(
            '/api/staff/collections/',
            {'name': 'New Map', 'description': 'Fresh'},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['slug'], 'new-map')  # auto-generated
        self.assertEqual(body['created_by'], self.staff.id)
        collection_id = body['id']

        resp = self.staff_client.get('/api/staff/collections/')
        self.assertEqual(resp.status_code, 200)
        names = [c['name'] for c in resp.json()]
        self.assertIn('New Map', names)

        resp = self.staff_client.patch(
            f'/api/staff/collections/{collection_id}/',
            {'name': 'Renamed Map'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['name'], 'Renamed Map')

        resp = self.staff_client.delete(
            f'/api/staff/collections/{collection_id}/',
        )
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Collection.objects.filter(pk=collection_id).exists())

    def test_deleting_collection_keeps_repository_rows(self):
        tower_pk = self.tower.pk
        resp = self.staff_client.delete(
            f'/api/staff/collections/{self.collection.id}/',
        )
        self.assertEqual(resp.status_code, 204)
        self.assertTrue(Tower.objects.filter(pk=tower_pk).exists())

    def test_membership_add_and_remove(self):
        resp = self.staff_client.post(
            '/api/staff/collections/', {'name': 'Curated'}, format='json',
        )
        cid = resp.json()['id']

        resp = self.staff_client.post(
            f'/api/staff/collections/{cid}/add-towers/',
            {'tower_ids': [self.tower.id]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['towers'], [self.tower.id])

        resp = self.staff_client.post(
            f'/api/staff/collections/{cid}/add-zones/',
            {'zone_ids': [self.zone.id]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['zones'], [self.zone.id])

        resp = self.staff_client.post(
            f'/api/staff/collections/{cid}/remove-towers/',
            {'tower_ids': [self.tower.id]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['towers'], [])
        # Removal only touched membership.
        self.assertTrue(Tower.objects.filter(pk=self.tower.pk).exists())

        resp = self.staff_client.post(
            f'/api/staff/collections/{cid}/remove-zones/',
            {'zone_ids': [self.zone.id]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['zones'], [])

    def test_membership_rejects_unknown_ids(self):
        resp = self.staff_client.post(
            f'/api/staff/collections/{self.collection.id}/add-towers/',
            {'tower_ids': [999999]},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.staff_client.post(
            f'/api/staff/collections/{self.collection.id}/add-towers/',
            {'tower_ids': 'nope'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_staff_towers_are_repository_scoped_with_collection_filter(self):
        # A tower in a different collection, not linked to any game.
        other_collection = Collection.objects.create(name='Other', slug='other')
        other_tower = Tower.objects.create(
            name='Elsewhere', location=Point(24.0, 47.0),
            is_active=True, category=Tower.CATEGORY_NORMAL,
        )
        other_collection.towers.add(other_tower)

        # Unfiltered: the whole repository is visible to staff.
        resp = self.staff_client.get('/api/staff/towers/')
        ids = {t['id'] for t in resp.json()}
        self.assertEqual(ids, {self.tower.id, other_tower.id})

        # Filtered by collection.
        resp = self.staff_client.get(
            f'/api/staff/towers/?collection={other_collection.id}',
        )
        ids = {t['id'] for t in resp.json()}
        self.assertEqual(ids, {other_tower.id})

        resp = self.staff_client.get(
            f'/api/staff/zones/?collection={self.collection.id}',
        )
        self.assertEqual(
            {z['id'] for z in resp.json()}, {self.zone.id},
        )

    def test_usage_reporting_on_towers_and_zones(self):
        resp = self.staff_client.get(f'/api/staff/towers/{self.tower.id}/')
        body = resp.json()
        self.assertEqual(
            body['collections'],
            [{'id': self.collection.id, 'name': self.collection.name}],
        )
        self.assertEqual(
            body['games'], [{'id': self.game.id, 'name': self.game.name}],
        )

        resp = self.staff_client.get(f'/api/staff/zones/{self.zone.id}/')
        body = resp.json()
        self.assertEqual(
            [c['id'] for c in body['collections']], [self.collection.id],
        )
        self.assertEqual(
            [g['id'] for g in body['games']], [self.game.id],
        )


class CloneGameTest(TestCase):
    """Tasks 3.1–3.3 / 6.3 — creator vs runner roles and template cloning."""

    def setUp(self):
        self.game = _make_game(name='Original', slug='original')
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.challenge = Challenge.objects.create(
            text='original challenge', tower=self.tower,
            game=self.game, difficulty=1,
        )
        self.collection = self.game.collections.first()
        self.creator_client, self.creator = _staff_client(username='creator')
        self.game.created_by = self.creator
        self.game.save(update_fields=['created_by'])
        self.runner_client, self.runner = _staff_client(username='runner')

    def _clone(self, client=None, payload=None):
        return (client or self.runner_client).post(
            f'/api/staff/games/{self.game.id}/clone/',
            payload or {},
            format='json',
        )

    def test_clone_copies_template_and_shares_geometry(self):
        resp = self._clone()
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['cloned_from'], self.game.id)
        self.assertEqual(body['created_by'], self.runner.id)
        self.assertEqual(body['collections'], [self.collection.id])
        self.assertEqual(body['slug'], 'original-clone')
        self.assertFalse(body['is_active'])

        clone = Game.objects.get(pk=body['id'])
        # Geometry shared by PK — no new Tower/Zone rows.
        self.assertEqual(Tower.objects.count(), 1)
        self.assertEqual(Zone.objects.count(), 1)
        self.assertEqual(
            list(clone.towers().values_list('pk', flat=True)), [self.tower.pk],
        )
        self.assertEqual(
            list(clone.zones().values_list('pk', flat=True)), [self.zone.pk],
        )
        # Template rows deep-copied: new Challenge and TeamGroup rows.
        clone_challenge = clone.challenges.get()
        self.assertEqual(clone_challenge.text, 'original challenge')
        self.assertNotEqual(clone_challenge.pk, self.challenge.pk)
        self.assertEqual(clone_challenge.tower_id, self.tower.pk)  # shared tower
        clone_group = TeamGroup.objects.get(game=clone)
        self.assertEqual(clone_group.slug, self.group.slug)
        self.assertNotEqual(clone_group.pk, self.group.pk)
        # Rules config copied.
        self.assertEqual(clone.proximity_meters, self.game.proximity_meters)
        self.assertEqual(clone.cooloff_minutes, self.game.cooloff_minutes)

    def test_clone_accepts_custom_name_and_slug(self):
        resp = self._clone(payload={'name': 'My Run', 'slug': 'my-run'})
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['name'], 'My Run')
        self.assertEqual(resp.json()['slug'], 'my-run')

    def test_clone_rejects_duplicate_slug(self):
        resp = self._clone(payload={'slug': 'original'})
        self.assertEqual(resp.status_code, 400)

    def test_clone_edits_do_not_affect_original(self):
        clone_id = self._clone().json()['id']
        resp = self.runner_client.patch(
            f'/api/staff/games/{clone_id}/',
            {'cooloff_minutes': 9, 'name': 'Runner special'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.game.refresh_from_db()
        self.assertEqual(self.game.cooloff_minutes, 5)
        self.assertEqual(self.game.name, 'Original')

        # Runner adds a challenge to their clone — original bank untouched.
        resp = self.runner_client.post(
            '/api/staff/challenges/',
            {'game': clone_id, 'text': 'runner extra', 'difficulty': 2},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(self.game.challenges.count(), 1)
        self.assertEqual(Game.objects.get(pk=clone_id).challenges.count(), 2)

    def test_runner_cannot_mutate_original_template(self):
        resp = self.runner_client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'cooloff_minutes': 1},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)
        resp = self.runner_client.post(
            '/api/staff/challenges/',
            {'game': self.game.id, 'text': 'sneaky', 'difficulty': 1},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)
        resp = self.runner_client.delete(f'/api/staff/games/{self.game.id}/')
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Game.objects.filter(pk=self.game.pk).exists())

    def test_creator_can_mutate_own_template(self):
        resp = self.creator_client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'cooloff_minutes': 7},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.game.refresh_from_db()
        self.assertEqual(self.game.cooloff_minutes, 7)

    def test_creator_collaborator_can_edit(self):
        GameCollaborator.objects.create(
            game=self.game, user=self.runner,
            role=GameCollaborator.ROLE_CREATOR,
        )
        resp = self.runner_client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'cooloff_minutes': 8},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_runner_collaborator_cannot_edit(self):
        GameCollaborator.objects.create(
            game=self.game, user=self.runner,
            role=GameCollaborator.ROLE_RUNNER,
        )
        resp = self.runner_client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'cooloff_minutes': 8},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_legacy_game_without_creator_stays_open_to_staff(self):
        legacy = _make_game(name='Legacy Open', slug='legacy-open')
        resp = self.runner_client.patch(
            f'/api/staff/games/{legacy.id}/',
            {'cooloff_minutes': 3},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)

    def test_runner_can_run_sessions_under_foreign_game(self):
        # Runner may create + control a Session under the creator's game.
        now = timezone.now()
        resp = self.runner_client.post(
            '/api/staff/sessions/',
            {
                'game': self.game.id,
                'slug': 'runner-run',
                'name': 'Runner run',
                'start_time': now.isoformat(),
                'end_time': (now + timedelta(hours=2)).isoformat(),
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        session_id = resp.json()['id']
        # Sessions are born DRAFT under the lifecycle state machine, and
        # DRAFT→RUNNING needs a ready roster — out of scope here, where
        # only the runner *permission* is under test. Jump straight to
        # RUNNING and exercise pause/resume through the API.
        Session.objects.filter(pk=session_id).update(state=Session.RUNNING)
        resp = self.runner_client.post(f'/api/staff/sessions/{session_id}/pause/')
        self.assertEqual(resp.status_code, 200, resp.content)
        resp = self.runner_client.post(f'/api/staff/sessions/{session_id}/resume/')
        self.assertEqual(resp.status_code, 200, resp.content)


# ---------------------------------------------------------------------------
# tower-locking — identify → initiate → finish + locking modes
# ---------------------------------------------------------------------------


class TowerLockingBase(TestCase):
    """Shared fixture for the tower-locking scenarios.

    Game in LOCK_ON_INITIATE with a 15-minute finish window, one zone,
    one tower, two teams in the same group plus one team in a second
    group — enough to exercise contention and per-group isolation.
    """

    LOCK_MODE = TOWER_LOCK_ON_INITIATE

    def setUp(self):
        self.game = _make_game(name='Lock Game')
        self.game.tower_lock_mode = self.LOCK_MODE
        self.game.save(update_fields=['tower_lock_mode'])
        self.group = _make_group(self.game)
        self.other_group = _make_group(self.game, name='Temerari', slug='temerari')
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone, initial_bonus=10)
        self.session = _default_session(self.game)
        self.team1 = _make_team(self.game, self.group, name='alpha')
        self.team2 = _make_team(self.game, self.group, name='bravo', color='#663300')
        self.team3 = _make_team(
            self.game, self.other_group, name='charlie', color='#336600',
        )
        self.challenge = Challenge.objects.create(
            text='c1', tower=self.tower, difficulty=1, game=self.game,
        )
        self.client1, self.user1 = _authed_client(self.team1, username='p1')
        self.client2, self.user2 = _authed_client(self.team2, username='p2')
        self.client3, self.user3 = _authed_client(self.team3, username='p3')

    def _initiate(self, client, tower=None):
        tower = tower or self.tower
        return client.post(f'/api/towers/{tower.pk}/initiate/')

    def _submit(self, client, tower=None, challenge=None):
        tower = tower or self.tower
        return client.post(
            '/api/team_tower_challenges/',
            {
                'tower': tower.pk,
                'challenge': (challenge or self.challenge).pk,
                'lat': 46.5,
                'lng': 23.5,
            },
            format='json',
        )

    def _confirm(self, ttc_id):
        staff_client, _ = _staff_client(self.session, username=f'staff{ttc_id}')
        return staff_client.post(
            f'/api/staff/submissions/{ttc_id}/review/',
            {'outcome': 'confirm'},
            format='json',
        )

    def _expire_lock(self, lock):
        """Push a lock's deadline into the past without releasing it."""
        TowerLock.objects.filter(pk=lock.pk).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        lock.refresh_from_db()
        return lock


class TowerLockConfigTest(TestCase):
    """Task 7.1 — Session.effective resolves the two new knobs."""

    def setUp(self):
        self.game = _make_game()
        self.session = _default_session(self.game)

    def test_defaults_preserve_current_behavior(self):
        self.assertEqual(self.game.tower_lock_mode, TOWER_LOCK_FREE_FOR_ALL)
        self.assertEqual(self.game.tower_lock_finish_minutes, 15)
        self.assertEqual(
            self.session.effective('tower_lock_mode'), TOWER_LOCK_FREE_FOR_ALL,
        )
        self.assertEqual(self.session.effective('tower_lock_finish_minutes'), 15)

    def test_game_default_used_when_override_null(self):
        self.game.tower_lock_mode = TOWER_LOCK_ON_INITIATE
        self.game.tower_lock_finish_minutes = 30
        self.game.save()
        self.assertIsNone(self.session.tower_lock_mode)
        self.assertEqual(
            self.session.effective('tower_lock_mode'), TOWER_LOCK_ON_INITIATE,
        )
        self.assertEqual(self.session.effective('tower_lock_finish_minutes'), 30)

    def test_session_override_wins(self):
        self.session.tower_lock_mode = TOWER_LOCK_ON_INITIATE
        self.session.tower_lock_finish_minutes = 5
        self.session.save()
        self.assertEqual(
            self.session.effective('tower_lock_mode'), TOWER_LOCK_ON_INITIATE,
        )
        self.assertEqual(self.session.effective('tower_lock_finish_minutes'), 5)
        # The Game default is untouched.
        self.assertEqual(self.game.tower_lock_mode, TOWER_LOCK_FREE_FOR_ALL)


class TowerLockInitiateTest(TowerLockingBase):
    """Task 7.2 — initiate acquires a lock; contention within a group."""

    def test_initiate_creates_active_lock(self):
        resp = self._initiate(self.client1)
        self.assertEqual(resp.status_code, 201, resp.content)
        body = resp.json()
        self.assertEqual(body['tower_lock_mode'], TOWER_LOCK_ON_INITIATE)
        self.assertTrue(body['locked'])
        self.assertTrue(body['lock']['held_by_us'])
        self.assertEqual(body['lock']['team_id'], self.team1.id)

        lock = TowerLock.objects.get()
        self.assertEqual(lock.tower, self.tower)
        self.assertEqual(lock.team, self.team1)
        self.assertEqual(lock.group, self.group)
        self.assertTrue(lock.is_active())
        # expires_at = started_at + effective finish window (15 min).
        self.assertEqual(
            (lock.expires_at - lock.started_at), timedelta(minutes=15),
        )

    def test_initiate_uses_effective_finish_minutes(self):
        Session.objects.filter(pk=self.session.pk).update(
            tower_lock_finish_minutes=5,
        )
        self._initiate(self.client1)
        lock = TowerLock.objects.get()
        self.assertEqual(
            (lock.expires_at - lock.started_at), timedelta(minutes=5),
        )

    def test_second_team_same_group_blocked_from_initiating(self):
        self._initiate(self.client1)
        resp = self._initiate(self.client2)
        self.assertEqual(resp.status_code, 409, resp.content)
        body = resp.json()
        self.assertFalse(body['lock']['held_by_us'])
        self.assertEqual(body['lock']['team_id'], self.team1.id)
        self.assertEqual(TowerLock.objects.count(), 1)

    def test_second_team_same_group_blocked_from_finishing(self):
        self._initiate(self.client1)
        resp = self._submit(self.client2)
        self.assertEqual(resp.status_code, 409, resp.content)
        self.assertFalse(TeamTowerChallenge.objects.exists())

    def test_holder_reinitiate_is_idempotent(self):
        first = self._initiate(self.client1)
        again = self._initiate(self.client1)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertEqual(TowerLock.objects.count(), 1)
        self.assertEqual(
            again.json()['lock']['expires_at'],
            first.json()['lock']['expires_at'],
        )

    def test_initiate_requires_team_group(self):
        loner_team = _make_team(self.game, None, name='groupless', color='#111111')
        client, _ = _authed_client(loner_team, username='p4')
        resp = self._initiate(client)
        self.assertEqual(resp.status_code, 400)

    def test_submission_without_any_lock_is_accepted(self):
        # Initiating is the lock-acquisition point, but a finish is only
        # refused while ANOTHER team holds the active lock — a free tower
        # accepts a direct submission.
        resp = self._submit(self.client1)
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_voluntary_release_frees_the_tower(self):
        self._initiate(self.client1)
        resp = self.client1.post(f'/api/towers/{self.tower.pk}/release_lock/')
        self.assertEqual(resp.status_code, 200, resp.content)
        lock = TowerLock.objects.get()
        self.assertEqual(lock.release_reason, TowerLock.CANCELLED)
        self.assertIsNotNone(lock.released_at)
        # The other team may initiate immediately.
        resp = self._initiate(self.client2)
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_release_without_lock_conflicts(self):
        resp = self.client1.post(f'/api/towers/{self.tower.pk}/release_lock/')
        self.assertEqual(resp.status_code, 409)
        # A non-holder cannot release the holder's lock either.
        self._initiate(self.client1)
        resp = self.client2.post(f'/api/towers/{self.tower.pk}/release_lock/')
        self.assertEqual(resp.status_code, 409)
        self.assertTrue(TowerLock.objects.get().is_active())


class TowerLockFinishTest(TowerLockingBase):
    """Task 7.3 — a finish within the window captures + releases FINISHED."""

    def test_confirmed_finish_captures_and_releases(self):
        self._initiate(self.client1)
        submit = self._submit(self.client1)
        self.assertEqual(submit.status_code, 201, submit.content)
        ttc_id = submit.json()['id']

        confirm = self._confirm(ttc_id)
        self.assertEqual(confirm.status_code, 200, confirm.content)

        # Captured through assign_to_team: ownership window + bonus.
        ownership = TeamTowerOwnership.objects.get(
            tower=self.tower, timestamp_end__isnull=True,
        )
        self.assertEqual(ownership.team, self.team1)
        self.team1.refresh_from_db()
        self.assertEqual(self.team1.score, 10)

        lock = TowerLock.objects.get()
        self.assertEqual(lock.release_reason, TowerLock.FINISHED)
        self.assertIsNotNone(lock.released_at)
        self.assertFalse(lock.is_active())

        # Tower is lockable again by anyone in the group.
        resp = self._initiate(self.client2)
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_stale_finish_from_non_holder_cannot_be_confirmed(self):
        # team2 submits while the tower is free, then team1 locks it —
        # the pending (stale) finish from team2 must not confirm while
        # team1's lock is active.
        submit = self._submit(self.client2)
        self.assertEqual(submit.status_code, 201, submit.content)
        self._initiate(self.client1)

        confirm = self._confirm(submit.json()['id'])
        self.assertEqual(confirm.status_code, 409, confirm.content)
        self.assertFalse(TeamTowerOwnership.objects.exists())
        # The holder's own finish still confirms fine.
        own = self._submit(self.client1)
        self.assertEqual(self._confirm(own.json()['id']).status_code, 200)


class TowerLockExpiryTest(TowerLockingBase):
    """Task 7.4 — expiry frees the tower lazily and via the sweep."""

    def test_expired_lock_frees_initiation_lazily(self):
        self._initiate(self.client1)
        self._expire_lock(TowerLock.objects.get())

        # Lazy expiry: active_lock reads it as free…
        self.assertIsNone(self.tower.active_lock(self.group))
        # …and another team's initiate succeeds, stamping EXPIRED.
        resp = self._initiate(self.client2)
        self.assertEqual(resp.status_code, 201, resp.content)
        old = TowerLock.objects.get(team=self.team1)
        self.assertEqual(old.release_reason, TowerLock.EXPIRED)
        self.assertIsNotNone(old.released_at)

    def test_expired_lock_frees_submission_lazily(self):
        self._initiate(self.client1)
        self._expire_lock(TowerLock.objects.get())
        resp = self._submit(self.client2)
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_sweep_command_releases_expired_locks(self):
        self._initiate(self.client1)
        lock = self._expire_lock(TowerLock.objects.get())
        call_command('release_expired_locks')
        lock.refresh_from_db()
        self.assertEqual(lock.release_reason, TowerLock.EXPIRED)
        self.assertEqual(lock.released_at, lock.expires_at)
        # Idempotent: a second sweep changes nothing.
        self.assertEqual(TowerLock.sweep_expired(), 0)
        lock.refresh_from_db()
        self.assertEqual(lock.release_reason, TowerLock.EXPIRED)

    def test_expired_lock_opens_no_window_and_awards_nothing(self):
        self._initiate(self.client1)
        self._expire_lock(TowerLock.objects.get())
        call_command('release_expired_locks')
        self.assertFalse(TeamTowerOwnership.objects.exists())
        self.assertFalse(TeamZoneOwnership.objects.exists())
        self.team1.refresh_from_db()
        self.assertEqual(self.team1.score, 0)


class TowerLockGroupIsolationTest(TowerLockingBase):
    """Task 7.5 — a lock in one group never blocks another group."""

    def test_lock_does_not_block_other_group_initiate(self):
        self._initiate(self.client1)
        resp = self._initiate(self.client3)
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(TowerLock.objects.count(), 2)
        self.assertEqual(
            set(TowerLock.objects.values_list('group_id', flat=True)),
            {self.group.id, self.other_group.id},
        )

    def test_lock_does_not_block_other_group_finish(self):
        self._initiate(self.client1)
        submit = self._submit(self.client3)
        self.assertEqual(submit.status_code, 201, submit.content)
        confirm = self._confirm(submit.json()['id'])
        self.assertEqual(confirm.status_code, 200, confirm.content)
        # team3 owns the tower for ITS group; team1's lock is untouched.
        self.assertEqual(self.tower.tower_control(self.other_group), self.team3)
        self.assertTrue(TowerLock.objects.get(team=self.team1).is_active())

    def test_lock_state_reported_per_group(self):
        self._initiate(self.client1)
        # Same group: locked by another team.
        state2 = self.client2.get(f'/api/towers/{self.tower.pk}/state/').json()
        self.assertFalse(state2['lock']['held_by_us'])
        # Other group: free.
        state3 = self.client3.get(f'/api/towers/{self.tower.pk}/state/').json()
        self.assertIsNone(state3['lock'])


class FreeForAllModeTest(TowerLockingBase):
    """Task 7.6 — FREE_FOR_ALL preserves today's behavior exactly."""

    LOCK_MODE = TOWER_LOCK_FREE_FOR_ALL

    def test_initiate_is_a_noop_acknowledgement(self):
        resp = self._initiate(self.client1)
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['tower_lock_mode'], TOWER_LOCK_FREE_FOR_ALL)
        self.assertFalse(body['locked'])
        self.assertFalse(TowerLock.objects.exists())

    def test_simultaneous_attempts_allowed(self):
        self._initiate(self.client1)
        self._initiate(self.client2)
        resp1 = self._submit(self.client1)
        resp2 = self._submit(self.client2)
        self.assertEqual(resp1.status_code, 201, resp1.content)
        self.assertEqual(resp2.status_code, 201, resp2.content)
        self.assertFalse(TowerLock.objects.exists())

    def test_last_confirmed_finish_owns_the_tower(self):
        first = self._submit(self.client1)
        self.assertEqual(self._confirm(first.json()['id']).status_code, 200)
        self.assertEqual(self.tower.tower_control(self.group), self.team1)

        challenge2 = Challenge.objects.create(
            text='c2', tower=self.tower, difficulty=2, game=self.game,
        )
        second = self._submit(self.client2, challenge=challenge2)
        self.assertEqual(self._confirm(second.json()['id']).status_code, 200)

        # Ownership passed to the later finisher; the first team's
        # window is closed (accrual for exactly its hold interval).
        self.assertEqual(self.tower.tower_control(self.group), self.team2)
        first_window = TeamTowerOwnership.objects.get(team=self.team1)
        self.assertIsNotNone(first_window.timestamp_end)

    def test_rejection_cooldown_still_applies(self):
        submit = self._submit(self.client1)
        staff_client, _ = _staff_client(self.session, username='staffr')
        resp = staff_client.post(
            f'/api/staff/submissions/{submit.json()["id"]}/review/',
            {'outcome': 'reject'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertTrue(self.tower.team_in_cooloff(self.team1))
        self.assertFalse(self.tower.team_in_cooloff(self.team2))


class TowerLockScoringReconciliationTest(TowerLockingBase):
    """Task 7.7 — hold intervals accrue identically under LOCK_ON_INITIATE."""

    def test_hold_interval_runs_from_capture_to_next_capture(self):
        self._initiate(self.client1)
        first = self._submit(self.client1)
        self.assertEqual(self._confirm(first.json()['id']).status_code, 200)
        # team1 holds the tower (open window feeding zone control).
        window1 = TeamTowerOwnership.objects.get(team=self.team1)
        self.assertIsNone(window1.timestamp_end)
        self.assertEqual(
            list(self.zone.zone_control(self.group)), [self.team1.id],
        )

        # team2 locks and finishes the same tower.
        self._initiate(self.client2)
        challenge2 = Challenge.objects.create(
            text='c2', tower=self.tower, difficulty=2, game=self.game,
        )
        second = self._submit(self.client2, challenge=challenge2)
        self.assertEqual(self._confirm(second.json()['id']).status_code, 200)

        # team1's window closed at team2's capture; team2's window open.
        window1.refresh_from_db()
        window2 = TeamTowerOwnership.objects.get(team=self.team2)
        self.assertIsNotNone(window1.timestamp_end)
        self.assertIsNone(window2.timestamp_end)
        # timestamp_start is auto_now_add, so the handover close and the
        # new open differ by a few ms; the intervals are contiguous.
        self.assertLessEqual(window1.timestamp_end, window2.timestamp_start)
        self.assertLess(
            (window2.timestamp_start - window1.timestamp_end).total_seconds(), 1,
        )
        # Zone control follows the ownership windows.
        self.assertEqual(
            list(self.zone.zone_control(self.group)), [self.team2.id],
        )
        # Both locks released FINISHED.
        self.assertEqual(
            list(
                TowerLock.objects.order_by('started_at')
                .values_list('release_reason', flat=True),
            ),
            [TowerLock.FINISHED, TowerLock.FINISHED],
        )


class TowerLockConstraintTest(TestCase):
    """Task 7.8 — partial-unique active lock + idempotent release."""

    def setUp(self):
        self.game = _make_game(name='Constraint Game')
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.team1 = _make_team(self.game, self.group, name='alpha')
        self.team2 = _make_team(self.game, self.group, name='bravo', color='#663300')

    def _lock(self, team, **overrides):
        now = timezone.now()
        fields = dict(
            tower=self.tower, team=team, group=team.group,
            started_at=now, expires_at=now + timedelta(minutes=15),
        )
        fields.update(overrides)
        return TowerLock.objects.create(**fields)

    def test_second_active_lock_same_group_violates_constraint(self):
        self._lock(self.team1)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self._lock(self.team2)
        # A released first lock frees the constraint slot.
        TowerLock.objects.get().release(TowerLock.CANCELLED)
        self._lock(self.team2)
        self.assertEqual(TowerLock.objects.count(), 2)

    def test_concurrent_acquire_yields_exactly_one_lock(self):
        lock1, created1 = TowerLock.acquire(self.tower, self.team1, 15)
        lock2, created2 = TowerLock.acquire(self.tower, self.team2, 15)
        self.assertTrue(created1)
        self.assertIsNotNone(lock1)
        self.assertIsNone(lock2)
        self.assertFalse(created2)
        self.assertEqual(TowerLock.objects.count(), 1)

    def test_release_is_idempotent(self):
        lock = self._lock(self.team1)
        self.assertTrue(lock.release(TowerLock.CANCELLED))
        first_release_at = lock.released_at
        # A second release (any reason) is a no-op: first writer wins.
        self.assertFalse(lock.release(TowerLock.EXPIRED))
        lock.refresh_from_db()
        self.assertEqual(lock.release_reason, TowerLock.CANCELLED)
        self.assertEqual(lock.released_at, first_release_at)

    def test_sweep_does_not_touch_released_locks(self):
        lock = self._lock(
            self.team1, expires_at=timezone.now() - timedelta(minutes=1),
        )
        lock.release(TowerLock.CANCELLED)
        self.assertEqual(TowerLock.sweep_expired(), 0)
        lock.refresh_from_db()
        self.assertEqual(lock.release_reason, TowerLock.CANCELLED)


class TowerIdentifyEndpointTest(TowerLockingBase):
    """Task 3.1 — identify serves the next challenge with no side effects."""

    def test_identify_returns_next_challenge(self):
        resp = self.client1.post(f'/api/towers/{self.tower.pk}/identify/')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(body['next_challenge']['id'], self.challenge.pk)
        self.assertEqual(body['tower_lock_mode'], TOWER_LOCK_ON_INITIATE)
        self.assertIsNone(body['lock'])

    def test_identify_is_repeatable_and_side_effect_free(self):
        first = self.client1.post(f'/api/towers/{self.tower.pk}/identify/')
        second = self.client1.post(f'/api/towers/{self.tower.pk}/identify/')
        self.assertEqual(first.json(), second.json())
        self.assertFalse(TowerLock.objects.exists())
        self.assertFalse(TeamTowerChallenge.objects.exists())

    def test_identify_reports_foreign_lock(self):
        self._initiate(self.client1)
        resp = self.client2.post(f'/api/towers/{self.tower.pk}/identify/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()['lock']['held_by_us'])

    def test_identify_requires_team(self):
        user = User.objects.create_user(
            username='lone-identify', email='li@x.com', password='password123',
        )
        token = Token.objects.create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        resp = client.post(f'/api/towers/{self.tower.pk}/identify/')
        self.assertEqual(resp.status_code, 404)


class TowerStateLockPayloadTest(TowerLockingBase):
    """Task 6.2 backend — tower state exposes lock mode + countdown data."""

    def test_state_reports_free_tower(self):
        body = self.client1.get(f'/api/towers/{self.tower.pk}/state/').json()
        self.assertEqual(body['tower_lock_mode'], TOWER_LOCK_ON_INITIATE)
        self.assertIsNone(body['lock'])

    def test_state_reports_lock_held_by_us_with_deadline(self):
        self._initiate(self.client1)
        body = self.client1.get(f'/api/towers/{self.tower.pk}/state/').json()
        lock = body['lock']
        self.assertTrue(lock['held_by_us'])
        self.assertEqual(lock['team_id'], self.team1.id)
        self.assertGreater(lock['remaining_seconds'], 14 * 60)
        self.assertLessEqual(lock['remaining_seconds'], 15 * 60)

    def test_state_reports_lock_held_by_other(self):
        self._initiate(self.client1)
        body = self.client2.get(f'/api/towers/{self.tower.pk}/state/').json()
        self.assertFalse(body['lock']['held_by_us'])
        self.assertEqual(body['lock']['team_name'], 'alpha')

    def test_state_hides_expired_lock(self):
        self._initiate(self.client1)
        self._expire_lock(TowerLock.objects.get())
        body = self.client1.get(f'/api/towers/{self.tower.pk}/state/').json()
        self.assertIsNone(body['lock'])


class StaffTowerLockEndpointTest(TowerLockingBase):
    """Task 6.1 / 3.5 — staff active-lock list + cancel."""

    def setUp(self):
        super().setUp()
        self.staff_client, self.staff = _staff_client(
            self.session, username='lockstaff',
        )

    def test_lists_only_active_locks(self):
        self._initiate(self.client1)
        # A released lock and an expired lock must not be listed.
        cancelled = TowerLock.objects.create(
            tower=self.tower, team=self.team3, group=self.other_group,
            started_at=timezone.now(),
            expires_at=timezone.now() + timedelta(minutes=15),
        )
        cancelled.release(TowerLock.CANCELLED)
        other_tower = _make_tower(self.game, zone=self.zone, name='T2', lng=23.6)
        expired = TowerLock.objects.create(
            tower=other_tower, team=self.team2, group=self.group,
            started_at=timezone.now() - timedelta(minutes=30),
            expires_at=timezone.now() - timedelta(minutes=15),
        )

        resp = self.staff_client.get('/api/staff/tower_locks/')
        self.assertEqual(resp.status_code, 200, resp.content)
        body = resp.json()
        self.assertEqual(len(body), 1)
        entry = body[0]
        self.assertEqual(entry['tower'], self.tower.pk)
        self.assertEqual(entry['tower_name'], self.tower.name)
        self.assertEqual(entry['team'], self.team1.pk)
        self.assertEqual(entry['team_name'], 'alpha')
        self.assertEqual(entry['group'], self.group.pk)
        self.assertGreater(entry['remaining_seconds'], 0)
        self.assertNotIn(expired.pk, [e['id'] for e in body])

    def test_requires_staff(self):
        resp = self.client1.get('/api/staff/tower_locks/')
        self.assertEqual(resp.status_code, 403)

    def test_scoped_to_current_session(self):
        self._initiate(self.client1)
        other_game = _make_game(name='Other Lock Game')
        other_session = _default_session(other_game)
        foreign_staff, _ = _staff_client(other_session, username='otherstaff')
        resp = foreign_staff.get('/api/staff/tower_locks/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_staff_cancel_releases_lock(self):
        self._initiate(self.client1)
        lock = TowerLock.objects.get()
        resp = self.staff_client.post(f'/api/staff/tower_locks/{lock.pk}/cancel/')
        self.assertEqual(resp.status_code, 200, resp.content)
        lock.refresh_from_db()
        self.assertEqual(lock.release_reason, TowerLock.CANCELLED)
        self.assertIsNotNone(lock.released_at)
        # Cancelling again conflicts (no longer active).
        resp = self.staff_client.post(f'/api/staff/tower_locks/{lock.pk}/cancel/')
        self.assertEqual(resp.status_code, 409)
        # And the tower is free for the group again.
        self.assertEqual(self._initiate(self.client2).status_code, 201)


class CollectionBackfillMigrationTest(TransactionTestCase):
    """Task 6.1 — the data migration gives every existing Game a
    Collection resolving the exact Towers/Zones it owned before."""

    # Pre-backfill state: Collection exists, Tower.game/Zone.game still present.
    migrate_from = [
        ('game', '0022_collection'),
        ('organize', '0011_game_collections_roles_cloning'),
        # Sibling branch heads (team-roles, lifecycle-states, team-rules,
        # player-team-formation): their NOT NULL columns exist in the
        # test DB, so the historical project state must include them for
        # inserts through the old models to succeed.
        ('game', '0022_challenge_role_requirements'),
        ('organize', '0016_merge_20260720_2357'),
    ]
    # Post-removal state: geometry reachable only through collections.
    migrate_to = [('game', '0024_remove_tower_zone_game_fk')]

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        # Leave the schema at head for the rest of the suite.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_each_game_resolves_identical_geometry_after_migration(self):
        old_apps = self._migrate(self.migrate_from)
        OldGame = old_apps.get_model('organize', 'Game')
        OldZone = old_apps.get_model('game', 'Zone')
        OldTower = old_apps.get_model('game', 'Tower')

        bbox = Polygon.from_bbox((23.0, 46.0, 24.0, 47.0))
        g1 = OldGame.objects.create(name='Legacy One', slug='legacy-one')
        g2 = OldGame.objects.create(name='Legacy Two', slug='legacy-two')
        z1 = OldZone.objects.create(
            name='Z1', scoring_type=3, shape=bbox, game=g1, color='#000000',
        )
        z2 = OldZone.objects.create(
            name='Z2', scoring_type=3, shape=bbox, game=g2, color='#000000',
        )
        t1a = OldTower.objects.create(
            name='T1a', game=g1, zone=z1, location=Point(23.5, 46.5),
            is_active=True, category=1,
        )
        t1b = OldTower.objects.create(
            name='T1b', game=g1, zone=z1, location=Point(23.6, 46.6),
            is_active=True, category=1,
        )
        t2 = OldTower.objects.create(
            name='T2', game=g2, zone=z2, location=Point(23.7, 46.7),
            is_active=True, category=1,
        )

        new_apps = self._migrate(self.migrate_to)
        NewGame = new_apps.get_model('organize', 'Game')
        NewCollection = new_apps.get_model('game', 'Collection')
        NewTower = new_apps.get_model('game', 'Tower')
        NewZone = new_apps.get_model('game', 'Zone')

        # One collection per game, named '<game name> map'.
        c1 = NewCollection.objects.get(name='Legacy One map')
        c2 = NewCollection.objects.get(name='Legacy Two map')

        game1 = NewGame.objects.get(slug='legacy-one')
        game2 = NewGame.objects.get(slug='legacy-two')
        self.assertEqual(
            [c.pk for c in game1.collections.all()], [c1.pk],
        )
        self.assertEqual(
            [c.pk for c in game2.collections.all()], [c2.pk],
        )

        # Exactly the same Tower/Zone rows resolve for each game.
        self.assertEqual(
            set(NewTower.objects.filter(collections__games=game1)
                .values_list('pk', flat=True)),
            {t1a.pk, t1b.pk},
        )
        self.assertEqual(
            set(NewZone.objects.filter(collections__games=game1)
                .values_list('pk', flat=True)),
            {z1.pk},
        )
        self.assertEqual(
            set(NewTower.objects.filter(collections__games=game2)
                .values_list('pk', flat=True)),
            {t2.pk},
        )
        self.assertEqual(
            set(NewZone.objects.filter(collections__games=game2)
                .values_list('pk', flat=True)),
            {z2.pk},
        )
