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
import json
import math
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from unittest.mock import patch

from channels.db import database_sync_to_async
from channels.testing import HttpCommunicator, WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point, Polygon
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from game import events
from game.admin import unassign_all
from game.models import (
    ROLE_REQUIREMENT_ALL,
    ROLE_REQUIREMENT_ANY,
    ROLE_REQUIREMENT_NONE,
    Challenge,
    Collection,
    LocationConsent,
    LocationPing,
    PauseWindow,
    PresenceCheck,
    PresenceRequirement,
    TeamTowerChallenge,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    TeamZoneOwnership,
    Tower,
    TowerPhoto,
    Zone,
)
from geogame.asgi import application as asgi_application
from organize.models import (
    Game,
    GameCollaborator,
    GameRole,
    Invite,
    PushSubscription,
    Session,
    Team,
    TeamGroup,
    TeamMembership,
    TeamRole,
)
from organize.push import BasePushSender

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
                initial_bonus=0, category=Tower.CATEGORY_NORMAL, rfid_code=None,
                proximity_meters=None):
    """Create a repository Tower attached to `game`'s default collection.

    `zone` (single, for fixture convenience) is linked through the
    many-to-many `zones` (tower-zone-topology); link further zones with
    `tower.zones.add(...)`.
    """
    tower = Tower.objects.create(
        name=name, location=Point(lng, lat), is_active=is_active,
        category=category, initial_bonus=initial_bonus, rfid_code=rfid_code,
        proximity_meters=proximity_meters,
    )
    if zone is not None:
        tower.zones.add(zone)
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
            name='T', location=Point(23.5, 46.5),
            is_active=True, category=Tower.CATEGORY_NORMAL,
        )
        tower.zones.add(zone)
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


# ---------------------------------------------------------------------------
# live-location — config knobs, consent gate, ping ingestion, visibility,
# retention (live-location-tracking change)
# ---------------------------------------------------------------------------


class LocationConfigResolutionTest(TestCase):
    """Task 7.1 — effective location knobs resolve override → default."""

    def setUp(self):
        self.game = _make_game()
        self.session = _default_session(self.game)

    def test_defaults_leave_tracking_off(self):
        self.assertFalse(self.session.effective('location_tracking_enabled'))
        self.assertEqual(self.session.effective('location_ping_interval_seconds'), 30)
        self.assertEqual(self.session.effective('location_visibility'), 'OWN_TEAM')
        self.assertEqual(self.session.effective('location_retention_days'), 30)
        self.assertEqual(self.session.effective('location_consent_text'), '')

    def test_session_override_wins(self):
        self.game.location_tracking_enabled = True
        self.game.location_ping_interval_seconds = 60
        self.game.save()
        self.session.location_ping_interval_seconds = 10
        self.session.location_visibility = 'EVERYONE'
        self.session.save()
        self.assertTrue(self.session.effective('location_tracking_enabled'))
        self.assertEqual(self.session.effective('location_ping_interval_seconds'), 10)
        self.assertEqual(self.session.effective('location_visibility'), 'EVERYONE')
        # Un-overridden fields keep resolving to the Game default.
        self.assertEqual(self.session.effective('location_retention_days'), 30)

    def test_ping_rejected_when_tracking_disabled(self):
        group = _make_group(self.game)
        team = _make_team(self.game, group)
        client, _user = _authed_client(team, username='loc-off')
        response = client.post(
            reverse('api-location-ping'),
            {'lat': 46.5, 'lng': 23.5},
            format='json',
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(LocationPing.objects.count(), 0)


class LocationConsentGateTest(TestCase):
    """Tasks 7.2/3.3 — consent gates pings and play; withdrawal purges."""

    def setUp(self):
        self.game = _make_game()
        self.game.location_tracking_enabled = True
        self.game.location_consent_text = 'We track you during the game.'
        self.game.save()
        self.session = _default_session(self.game)
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.tower = _make_tower(self.game, name='LT', lng=23.5, lat=46.5)
        self.challenge = Challenge.objects.create(
            game=self.game, text='Sing', tower=self.tower, difficulty=1,
        )
        self.client_api, self.user = _authed_client(self.team, username='loc-player')

    def _ping(self):
        return self.client_api.post(
            reverse('api-location-ping'),
            {'lat': 46.5, 'lng': 23.5, 'accuracy': 8.5},
            format='json',
        )

    def _submit(self):
        return self.client_api.post(
            '/api/team_tower_challenges/',
            {
                'tower': self.tower.id,
                'challenge': self.challenge.id,
                'lat': 46.5,
                'lng': 23.5,
            },
            format='json',
        )

    def test_consent_status_reports_effective_text(self):
        response = self.client_api.get(reverse('api-location-consent'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data['tracking_enabled'])
        self.assertFalse(response.data['has_consent'])
        self.assertEqual(
            response.data['consent_text'], 'We track you during the game.',
        )
        self.assertEqual(response.data['ping_interval_seconds'], 30)

    def test_ping_and_play_blocked_without_consent(self):
        self.assertEqual(self._ping().status_code, 403)
        response = self._submit()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(TeamTowerChallenge.objects.count(), 0)

    def test_recording_consent_unblocks_and_snapshots_text(self):
        response = self.client_api.post(reverse('api-location-consent'), {}, format='json')
        self.assertEqual(response.status_code, 201)
        consent = LocationConsent.objects.get(user=self.user, session=self.session)
        self.assertTrue(consent.is_standing)
        self.assertEqual(consent.consent_text, 'We track you during the game.')
        self.assertEqual(len(consent.consent_text_hash), 64)

        self.assertEqual(self._ping().status_code, 201)
        submit = self._submit()
        self.assertEqual(submit.status_code, 201)

    def test_withdrawal_reblocks_and_purges_session_pings(self):
        self.client_api.post(reverse('api-location-consent'), {}, format='json')
        self._ping()
        self.assertEqual(
            LocationPing.objects.filter(user=self.user, session=self.session).count(), 1,
        )
        response = self.client_api.delete(reverse('api-location-consent'))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            LocationPing.objects.filter(user=self.user, session=self.session).count(), 0,
        )
        consent = LocationConsent.objects.get(user=self.user, session=self.session)
        self.assertFalse(consent.is_standing)
        self.assertEqual(self._ping().status_code, 403)
        self.assertEqual(self._submit().status_code, 403)

    def test_regranting_after_withdrawal_reuses_the_row(self):
        self.client_api.post(reverse('api-location-consent'), {}, format='json')
        self.client_api.delete(reverse('api-location-consent'))
        response = self.client_api.post(reverse('api-location-consent'), {}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(LocationConsent.objects.count(), 1)
        self.assertTrue(
            LocationConsent.objects.get(user=self.user, session=self.session).is_standing,
        )

    def test_consent_post_rejected_when_tracking_disabled(self):
        self.game.location_tracking_enabled = False
        self.game.save()
        response = self.client_api.post(reverse('api-location-consent'), {}, format='json')
        self.assertEqual(response.status_code, 409)

    def test_tracking_off_requires_no_consent_to_play(self):
        self.game.location_tracking_enabled = False
        self.game.save()
        response = self._submit()
        self.assertEqual(response.status_code, 201)


class LocationPingIngestionTest(TestCase):
    """Task 7.3 — stored pings denormalize team and carry both clocks."""

    def setUp(self):
        self.game = _make_game()
        self.game.location_tracking_enabled = True
        self.game.save()
        self.session = _default_session(self.game)
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.client_api, self.user = _authed_client(self.team, username='pinger')
        self.client_api.post(reverse('api-location-consent'), {}, format='json')

    def test_ping_stored_with_denormalized_team_and_timestamps(self):
        recorded = (timezone.now() - timedelta(seconds=5)).isoformat()
        response = self.client_api.post(
            reverse('api-location-ping'),
            {'lat': 46.51, 'lng': 23.52, 'accuracy': 12.0, 'recorded_at': recorded},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        ping = LocationPing.objects.get()
        self.assertEqual(ping.user, self.user)
        self.assertEqual(ping.session, self.session)
        self.assertEqual(ping.team, self.team)
        self.assertAlmostEqual(ping.point.y, 46.51)
        self.assertAlmostEqual(ping.point.x, 23.52)
        self.assertEqual(ping.accuracy, 12.0)
        self.assertIsNotNone(ping.recorded_at)
        self.assertIsNotNone(ping.received_at)
        self.assertLess(ping.recorded_at, ping.received_at)
        # The response tells the app its (game-level) pacing interval.
        self.assertEqual(response.data['ping_interval_seconds'], 30)

    def test_ping_requires_coordinates(self):
        response = self.client_api.post(
            reverse('api-location-ping'), {'lat': 46.5}, format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_ping_rejected_when_session_override_disables_tracking(self):
        self.session.location_tracking_enabled = False
        self.session.save()
        response = self.client_api.post(
            reverse('api-location-ping'), {'lat': 46.5, 'lng': 23.5}, format='json',
        )
        self.assertEqual(response.status_code, 409)


class LocationLiveVisibilityTest(TestCase):
    """Task 7.4 — the live feed honors the effective location_visibility."""

    def setUp(self):
        self.game = _make_game()
        self.game.location_tracking_enabled = True
        self.game.save()
        self.session = _default_session(self.game)
        self.group = _make_group(self.game)
        self.team_a = _make_team(self.game, self.group, name='A', color='#111111')
        self.team_b = _make_team(self.game, self.group, name='B', color='#222222')
        self.client_a, self.user_a = _authed_client(self.team_a, username='alice')
        self.client_b, self.user_b = _authed_client(self.team_b, username='bob')
        for client in (self.client_a, self.client_b):
            client.post(reverse('api-location-consent'), {}, format='json')
            client.post(
                reverse('api-location-ping'),
                {'lat': 46.5, 'lng': 23.5},
                format='json',
            )

    def _live_usernames(self, client):
        response = client.get(reverse('api-location-live'))
        self.assertEqual(response.status_code, 200)
        return {p['username'] for p in response.data['players']}

    def test_own_team_default_limits_to_callers_team(self):
        self.assertEqual(self._live_usernames(self.client_a), {'alice'})
        self.assertEqual(self._live_usernames(self.client_b), {'bob'})

    def test_everyone_broadens_to_all_consenting_players(self):
        self.session.location_visibility = 'EVERYONE'
        self.session.save()
        self.assertEqual(self._live_usernames(self.client_a), {'alice', 'bob'})

    def test_none_hides_from_players_but_not_staff(self):
        self.session.location_visibility = 'NONE'
        self.session.save()
        self.assertEqual(self._live_usernames(self.client_a), set())
        staff_client, _staff = _staff_client(session=self.session)
        self.assertEqual(self._live_usernames(staff_client), {'alice', 'bob'})

    def test_latest_ping_per_user_only(self):
        self.client_a.post(
            reverse('api-location-ping'),
            {'lat': 46.6, 'lng': 23.6},
            format='json',
        )
        response = self.client_a.get(reverse('api-location-live'))
        players = [p for p in response.data['players'] if p['username'] == 'alice']
        self.assertEqual(len(players), 1)
        self.assertAlmostEqual(players[0]['lat'], 46.6)

    def test_withdrawn_player_never_revealed(self):
        self.session.location_visibility = 'EVERYONE'
        self.session.save()
        self.client_b.delete(reverse('api-location-consent'))
        self.assertEqual(self._live_usernames(self.client_a), {'alice'})
        staff_client, _staff = _staff_client(session=self.session)
        self.assertEqual(self._live_usernames(staff_client), {'alice'})

    def test_live_feed_reports_tracking_disabled(self):
        self.session.location_tracking_enabled = False
        self.session.save()
        response = self.client_a.get(reverse('api-location-live'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data['tracking_enabled'])
        self.assertEqual(response.data['players'], [])

    def test_staff_history_series_with_filters(self):
        staff_client, _staff = _staff_client(session=self.session)
        url = reverse('api-staff-location-history', args=[self.session.id])
        response = staff_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['pings']), 2)
        response = staff_client.get(f'{url}?user={self.user_a.id}')
        self.assertEqual(
            {p['username'] for p in response.data['pings']}, {'alice'},
        )
        response = staff_client.get(f'{url}?team={self.team_b.id}')
        self.assertEqual(
            {p['username'] for p in response.data['pings']}, {'bob'},
        )

    def test_history_is_staff_only(self):
        url = reverse('api-staff-location-history', args=[self.session.id])
        self.assertEqual(self.client_a.get(url).status_code, 403)


class LocationRetentionTest(TestCase):
    """Task 7.5 — purge honors retention and consent withdrawal."""

    def setUp(self):
        self.game = _make_game()
        self.game.location_tracking_enabled = True
        self.game.location_retention_days = 7
        self.game.save()
        self.session = _default_session(self.game)
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.client_api, self.user = _authed_client(self.team, username='retained')
        self.client_api.post(reverse('api-location-consent'), {}, format='json')

    def _make_ping(self, user, age_days):
        return LocationPing.objects.create(
            user=user,
            session=self.session,
            team=self.team,
            point=Point(23.5, 46.5),
            recorded_at=timezone.now() - timedelta(days=age_days),
        )

    def _run_purge(self):
        from django.core.management import call_command
        call_command('purge_location_pings', verbosity=0)

    def test_purge_deletes_expired_keeps_in_window(self):
        old = self._make_ping(self.user, age_days=10)
        fresh = self._make_ping(self.user, age_days=1)
        self._run_purge()
        remaining = list(LocationPing.objects.all())
        self.assertEqual([p.pk for p in remaining], [fresh.pk])
        self.assertFalse(LocationPing.objects.filter(pk=old.pk).exists())

    def test_purge_respects_session_retention_override(self):
        self.session.location_retention_days = 15
        self.session.save()
        keeper = self._make_ping(self.user, age_days=10)
        self._run_purge()
        self.assertTrue(LocationPing.objects.filter(pk=keeper.pk).exists())

    def test_purge_deletes_unconsented_pings(self):
        other = User.objects.create_user(
            username='ghost', email='ghost@example.com', password='password123',
        )
        self._make_ping(other, age_days=1)  # no standing consent row
        mine = self._make_ping(self.user, age_days=1)
        self._run_purge()
        self.assertEqual(
            list(LocationPing.objects.values_list('pk', flat=True)), [mine.pk],
        )

    def test_finished_session_keeps_in_window_history(self):
        fresh = self._make_ping(self.user, age_days=1)
        Session.objects.filter(pk=self.session.pk).update(state=Session.FINISHED)
        self._run_purge()
        self.assertTrue(LocationPing.objects.filter(pk=fresh.pk).exists())


# ---------------------------------------------------------------------------
# presence-rules — togetherness/visibility knobs, PresenceRequirement,
# geofence + window verification, photo fallback, PresenceCheck evidence
# ---------------------------------------------------------------------------


class PresenceConfigResolutionTest(TestCase):
    """Task 8.1 — the four presence knobs resolve override → default."""

    def setUp(self):
        self.game = _make_game()
        self.session = _default_session(self.game)

    def test_defaults_preserve_base_behavior(self):
        self.assertEqual(self.session.effective('togetherness_mode'), 'SPLIT_ALLOWED')
        self.assertEqual(self.session.effective('teammate_visibility_mode'), 'OWN_TEAM')
        self.assertEqual(self.session.effective('teammate_visibility_count'), 0)
        self.assertEqual(self.session.effective('presence_window_seconds'), 0)

    def test_session_override_wins(self):
        self.game.togetherness_mode = 'WHOLE_TEAM_TOGETHER'
        self.game.teammate_visibility_count = 3
        self.game.save()
        self.session.togetherness_mode = 'SPLIT_ALLOWED'
        self.session.teammate_visibility_mode = 'SELECT_COUNT'
        self.session.presence_window_seconds = 45
        self.session.save()
        self.assertEqual(self.session.effective('togetherness_mode'), 'SPLIT_ALLOWED')
        self.assertEqual(
            self.session.effective('teammate_visibility_mode'), 'SELECT_COUNT',
        )
        # Un-overridden fields keep resolving to the Game default.
        self.assertEqual(self.session.effective('teammate_visibility_count'), 3)
        self.assertEqual(self.session.effective('presence_window_seconds'), 45)


class ResolvePresenceTest(TestCase):
    """Task 8.2 — effective requirement resolution (pure config function)."""

    def setUp(self):
        self.game = _make_game()
        self.session = _default_session(self.game)
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.tower = _make_tower(self.game, name='PT')
        self.challenge = Challenge.objects.create(
            game=self.game, text='Together', tower=self.tower, difficulty=1,
        )
        for name in ('pr-a', 'pr-b', 'pr-c'):
            _add_member(self.team, name)

    def test_null_requirement_resolves_to_noop_default(self):
        from game.presence import resolve_presence
        resolved = resolve_presence(self.session, self.challenge, self.tower, team=self.team)
        self.assertTrue(resolved['is_noop'])
        self.assertEqual(resolved['min_members'], 1)
        self.assertEqual(resolved['method'], 'GEOFENCE')
        self.assertEqual(resolved['geofence_radius_meters'], self.game.proximity_meters)
        self.assertEqual(resolved['window_seconds'], 0)

    def test_split_allowed_uses_challenge_minimum(self):
        from game.presence import resolve_presence
        req = PresenceRequirement.objects.create(name='Pair', min_members_present=2)
        self.challenge.presence_requirement = req
        self.challenge.save()
        resolved = resolve_presence(self.session, self.challenge, self.tower, team=self.team)
        self.assertFalse(resolved['is_noop'])
        self.assertEqual(resolved['min_members'], 2)

    def test_whole_team_raises_min_to_active_team_size(self):
        from game.presence import resolve_presence
        req = PresenceRequirement.objects.create(name='Pair', min_members_present=2)
        self.challenge.presence_requirement = req
        self.challenge.save()
        self.session.togetherness_mode = 'WHOLE_TEAM_TOGETHER'
        self.session.save()
        resolved = resolve_presence(self.session, self.challenge, self.tower, team=self.team)
        self.assertEqual(resolved['min_members'], 3)
        self.assertFalse(resolved['is_noop'])

    def test_radius_and_window_fallbacks(self):
        from game.presence import resolve_presence
        self.session.presence_window_seconds = 30
        self.session.save()
        req = PresenceRequirement.objects.create(name='Loose', min_members_present=2)
        self.challenge.presence_requirement = req
        self.challenge.save()
        resolved = resolve_presence(self.session, self.challenge, self.tower, team=self.team)
        self.assertEqual(resolved['geofence_radius_meters'], self.game.proximity_meters)
        self.assertEqual(resolved['window_seconds'], 30)

        req.geofence_radius_meters = 120
        req.window_seconds = 90
        req.save()
        self.challenge.refresh_from_db()
        resolved = resolve_presence(self.session, self.challenge, self.tower, team=self.team)
        self.assertEqual(resolved['geofence_radius_meters'], 120)
        self.assertEqual(resolved['window_seconds'], 90)


class _PresenceSubmissionBase(TestCase):
    """Shared fixture: location-enabled game, a team of three, a tower."""

    TOWER_LNG, TOWER_LAT = 23.5, 46.5
    INSIDE = (23.5, 46.5001)     # ~11 m from the tower
    OUTSIDE = (23.5, 46.502)     # ~220 m from the tower

    def setUp(self):
        self.game = _make_game()
        self.game.location_tracking_enabled = True
        self.game.save()
        self.session = _default_session(self.game)
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.zone = _make_zone(self.game, name='PZ')
        self.tower = _make_tower(
            self.game, name='PT', zone=self.zone,
            lng=self.TOWER_LNG, lat=self.TOWER_LAT,
        )
        self.challenge = Challenge.objects.create(
            game=self.game, text='Together', tower=self.tower, difficulty=1,
        )
        self.client_api, self.submitter = _authed_client(self.team, username='p-sub')
        self.client_api.post(reverse('api-location-consent'), {}, format='json')
        self.mate_a = _add_member(self.team, 'p-mate-a').user.user
        self.mate_b = _add_member(self.team, 'p-mate-b').user.user

    def _ping_at(self, user, lnglat, age_seconds=5):
        lng, lat = lnglat
        return LocationPing.objects.create(
            user=user,
            session=self.session,
            team=self.team,
            point=Point(lng, lat),
            recorded_at=timezone.now() - timedelta(seconds=age_seconds),
        )

    def _submit(self, photo=False, rfid_code=None):
        payload = {
            'challenge': self.challenge.id,
            'lat': self.INSIDE[1],
            'lng': self.INSIDE[0],
        }
        if rfid_code:
            payload['rfid_code'] = rfid_code
        else:
            payload['tower'] = self.tower.id
        if photo:
            payload['photo'] = _tiny_png_b64()
        return self.client_api.post('/api/team_tower_challenges/', payload, format='json')

    def _attach_requirement(self, **kwargs):
        kwargs.setdefault('name', 'Pair')
        kwargs.setdefault('min_members_present', 2)
        req = PresenceRequirement.objects.create(**kwargs)
        self.challenge.presence_requirement = req
        self.challenge.save()
        return req


class GeofencePresenceTest(_PresenceSubmissionBase):
    """Task 8.3 — point-in-time geofence co-presence counting."""

    def test_two_members_inside_pass(self):
        self._attach_requirement()
        self._ping_at(self.mate_a, self.INSIDE)
        response = self._submit()
        self.assertEqual(response.status_code, 201)
        ttc = TeamTowerChallenge.objects.get()
        check = ttc.presence_check
        self.assertTrue(check.satisfied)
        self.assertEqual(check.required_count, 2)
        self.assertEqual(check.present_count, 2)
        self.assertEqual(
            set(check.verified_member_ids), {self.submitter.id, self.mate_a.id},
        )

    def test_only_submitter_rejected_insufficient(self):
        self._attach_requirement()
        response = self._submit()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['presence']['reason_code'], 'INSUFFICIENT_MEMBERS_PRESENT',
        )
        self.assertEqual(TeamTowerChallenge.objects.count(), 0)

    def test_member_outside_geofence_reason(self):
        self._attach_requirement()
        self._ping_at(self.mate_a, self.OUTSIDE)
        response = self._submit()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['presence']['reason_code'], 'MEMBER_OUTSIDE_GEOFENCE',
        )

    def test_stale_ping_does_not_count(self):
        self._attach_requirement()
        self._ping_at(self.mate_a, self.INSIDE, age_seconds=600)
        response = self._submit()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['presence']['reason_code'], 'INSUFFICIENT_MEMBERS_PRESENT',
        )

    def test_whole_team_together_requires_everyone(self):
        # No PresenceRequirement at all — togetherness alone gates.
        self.session.togetherness_mode = 'WHOLE_TEAM_TOGETHER'
        self.session.save()
        self._ping_at(self.mate_a, self.INSIDE)
        response = self._submit()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['presence']['reason_code'], 'INSUFFICIENT_MEMBERS_PRESENT',
        )
        self._ping_at(self.mate_b, self.INSIDE)
        self.assertEqual(self._submit().status_code, 201)


class PresenceWindowTest(_PresenceSubmissionBase):
    """Task 8.4 — continuous-tracking window (trajectory/duration)."""

    def setUp(self):
        super().setUp()
        self._attach_requirement(window_seconds=60)

    def test_member_inside_for_whole_window_passes(self):
        self._ping_at(self.mate_a, self.INSIDE, age_seconds=70)  # boundary
        self._ping_at(self.mate_a, self.INSIDE, age_seconds=30)
        self._ping_at(self.mate_a, self.INSIDE, age_seconds=5)
        response = self._submit()
        self.assertEqual(response.status_code, 201)
        check = TeamTowerChallenge.objects.get().presence_check
        self.assertTrue(check.satisfied)
        self.assertTrue(check.window_satisfied)
        self.assertEqual(check.window_seconds, 60)

    def test_member_inside_only_at_last_instant_fails_window(self):
        self._ping_at(self.mate_a, self.OUTSIDE, age_seconds=40)
        self._ping_at(self.mate_a, self.INSIDE, age_seconds=5)
        response = self._submit()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['presence']['reason_code'], 'PRESENCE_WINDOW_NOT_SATISFIED',
        )

    def test_jitter_within_geofence_still_passes(self):
        self._ping_at(self.mate_a, (23.5, 46.50005), age_seconds=50)
        self._ping_at(self.mate_a, (23.50008, 46.5001), age_seconds=25)
        self._ping_at(self.mate_a, (23.5, 46.5002), age_seconds=5)
        self.assertEqual(self._submit().status_code, 201)


class PhotoFallbackTest(_PresenceSubmissionBase):
    """Task 8.5 — photo evidence routes to PENDING review, never auto-confirms."""

    def test_photo_method_requires_photo(self):
        self._attach_requirement(method='PHOTO')
        response = self._submit(photo=False)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['presence']['reason_code'], 'PHOTO_REVIEW_REQUIRED',
        )

    def test_photo_method_holds_for_review(self):
        self._attach_requirement(method='PHOTO')
        response = self._submit(photo=True)
        self.assertEqual(response.status_code, 201)
        ttc = TeamTowerChallenge.objects.get()
        self.assertEqual(ttc.outcome, TeamTowerChallenge.PENDING)
        check = ttc.presence_check
        self.assertEqual(check.method, 'PHOTO')
        self.assertEqual(check.reason_code, 'PHOTO_REVIEW_REQUIRED')

    def test_geofence_or_photo_falls_back_when_geofence_insufficient(self):
        self._attach_requirement(method='GEOFENCE_OR_PHOTO')
        response = self._submit(photo=True)  # no teammate pings at all
        self.assertEqual(response.status_code, 201)
        ttc = TeamTowerChallenge.objects.get()
        self.assertEqual(ttc.outcome, TeamTowerChallenge.PENDING)
        self.assertEqual(ttc.presence_check.method, 'PHOTO')

    def test_geofence_or_photo_without_photo_rejects_with_geofence_reason(self):
        self._attach_requirement(method='GEOFENCE_OR_PHOTO')
        response = self._submit(photo=False)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.data['presence']['reason_code'], 'INSUFFICIENT_MEMBERS_PRESENT',
        )

    def test_photo_fallback_suppresses_rfid_auto_confirm(self):
        self.tower.category = Tower.CATEGORY_RFID
        self.tower.rfid_code = 'PRESENCE1'
        self.tower.save()
        self._attach_requirement(method='PHOTO')
        response = self._submit(photo=True, rfid_code='PRESENCE1')
        self.assertEqual(response.status_code, 201)
        ttc = TeamTowerChallenge.objects.get()
        self.assertEqual(ttc.outcome, TeamTowerChallenge.PENDING)


class PresenceBackwardCompatTest(_PresenceSubmissionBase):
    """Task 8.6 — a NULL-requirement challenge submits exactly as before."""

    def test_default_game_submission_unchanged(self):
        # Turn location tracking back off — a fully default game.
        self.game.location_tracking_enabled = False
        self.game.save()
        response = self._submit()
        self.assertEqual(response.status_code, 201)
        ttc = TeamTowerChallenge.objects.get()
        self.assertEqual(ttc.outcome, TeamTowerChallenge.PENDING)
        self.assertEqual(PresenceCheck.objects.count(), 0)

    def test_rfid_auto_confirm_still_confirms_without_requirement(self):
        self.game.location_tracking_enabled = False
        self.game.save()
        self.tower.category = Tower.CATEGORY_RFID
        self.tower.rfid_code = 'PRESENCE2'
        self.tower.save()
        response = self._submit(rfid_code='PRESENCE2')
        self.assertEqual(response.status_code, 201)
        ttc = TeamTowerChallenge.objects.get()
        self.assertEqual(ttc.outcome, TeamTowerChallenge.CONFIRMED)
        self.assertEqual(PresenceCheck.objects.count(), 0)


class PresenceDegradationTest(_PresenceSubmissionBase):
    """Task 8.7 — window configured but live-location unavailable."""

    def test_tracking_disabled_degrades_to_point_in_time(self):
        self.game.location_tracking_enabled = False
        self.game.save()
        self.session.presence_window_seconds = 30
        self.session.save()
        response = self._submit()
        self.assertEqual(response.status_code, 201)
        check = TeamTowerChallenge.objects.get().presence_check
        self.assertTrue(check.satisfied)
        self.assertIsNone(check.window_satisfied)  # not evaluated

    def test_no_ping_data_degrades_to_point_in_time(self):
        self.session.presence_window_seconds = 30
        self.session.save()
        response = self._submit()  # nobody has pinged yet
        self.assertEqual(response.status_code, 201)
        check = TeamTowerChallenge.objects.get().presence_check
        self.assertTrue(check.satisfied)
        self.assertIsNone(check.window_satisfied)


class PresenceEvidenceTest(_PresenceSubmissionBase):
    """Task 8.8 — PresenceCheck persists and reaches the staff review payload."""

    def test_staff_review_payload_exposes_presence_check(self):
        self._attach_requirement()
        self._ping_at(self.mate_a, self.INSIDE)
        self.assertEqual(self._submit().status_code, 201)
        staff_client, _staff = _staff_client(session=self.session)
        response = staff_client.get('/api/staff/submissions/')
        self.assertEqual(response.status_code, 200)
        payload = response.data[0]['presence_check']
        self.assertIsNotNone(payload)
        self.assertEqual(payload['required_count'], 2)
        self.assertEqual(payload['present_count'], 2)
        self.assertEqual(payload['method'], 'GEOFENCE')
        self.assertEqual(
            set(payload['verified_member_ids']),
            {self.submitter.id, self.mate_a.id},
        )

    def test_ungated_submission_has_no_presence_block(self):
        self.game.location_tracking_enabled = False
        self.game.save()
        self.assertEqual(self._submit().status_code, 201)
        staff_client, _staff = _staff_client(session=self.session)
        response = staff_client.get('/api/staff/submissions/')
        self.assertIsNone(response.data[0]['presence_check'])


class PresenceApiTest(_PresenceSubmissionBase):
    """Tasks 6.2/6.3 — staff CRUD + knobs, player presence status."""

    def test_staff_presence_requirement_crud(self):
        staff_client, _staff = _staff_client(session=self.session)
        response = staff_client.post(
            '/api/staff/presence-requirements/',
            {'name': 'Trio', 'min_members_present': 3, 'method': 'GEOFENCE_OR_PHOTO'},
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        req_id = response.data['id']
        response = staff_client.patch(
            f'/api/staff/presence-requirements/{req_id}/',
            {'window_seconds': 45},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['window_seconds'], 45)
        response = staff_client.get('/api/staff/presence-requirements/')
        self.assertEqual(len(response.data), 1)
        # Attach to the challenge through the challenge editor.
        response = staff_client.patch(
            f'/api/staff/challenges/{self.challenge.id}/',
            {'presence_requirement': req_id},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['presence_requirement'], req_id)
        # Deleting detaches (SET_NULL) without touching the challenge.
        response = staff_client.delete(f'/api/staff/presence-requirements/{req_id}/')
        self.assertEqual(response.status_code, 204)
        self.challenge.refresh_from_db()
        self.assertIsNone(self.challenge.presence_requirement)

    def test_requirement_validation_rejects_zero_minimum(self):
        staff_client, _staff = _staff_client(session=self.session)
        response = staff_client.post(
            '/api/staff/presence-requirements/',
            {'name': 'Nobody', 'min_members_present': 0},
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_staff_game_and_session_accept_presence_knobs(self):
        staff_client, _staff = _staff_client(session=self.session)
        response = staff_client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'togetherness_mode': 'WHOLE_TEAM_TOGETHER', 'presence_window_seconds': 20},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['togetherness_mode'], 'WHOLE_TEAM_TOGETHER')
        response = staff_client.patch(
            f'/api/staff/sessions/{self.session.id}/',
            {'teammate_visibility_mode': 'SELECT_COUNT', 'teammate_visibility_count': 2},
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.session.refresh_from_db()
        self.assertEqual(
            self.session.effective('teammate_visibility_mode'), 'SELECT_COUNT',
        )

    def test_tower_state_reports_presence_status(self):
        self._attach_requirement(method='GEOFENCE_OR_PHOTO')
        self._ping_at(self.mate_a, self.INSIDE)
        response = self.client_api.get(f'/api/towers/{self.tower.id}/state/')
        self.assertEqual(response.status_code, 200)
        presence = response.data['presence']
        self.assertIsNotNone(presence)
        self.assertEqual(presence['required_members'], 2)
        self.assertEqual(presence['present_members'], 1)
        self.assertTrue(presence['photo_fallback_offered'])

    def test_tower_state_presence_none_by_default(self):
        response = self.client_api.get(f'/api/towers/{self.tower.id}/state/')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data['presence'])


class TeammateVisibilitySelectCountTest(TestCase):
    """Task 6.1 — SELECT_COUNT narrows the live feed to the nearest N."""

    def setUp(self):
        self.game = _make_game()
        self.game.location_tracking_enabled = True
        self.game.location_visibility = 'EVERYONE'
        self.game.teammate_visibility_mode = 'SELECT_COUNT'
        self.game.teammate_visibility_count = 1
        self.game.save()
        self.session = _default_session(self.game)
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        self.client_a, self.user_a = _authed_client(self.team, username='va')
        self.client_b, self.user_b = _authed_client(self.team, username='vb')
        self.client_c, self.user_c = _authed_client(self.team, username='vc')
        for client, lnglat in (
            (self.client_a, (23.5, 46.5)),
            (self.client_b, (23.5, 46.5002)),   # near A
            (self.client_c, (23.5, 46.52)),     # far from A
        ):
            client.post(reverse('api-location-consent'), {}, format='json')
            client.post(
                reverse('api-location-ping'),
                {'lat': lnglat[1], 'lng': lnglat[0]},
                format='json',
            )

    def test_nearest_n_plus_self(self):
        response = self.client_a.get(reverse('api-location-live'))
        self.assertEqual(response.status_code, 200)
        names = {p['username'] for p in response.data['players']}
        self.assertEqual(names, {'va', 'vb'})
        self.assertEqual(
            response.data['teammate_visibility'],
            {'mode': 'SELECT_COUNT', 'count': 1},
        )

    def test_staff_unaffected_by_select_count(self):
        staff_client, _staff = _staff_client(session=self.session)
        response = staff_client.get(reverse('api-location-live'))
        names = {p['username'] for p in response.data['players']}
        self.assertEqual(names, {'va', 'vb', 'vc'})

    def test_select_count_never_widens_own_team_gate(self):
        # location_visibility OWN_TEAM caps the feed even with a huge N.
        self.game.location_visibility = 'OWN_TEAM'
        self.game.teammate_visibility_count = 10
        self.game.save()
        other_group = _make_group(self.game, name='Other', slug='other')
        other_team = _make_team(self.game, other_group, name='others', color='#222222')
        client_d, _user_d = _authed_client(other_team, username='vd')
        client_d.post(reverse('api-location-consent'), {}, format='json')
        client_d.post(
            reverse('api-location-ping'), {'lat': 46.5, 'lng': 23.5}, format='json',
        )
        response = self.client_a.get(reverse('api-location-live'))
        names = {p['username'] for p in response.data['players']}
        self.assertEqual(names, {'va', 'vb', 'vc'})


# ---------------------------------------------------------------------------
# zone-conquest-and-scoring-config — effective-value helpers (task 6.1)
# ---------------------------------------------------------------------------


class EffectiveValueHelpersTest(TestCase):
    """Precedence of the three effective-value helpers.

    Conquest rule: Zone > Session > Game. Proximity: Tower > Game.
    Time unit: Session > Game. The all-defaults path reproduces the
    historical behavior (MAJORITY, game-wide radius, MINUTE).
    """

    def setUp(self):
        from game.models import (
            effective_conquest_rule,
            effective_proximity,
            effective_time_unit,
        )
        self.effective_conquest_rule = effective_conquest_rule
        self.effective_proximity = effective_proximity
        self.effective_time_unit = effective_time_unit
        self.game = _make_game()
        self.session = _default_session(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)

    def test_conquest_rule_all_defaults_is_majority(self):
        from organize.models import CONQUEST_RULE_MAJORITY
        self.assertEqual(
            self.effective_conquest_rule(self.zone, session=self.session),
            CONQUEST_RULE_MAJORITY,
        )

    def test_conquest_rule_game_default(self):
        from organize.models import CONQUEST_RULE_ALL
        self.game.zone_conquest_rule = CONQUEST_RULE_ALL
        self.game.save()
        self.session.refresh_from_db()
        self.assertEqual(
            self.effective_conquest_rule(self.zone, session=self.session),
            CONQUEST_RULE_ALL,
        )

    def test_conquest_rule_session_override_beats_game(self):
        from organize.models import CONQUEST_RULE_ALL, CONQUEST_RULE_ANY
        self.game.zone_conquest_rule = CONQUEST_RULE_ALL
        self.game.save()
        Session.objects.filter(pk=self.session.pk).update(
            zone_conquest_rule=CONQUEST_RULE_ANY,
        )
        self.session.refresh_from_db()
        self.assertEqual(
            self.effective_conquest_rule(self.zone, session=self.session),
            CONQUEST_RULE_ANY,
        )

    def test_conquest_rule_zone_override_wins(self):
        from organize.models import CONQUEST_RULE_ALL, CONQUEST_RULE_ANY
        Session.objects.filter(pk=self.session.pk).update(
            zone_conquest_rule=CONQUEST_RULE_ANY,
        )
        self.session.refresh_from_db()
        self.zone.conquest_rule = CONQUEST_RULE_ALL
        self.zone.save()
        self.assertEqual(
            self.effective_conquest_rule(self.zone, session=self.session),
            CONQUEST_RULE_ALL,
        )

    def test_conquest_rule_without_session_uses_game(self):
        from organize.models import CONQUEST_RULE_ALL, CONQUEST_RULE_MAJORITY
        self.assertEqual(
            self.effective_conquest_rule(self.zone, session=None, game=self.game),
            CONQUEST_RULE_MAJORITY,
        )
        self.game.zone_conquest_rule = CONQUEST_RULE_ALL
        self.game.save()
        self.assertEqual(
            self.effective_conquest_rule(self.zone, session=None, game=self.game),
            CONQUEST_RULE_ALL,
        )

    def test_proximity_game_default(self):
        self.assertEqual(
            self.effective_proximity(self.tower, self.game),
            self.game.proximity_meters,
        )

    def test_proximity_tower_override_wins(self):
        self.tower.proximity_meters = 500
        self.tower.save()
        self.assertEqual(self.effective_proximity(self.tower, self.game), 500)

    def test_time_unit_game_default(self):
        from organize.models import TIME_UNIT_MINUTE
        self.assertEqual(
            self.effective_time_unit(self.session), TIME_UNIT_MINUTE,
        )

    def test_time_unit_session_override(self):
        from organize.models import TIME_UNIT_SECOND
        Session.objects.filter(pk=self.session.pk).update(
            score_time_unit=TIME_UNIT_SECOND,
        )
        self.session.refresh_from_db()
        self.assertEqual(
            self.effective_time_unit(self.session), TIME_UNIT_SECOND,
        )


# ---------------------------------------------------------------------------
# zone-conquest-and-scoring-config — conquest rules (task 6.2)
# ---------------------------------------------------------------------------


class ConquestRuleTest(TestCase):
    """ALL / MAJORITY / ANY control computation over a zone's members."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game, scoring=Zone.SCORE_LIN)
        self.t1 = _make_team(self.game, self.group, name='t1')
        self.t2 = _make_team(self.game, self.group, name='t2')

    def _towers(self, n):
        return [
            _make_tower(self.game, zone=self.zone, name=f'tw{i}', lng=23.5 + i / 100)
            for i in range(n)
        ]

    def _controller_ids(self):
        return set(self.zone.zone_control(self.group))

    def test_all_rule_requires_every_active_tower(self):
        from organize.models import CONQUEST_RULE_ALL
        self.zone.conquest_rule = CONQUEST_RULE_ALL
        self.zone.save()
        t_a, t_b = self._towers(2)

        t_a.assign_to_team(self.t1)
        self.assertEqual(self._controller_ids(), set())

        t_b.assign_to_team(self.t1)
        self.assertEqual(self._controller_ids(), {self.t1.pk})

    def test_all_rule_control_lost_when_a_tower_is_taken(self):
        from organize.models import CONQUEST_RULE_ALL
        self.zone.conquest_rule = CONQUEST_RULE_ALL
        self.zone.save()
        t_a, t_b = self._towers(2)
        t_a.assign_to_team(self.t1)
        t_b.assign_to_team(self.t1)
        self.assertEqual(self._controller_ids(), {self.t1.pk})

        # t2 takes one tower: nobody holds ALL of them any more.
        t_b.assign_to_team(self.t2)
        self.assertEqual(self._controller_ids(), set())
        closed = TeamZoneOwnership.objects.get(zone=self.zone, team=self.t1)
        self.assertIsNotNone(closed.timestamp_end)

    def test_majority_rule_matches_prechange_behavior(self):
        # Default rule (no overrides anywhere) — the historical
        # most-towers computation, retained verbatim.
        towers = self._towers(3)
        towers[0].assign_to_team(self.t1)
        towers[1].assign_to_team(self.t1)
        towers[2].assign_to_team(self.t2)
        self.assertEqual(self._controller_ids(), {self.t1.pk})

    def test_any_rule_grants_on_single_tower(self):
        from organize.models import CONQUEST_RULE_ANY
        self.zone.conquest_rule = CONQUEST_RULE_ANY
        self.zone.save()
        t_a, _ = self._towers(2)
        t_a.assign_to_team(self.t1)
        self.assertEqual(self._controller_ids(), {self.t1.pk})

    def test_any_rule_most_towers_wins(self):
        from organize.models import CONQUEST_RULE_ANY
        self.zone.conquest_rule = CONQUEST_RULE_ANY
        self.zone.save()
        t_a, t_b, t_c = self._towers(3)
        t_a.assign_to_team(self.t1)
        t_b.assign_to_team(self.t2)
        t_c.assign_to_team(self.t2)
        self.assertEqual(self._controller_ids(), {self.t2.pk})

    def test_any_rule_tie_breaks_by_most_recent_capture(self):
        from organize.models import CONQUEST_RULE_ANY
        self.zone.conquest_rule = CONQUEST_RULE_ANY
        self.zone.save()
        t_a, t_b = self._towers(2)
        t_a.assign_to_team(self.t1)
        t_b.assign_to_team(self.t2)
        # 1 tower each — the more recent capture (t2's) wins the zone.
        self.assertEqual(self._controller_ids(), {self.t2.pk})
        closed = TeamZoneOwnership.objects.get(zone=self.zone, team=self.t1)
        self.assertIsNotNone(closed.timestamp_end)

    def test_session_override_applies_when_zone_unset(self):
        from organize.models import CONQUEST_RULE_ALL
        session = _default_session(self.game)
        Session.objects.filter(pk=session.pk).update(
            zone_conquest_rule=CONQUEST_RULE_ALL,
        )
        # Re-fetch: the setUp team instance caches its (stale) session.
        self.t1 = Team.objects.get(pk=self.t1.pk)
        t_a, _ = self._towers(2)
        t_a.assign_to_team(self.t1)
        # 1 of 2 towers: MAJORITY would grant, ALL does not.
        self.assertEqual(self._controller_ids(), set())


# ---------------------------------------------------------------------------
# zone-conquest-and-scoring-config — scoring time unit (task 6.3)
# ---------------------------------------------------------------------------


class ScoreTimeUnitTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game, scoring=Zone.SCORE_LIN)
        self.team = _make_team(self.game, self.group)

    def test_minute_default_reproduces_historical_scores(self):
        from organize.models import TIME_UNIT_MINUTE
        # 600 seconds → 10 minutes → LINEAR gives 10 points, exactly as
        # before the change (regression).
        self.assertAlmostEqual(self.zone.get_score(600), 10.0)
        self.assertAlmostEqual(
            self.zone.get_score(600, time_unit=TIME_UNIT_MINUTE), 10.0,
        )

    def test_second_unit_scales_duration(self):
        from organize.models import TIME_UNIT_SECOND
        self.assertAlmostEqual(
            self.zone.get_score(600, time_unit=TIME_UNIT_SECOND), 600.0,
        )

    def test_hour_unit_scales_duration(self):
        from organize.models import TIME_UNIT_HOUR
        self.assertAlmostEqual(
            self.zone.get_score(7200, time_unit=TIME_UNIT_HOUR), 2.0,
        )

    def test_nonlinear_formulas_use_converted_units(self):
        from organize.models import TIME_UNIT_HOUR
        self.zone.scoring_type = Zone.SCORE_EXP
        # 2 hours → units=2 → 2^2/140 + 10.
        self.assertAlmostEqual(
            self.zone.get_score(7200, time_unit=TIME_UNIT_HOUR),
            2 ** 2 / 140 + 10,
        )

    def _backdated_ownership(self, seconds):
        ownership = TeamZoneOwnership.objects.create(zone=self.zone, team=self.team)
        TeamZoneOwnership.objects.filter(pk=ownership.pk).update(
            timestamp_start=timezone.now() - timedelta(seconds=seconds),
        )
        ownership.refresh_from_db()
        return ownership

    def test_ownership_score_defaults_to_minutes(self):
        ownership = self._backdated_ownership(600)
        self.assertAlmostEqual(ownership.get_score(), 10.0, places=1)

    def test_ownership_score_honors_session_override(self):
        from organize.models import TIME_UNIT_SECOND
        Session.objects.filter(pk=self.team.session_id).update(
            score_time_unit=TIME_UNIT_SECOND,
        )
        ownership = self._backdated_ownership(600)
        self.assertAlmostEqual(ownership.get_score(), 600.0, delta=2.0)


# ---------------------------------------------------------------------------
# zone-conquest-and-scoring-config — per-tower proximity (task 6.4)
# ---------------------------------------------------------------------------


class ProximityOverrideTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        # Two towers at the same point: one inherits the game-wide 50m
        # default, the other overrides its radius to 5km.
        self.tower_default = _make_tower(
            self.game, zone=self.zone, name='default', lng=23.5, lat=46.5,
        )
        self.tower_wide = _make_tower(
            self.game, zone=self.zone, name='wide', lng=23.5, lat=46.5,
            proximity_meters=5000,
        )
        self.team = _make_team(self.game, self.group)
        self.challenge_default = Challenge.objects.create(
            text='c1', tower=self.tower_default, difficulty=1,
        )
        self.challenge_wide = Challenge.objects.create(
            text='c2', tower=self.tower_wide, difficulty=1,
        )
        self.client, self.user = _authed_client(self.team)
        # ~1km north of both towers.
        self.far_lat = 46.5 + 1000 / 111_111.0

    def test_submission_accepted_within_tower_override_radius(self):
        resp = self.client.post(
            '/api/team_tower_challenges/',
            {
                'tower': self.tower_wide.pk,
                'challenge': self.challenge_wide.pk,
                'lat': self.far_lat,
                'lng': 23.5,
                'photo': _tiny_png_b64(),
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_sibling_tower_still_uses_game_default(self):
        resp = self.client.post(
            '/api/team_tower_challenges/',
            {
                'tower': self.tower_default.pk,
                'challenge': self.challenge_default.pk,
                'lat': self.far_lat,
                'lng': 23.5,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_towers_endpoint_uses_per_tower_radius(self):
        resp = self.client.get(
            '/api/towers/',
            {'lat': self.far_lat, 'lng': 23.5, 'accuracy': 10000},
        )
        self.assertEqual(resp.status_code, 200)
        ids = [t['id'] for t in resp.json()]
        self.assertIn(self.tower_wide.id, ids)
        self.assertNotIn(self.tower_default.id, ids)

    def test_towers_endpoint_default_radius_unchanged(self):
        # Right at the towers, both are inside their effective radius.
        resp = self.client.get(
            '/api/towers/',
            {'lat': 46.5, 'lng': 23.5, 'accuracy': 50},
        )
        ids = [t['id'] for t in resp.json()]
        self.assertIn(self.tower_default.id, ids)
        self.assertIn(self.tower_wide.id, ids)

    def test_tower_state_reports_effective_proximity(self):
        resp = self.client.get(f'/api/towers/{self.tower_wide.pk}/state/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['proximity_meters'], 5000)
        resp = self.client.get(f'/api/towers/{self.tower_default.pk}/state/')
        self.assertEqual(
            resp.json()['proximity_meters'], self.game.proximity_meters,
        )


# ---------------------------------------------------------------------------
# zone-conquest-and-scoring-config — staff API knobs (tasks 4.1–4.3) and
# migration/defaults parity (task 6.5)
# ---------------------------------------------------------------------------


class ConquestConfigApiTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.session = _default_session(self.game)
        self.client, self.staff = _staff_client(session=self.session)

    def test_game_defaults_editable(self):
        resp = self.client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'zone_conquest_rule': 'ALL', 'score_time_unit': 'HOUR'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.game.refresh_from_db()
        self.assertEqual(self.game.zone_conquest_rule, 'ALL')
        self.assertEqual(self.game.score_time_unit, 'HOUR')

    def test_invalid_choice_rejected(self):
        resp = self.client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'zone_conquest_rule': 'SOMETIMES'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch(
            f'/api/staff/games/{self.game.id}/',
            {'score_time_unit': 'FORTNIGHT'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_session_overrides_nullable(self):
        resp = self.client.patch(
            f'/api/staff/sessions/{self.session.id}/',
            {'zone_conquest_rule': 'ANY', 'score_time_unit': 'SECOND'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.session.refresh_from_db()
        self.assertEqual(self.session.effective('zone_conquest_rule'), 'ANY')
        self.assertEqual(self.session.effective('score_time_unit'), 'SECOND')

        # Clearing back to null re-inherits the Game defaults.
        resp = self.client.patch(
            f'/api/staff/sessions/{self.session.id}/',
            {'zone_conquest_rule': None, 'score_time_unit': None},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.session.refresh_from_db()
        self.assertEqual(self.session.effective('zone_conquest_rule'), 'MAJORITY')
        self.assertEqual(self.session.effective('score_time_unit'), 'MINUTE')

    def test_zone_conquest_rule_editable(self):
        resp = self.client.patch(
            f'/api/staff/zones/{self.zone.id}/',
            {'conquest_rule': 'ALL'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.conquest_rule, 'ALL')

    def test_tower_proximity_editable(self):
        resp = self.client.patch(
            f'/api/staff/towers/{self.tower.id}/',
            {'proximity_meters': 120},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.tower.refresh_from_db()
        self.assertEqual(self.tower.proximity_meters, 120)


class DefaultsParityTest(TestCase):
    """Task 6.5 — an untouched Game/Session keeps the historical behavior.

    All new knobs default to values that reproduce pre-change results:
    MAJORITY control, game-wide proximity, minute-based accrual.
    """

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game, scoring=Zone.SCORE_LIN)
        self.session = _default_session(self.game)

    def test_field_defaults(self):
        self.assertEqual(self.game.zone_conquest_rule, 'MAJORITY')
        self.assertEqual(self.game.score_time_unit, 'MINUTE')
        self.assertIsNone(self.session.zone_conquest_rule)
        self.assertIsNone(self.session.score_time_unit)
        self.assertIsNone(self.zone.conquest_rule)
        tower = _make_tower(self.game, zone=self.zone)
        self.assertIsNone(tower.proximity_meters)

    def test_control_and_scores_identical_to_prechange(self):
        t1 = _make_team(self.game, self.group, name='a')
        t2 = _make_team(self.game, self.group, name='b')
        towers = [
            _make_tower(self.game, zone=self.zone, name=f'p{i}', lng=23.5 + i / 100)
            for i in range(3)
        ]
        towers[0].assign_to_team(t1)
        towers[1].assign_to_team(t1)
        towers[2].assign_to_team(t2)
        # Pre-change majority outcome.
        self.assertEqual(set(self.zone.zone_control(self.group)), {t1.pk})
        # Pre-change minute-based floating score.
        ownership = TeamZoneOwnership.objects.get(
            zone=self.zone, team=t1, timestamp_end__isnull=True,
        )
        TeamZoneOwnership.objects.filter(pk=ownership.pk).update(
            timestamp_start=timezone.now() - timedelta(minutes=10),
        )
        ownership.refresh_from_db()
        self.assertAlmostEqual(ownership.get_score(), 10.0, places=1)


# ---------------------------------------------------------------------------
# tower-zone-topology — many-to-many membership (tasks 7.1–7.5)
# ---------------------------------------------------------------------------


class TowerZonesDataMigrationTest(TransactionTestCase):
    """Task 7.1 — the data migration copies each single-FK link into the
    many-to-many and keeps (reports, never deletes) empty zones."""

    migrate_from = [('game', '0027_tower_zones_m2m')]
    migrate_to = [('game', '0028_copy_tower_zone_to_zones')]

    def _migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_single_fk_links_copied_and_empty_zones_kept(self):
        old_apps = self._migrate(self.migrate_from)
        OldZone = old_apps.get_model('game', 'Zone')
        OldTower = old_apps.get_model('game', 'Tower')

        bbox = Polygon.from_bbox((23.0, 46.0, 24.0, 47.0))
        linked = OldZone.objects.create(
            name='Linked', scoring_type=3, shape=bbox, color='#000000',
        )
        empty = OldZone.objects.create(
            name='Empty', scoring_type=3, shape=bbox, color='#000000',
        )
        tower = OldTower.objects.create(
            name='T', zone=linked, location=Point(23.5, 46.5),
            is_active=True, category=1,
        )

        new_apps = self._migrate(self.migrate_to)
        NewZone = new_apps.get_model('game', 'Zone')
        NewTower = new_apps.get_model('game', 'Tower')

        migrated = NewTower.objects.get(pk=tower.pk)
        self.assertEqual(
            list(migrated.zones.values_list('pk', flat=True)), [linked.pk],
        )
        # The empty zone is reported, never deleted.
        self.assertTrue(NewZone.objects.filter(pk=empty.pk).exists())


class OverlappingZonesTest(TestCase):
    """Task 7.2 — overlapping zones are evaluated independently."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.team_a = _make_team(self.game, self.group, name='A')
        self.team_b = _make_team(self.game, self.group, name='B', color='#663300')
        self.z1 = _make_zone(self.game, name='Z1', scoring=Zone.SCORE_LIN)
        self.z2 = _make_zone(self.game, name='Z2', scoring=Zone.SCORE_LIN)
        # Shared tower belongs to BOTH zones; z2 has two more members.
        self.shared = _make_tower(self.game, zone=self.z1, name='shared')
        self.shared.zones.add(self.z2)
        self.t2 = _make_tower(self.game, zone=self.z2, name='t2', lng=23.6)
        self.t3 = _make_tower(self.game, zone=self.z2, name='t3', lng=23.7)

    def test_capture_recomputes_each_zone_independently(self):
        self.t2.assign_to_team(self.team_b)
        self.t3.assign_to_team(self.team_b)
        self.shared.assign_to_team(self.team_a)

        # Z1 (only the shared tower): team A controls it.
        self.assertEqual(
            set(self.z1.zone_control(self.group)), {self.team_a.pk},
        )
        # Z2 (B holds 2 of 3): team B keeps control — A won one
        # overlapping zone but not the other.
        self.assertEqual(
            set(self.z2.zone_control(self.group)), {self.team_b.pk},
        )


class ZoneInvariantTest(TestCase):
    """Task 7.3 — every zone retains at least one member tower."""

    def setUp(self):
        from django.core.exceptions import ValidationError
        self.ValidationError = ValidationError
        self.game = _make_game()
        self.zone = _make_zone(self.game)
        self.t1 = _make_tower(self.game, zone=self.zone, name='t1')
        self.t2 = _make_tower(self.game, zone=self.zone, name='t2', lng=23.6)

    def test_removing_non_last_member_is_allowed(self):
        self.t1.zones.remove(self.zone)
        self.assertEqual(self.zone.towers.count(), 1)

    def test_removing_last_member_is_rejected(self):
        from django.db import transaction
        self.t1.zones.remove(self.zone)
        with self.assertRaises(self.ValidationError), transaction.atomic():
            self.t2.zones.remove(self.zone)
        self.assertEqual(self.zone.towers.count(), 1)

    def test_clearing_zone_members_is_rejected(self):
        from django.db import transaction
        with self.assertRaises(self.ValidationError), transaction.atomic():
            self.zone.towers.clear()
        self.assertEqual(self.zone.towers.count(), 2)

    def test_deleting_last_member_tower_is_rejected(self):
        from django.db import transaction
        self.t1.delete()
        with self.assertRaises(self.ValidationError), transaction.atomic():
            self.t2.delete()
        self.assertTrue(Tower.objects.filter(pk=self.t2.pk).exists())

    def test_zone_clean_rejects_empty_zone(self):
        self.t1.zones.remove(self.zone)
        # Bypass the guard to simulate a legacy empty zone.
        self.zone.towers.through.objects.filter(zone=self.zone).delete()
        with self.assertRaises(self.ValidationError):
            self.zone.clean()

    def test_zone_delete_itself_is_allowed(self):
        # Deleting the zone removes the memberships with it — the
        # invariant constrains emptying a zone, not deleting it.
        self.zone.delete()
        self.assertFalse(Zone.objects.filter(pk=self.zone.pk).exists())
        self.assertTrue(Tower.objects.filter(pk=self.t1.pk).exists())


class LogicalNotSpatialTest(TestCase):
    """Task 7.4 — membership is an explicit link, never geometry."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group)
        # Zone polygon spans (23..24, 46..47).
        self.zone = _make_zone(self.game, scoring=Zone.SCORE_LIN)

    def test_tower_outside_polygon_still_contributes_when_linked(self):
        outside = _make_tower(
            self.game, zone=self.zone, name='outside', lng=30.0, lat=50.0,
        )
        outside.assign_to_team(self.team)
        self.assertEqual(
            set(self.zone.zone_control(self.group)), {self.team.pk},
        )

    def test_tower_inside_polygon_is_never_auto_added(self):
        inside = _make_tower(self.game, name='inside', lng=23.5, lat=46.5)
        self.assertEqual(inside.zones.count(), 0)
        inside.assign_to_team(self.team)
        # No membership → no control contribution.
        self.assertEqual(set(self.zone.zone_control(self.group)), set())


class UnassignAcrossZonesTest(TestCase):
    """Task 7.5 — deactivating a tower recomputes all of its zones."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.team_a = _make_team(self.game, self.group, name='A')
        self.team_b = _make_team(self.game, self.group, name='B', color='#663300')
        self.z1 = _make_zone(self.game, name='Z1', scoring=Zone.SCORE_LIN)
        self.z2 = _make_zone(self.game, name='Z2', scoring=Zone.SCORE_LIN)
        self.shared = _make_tower(self.game, zone=self.z1, name='shared')
        self.shared.zones.add(self.z2)
        self.other = _make_tower(self.game, zone=self.z2, name='other', lng=23.6)

    def test_deactivation_closes_and_reopens_across_all_zones(self):
        self.shared.assign_to_team(self.team_a)
        self.other.assign_to_team(self.team_b)
        # Z1 → A. Z2 → tie (1–1) keeps both (historical plurality).
        self.assertEqual(set(self.z1.zone_control(self.group)), {self.team_a.pk})
        self.assertEqual(
            set(self.z2.zone_control(self.group)),
            {self.team_a.pk, self.team_b.pk},
        )

        self.shared.is_active = False
        self.shared.save()

        # Z1 has no active members left: every ownership closed.
        self.assertEqual(set(self.z1.zone_control(self.group)), set())
        # Z2 recomputed: only B still holds a member tower.
        self.assertEqual(set(self.z2.zone_control(self.group)), {self.team_b.pk})
        closed = TeamZoneOwnership.objects.get(zone=self.z2, team=self.team_a)
        self.assertIsNotNone(closed.timestamp_end)


class AutocreateZoneTest(TestCase):
    """Autocreate-circle-zone adds to the tower's zones set (task 1.3)."""

    def setUp(self):
        self.game = _make_game()

    def test_autocreate_zone_added_to_set(self):
        tower = Tower.objects.create(
            name='Solo', location=Point(23.5, 46.5), is_active=True,
            category=Tower.CATEGORY_NORMAL, autocreate_zone=True,
        )
        zones = list(tower.zones.all())
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0].name, 'Solo - zone')
        # Founding member — the invariant holds from creation.
        self.assertEqual(zones[0].towers.count(), 1)

    def test_autocreate_is_idempotent(self):
        tower = Tower.objects.create(
            name='Solo', location=Point(23.5, 46.5), is_active=True,
            category=Tower.CATEGORY_NORMAL, autocreate_zone=True,
        )
        tower.save()
        self.assertEqual(tower.zones.count(), 1)

    def test_no_autocreate_when_tower_has_zones(self):
        zone = _make_zone(self.game)
        tower = _make_tower(self.game, zone=zone)
        tower.autocreate_zone = True
        tower.save()
        self.assertEqual(
            list(tower.zones.values_list('pk', flat=True)), [zone.pk],
        )

    def test_autocreated_zone_joins_tower_collections(self):
        tower = Tower.objects.create(
            name='Solo', location=Point(23.5, 46.5), is_active=True,
            category=Tower.CATEGORY_NORMAL,
        )
        collection = _game_collection(self.game)
        collection.towers.add(tower)
        tower.autocreate_zone = True
        tower.save()
        zone = tower.zones.get()
        self.assertIn(collection.pk, zone.collections.values_list('pk', flat=True))


class TopologyApiTest(TestCase):
    """Tasks 4.1–4.2 — serializers and staff filters over the M2M."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.z1 = _make_zone(self.game, name='Z1')
        self.z2 = _make_zone(self.game, name='Z2')
        self.tower = _make_tower(self.game, zone=self.z1)
        self.keeper = _make_tower(self.game, zone=self.z2, name='keeper', lng=23.6)
        self.team = _make_team(self.game, self.group)
        self.session = _default_session(self.game)
        self.player_client, _ = _authed_client(self.team, username='mapviewer')
        self.staff_client, _ = _staff_client(session=self.session)

    def test_player_tower_payload_lists_zones(self):
        self.tower.zones.add(self.z2)
        resp = self.player_client.get('/api/towers/')
        self.assertEqual(resp.status_code, 200)
        payload = next(t for t in resp.json() if t['id'] == self.tower.id)
        self.assertNotIn('zone', payload)
        self.assertEqual(set(payload['zones']), {self.z1.pk, self.z2.pk})

    def test_staff_tower_zones_editable(self):
        resp = self.staff_client.patch(
            f'/api/staff/towers/{self.tower.id}/',
            {'zones': [self.z1.pk, self.z2.pk]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(
            set(self.tower.zones.values_list('pk', flat=True)),
            {self.z1.pk, self.z2.pk},
        )

    def test_staff_tower_update_rejects_emptying_a_zone(self):
        resp = self.staff_client.patch(
            f'/api/staff/towers/{self.tower.id}/',
            {'zones': []},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.z1.towers.count(), 1)

    def test_staff_tower_delete_rejected_for_last_member(self):
        resp = self.staff_client.delete(f'/api/staff/towers/{self.tower.id}/')
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Tower.objects.filter(pk=self.tower.pk).exists())

    def test_staff_zone_lists_member_towers(self):
        resp = self.staff_client.get('/api/staff/zones/')
        self.assertEqual(resp.status_code, 200)
        z1 = next(z for z in resp.json() if z['id'] == self.z1.pk)
        self.assertEqual(
            [t['id'] for t in z1['towers']], [self.tower.pk],
        )

    def test_staff_filters_by_membership(self):
        resp = self.staff_client.get('/api/staff/towers/', {'zone': self.z1.pk})
        self.assertEqual(
            [t['id'] for t in resp.json()], [self.tower.pk],
        )
        resp = self.staff_client.get('/api/staff/zones/', {'tower': self.keeper.pk})
        self.assertEqual(
            [z['id'] for z in resp.json()], [self.z2.pk],
        )




# ---------------------------------------------------------------------------
# field-authoring-mode — create-at-GPS, reference photos, zone drawing,
# attach-challenge, collection permission gate, draft staging (tasks 5.1–5.6)
# ---------------------------------------------------------------------------


class FieldAuthoringTowerApiTest(TestCase):
    """Tasks 5.1 / 5.2 — drop-at-GPS with provenance + reference photos."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.collection = _game_collection(self.game)
        self.team = _make_team(self.game, self.group)
        self.staff_client, self.staff = _staff_client(
            session=self.team.session, username='curator',
        )

    def test_drop_tower_records_accuracy_and_files_into_collection(self):
        resp = self.staff_client.post(
            '/api/staff/towers/',
            {
                'name': 'Fountain',
                'category': Tower.CATEGORY_NORMAL,
                'is_active': False,
                'lat': 46.51,
                'lng': 23.52,
                'authored_accuracy_m': 12.5,
                'collection': self.collection.id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        tower = Tower.objects.get(pk=resp.json()['id'])
        self.assertAlmostEqual(tower.location.x, 23.52)
        self.assertAlmostEqual(tower.location.y, 46.51)
        self.assertEqual(tower.authored_accuracy_m, 12.5)
        self.assertFalse(tower.is_active)
        self.assertIn(tower, self.collection.towers.all())
        # Read side reports GeoJSON location + provenance.
        self.assertEqual(resp.json()['location']['coordinates'], [23.52, 46.51])
        self.assertEqual(resp.json()['authored_accuracy_m'], 12.5)

    def test_desk_authored_towers_have_null_provenance(self):
        tower = _make_tower(self.game, name='Desk')
        self.assertIsNone(tower.authored_accuracy_m)

    def test_create_without_coordinates_is_rejected(self):
        resp = self.staff_client.post(
            '/api/staff/towers/',
            {'name': 'Nowhere', 'category': 1, 'is_active': True},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_nudge_updates_location_via_lat_lng(self):
        tower = _make_tower(self.game, name='T1')
        resp = self.staff_client.patch(
            f'/api/staff/towers/{tower.id}/',
            {'lat': 46.499, 'lng': 23.501},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        tower.refresh_from_db()
        self.assertAlmostEqual(tower.location.x, 23.501)
        self.assertAlmostEqual(tower.location.y, 46.499)

    def test_photo_upload_records_capture_provenance(self):
        tower = _make_tower(self.game, name='T1')
        resp = self.staff_client.post(
            f'/api/staff/towers/{tower.id}/photos/',
            {
                'image': f'data:image/png;base64,{_tiny_png_b64()}',
                'caption': 'north face',
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        photo = TowerPhoto.objects.get(pk=resp.json()['id'])
        self.assertEqual(photo.tower, tower)
        self.assertEqual(photo.caption, 'north face')
        self.assertEqual(photo.captured_by, self.staff)
        self.assertIsNotNone(photo.captured_at)

    def test_tower_may_have_multiple_photos_listed_and_deleted(self):
        tower = _make_tower(self.game, name='T1')
        for caption in ('front', 'back'):
            self.staff_client.post(
                f'/api/staff/towers/{tower.id}/photos/',
                {'image': f'data:image/png;base64,{_tiny_png_b64()}', 'caption': caption},
                format='json',
            )
        resp = self.staff_client.get(f'/api/staff/towers/{tower.id}/photos/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

        photo_id = resp.json()[0]['id']
        resp = self.staff_client.delete(
            f'/api/staff/towers/{tower.id}/photos/{photo_id}/',
        )
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(tower.photos.count(), 1)

    def test_photo_endpoints_require_staff(self):
        tower = _make_tower(self.game, name='T1')
        player_client, _ = _authed_client(self.team)
        resp = player_client.post(
            f'/api/staff/towers/{tower.id}/photos/',
            {'image': f'data:image/png;base64,{_tiny_png_b64()}'},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)


class FieldAuthoringZoneApiTest(TestCase):
    """Task 5.3 — walked/tapped vertices persist and file into the collection."""

    def setUp(self):
        self.game = _make_game()
        self.collection = _game_collection(self.game)
        self.staff_client, self.staff = _staff_client(username='curator')

    def test_walked_boundary_creates_zone_in_collection(self):
        resp = self.staff_client.post(
            '/api/staff/zones/',
            {
                'name': 'Old town',
                'scoring_type': Zone.SCORE_LIN,
                'vertices': [[23.50, 46.50], [23.52, 46.50], [23.52, 46.52]],
                'collection': self.collection.id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        zone = Zone.objects.get(pk=resp.json()['id'])
        # Ring closed server-side: 3 marks -> 4 ring points.
        self.assertEqual(len(zone.shape.coords[0]), 4)
        self.assertEqual(zone.shape.coords[0][0], zone.shape.coords[0][-1])
        self.assertIn(zone, self.collection.zones.all())
        self.assertEqual(resp.json()['shape']['type'], 'Polygon')

    def test_adjusting_vertices_persists_the_new_boundary(self):
        zone = _make_zone(self.game, name='Z1')
        resp = self.staff_client.patch(
            f'/api/staff/zones/{zone.id}/',
            {'vertices': [[23.1, 46.1], [23.2, 46.1], [23.2, 46.2], [23.1, 46.2]]},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        zone.refresh_from_db()
        self.assertEqual(len(zone.shape.coords[0]), 5)
        self.assertAlmostEqual(zone.shape.coords[0][0][0], 23.1)

    def test_too_few_vertices_rejected(self):
        resp = self.staff_client.post(
            '/api/staff/zones/',
            {
                'name': 'Line',
                'scoring_type': Zone.SCORE_LIN,
                'vertices': [[23.5, 46.5], [23.6, 46.5]],
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


class FieldAuthoringChallengeAttachTest(TestCase):
    """Task 5.4 — attach existing/new challenge; visible to players at the tower."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, name='T1', zone=self.zone)
        self.team = _make_team(self.game, self.group)
        self.staff_client, self.staff = _staff_client(
            session=self.team.session, username='curator',
        )

    def test_attach_existing_challenge(self):
        challenge = Challenge.objects.create(
            game=self.game, text='Sing a song', difficulty=1,
        )
        resp = self.staff_client.post(
            f'/api/staff/towers/{self.tower.id}/attach-challenge/',
            {'challenge': challenge.id},
            format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        challenge.refresh_from_db()
        self.assertEqual(challenge.tower, self.tower)

    def test_attach_creates_new_challenge_on_the_spot(self):
        resp = self.staff_client.post(
            f'/api/staff/towers/{self.tower.id}/attach-challenge/',
            {'game': self.game.id, 'text': 'Count the windows', 'difficulty': 2},
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        challenge = Challenge.objects.get(pk=resp.json()['id'])
        self.assertEqual(challenge.tower, self.tower)
        self.assertEqual(challenge.difficulty, 2)

    def test_attached_challenge_is_visible_to_players_at_the_tower(self):
        resp = self.staff_client.post(
            f'/api/staff/towers/{self.tower.id}/attach-challenge/',
            {'game': self.game.id, 'text': 'Field challenge'},
            format='json',
        )
        challenge_id = resp.json()['id']
        player_client, _ = _authed_client(self.team)
        resp = player_client.get(f'/api/towers/{self.tower.id}/state/')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.assertEqual(resp.json()['next_challenge']['id'], challenge_id)

    def test_attach_requires_a_challenge_or_game_and_text(self):
        resp = self.staff_client.post(
            f'/api/staff/towers/{self.tower.id}/attach-challenge/',
            {},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)


class FieldAuthoringPermissionTest(TestCase):
    """Task 5.5 — writes are gated to staff authorised for the Collection."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner', email='owner@example.com',
            password='password123', is_staff=True,
        )
        # A Game with a recorded creator: only the creator (or a CREATOR
        # collaborator / superuser) may edit its template.
        self.game = Game.objects.create(
            name='Owned game', slug='owned-game', created_by=self.owner,
        )
        self.collection = Collection.objects.create(
            name='Owned map', slug='owned-map', created_by=self.owner,
        )
        self.game.collections.add(self.collection)
        self.tower = Tower.objects.create(
            name='Owned T', location=Point(23.5, 46.5),
            is_active=True, category=Tower.CATEGORY_NORMAL,
        )
        self.collection.towers.add(self.tower)
        self.zone = Zone.objects.create(
            name='Owned Z', scoring_type=Zone.SCORE_LIN,
            shape=Polygon.from_bbox((23.0, 46.0, 24.0, 47.0)),
        )
        self.collection.zones.add(self.zone)
        # A staff user with no rights on the owner's game.
        self.other_client, self.other = _staff_client(username='outsider')

    def test_unauthorised_staff_cannot_create_into_the_collection(self):
        resp = self.other_client.post(
            '/api/staff/towers/',
            {
                'name': 'Intruder', 'category': 1, 'is_active': False,
                'lat': 46.5, 'lng': 23.5, 'collection': self.collection.id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 403)
        resp = self.other_client.post(
            '/api/staff/zones/',
            {
                'name': 'Intruder Z', 'scoring_type': Zone.SCORE_LIN,
                'vertices': [[23.5, 46.5], [23.6, 46.5], [23.6, 46.6]],
                'collection': self.collection.id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_unauthorised_staff_cannot_adjust_collection_geometry(self):
        resp = self.other_client.patch(
            f'/api/staff/towers/{self.tower.id}/',
            {'lat': 46.6, 'lng': 23.6},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)
        resp = self.other_client.patch(
            f'/api/staff/zones/{self.zone.id}/',
            {'vertices': [[23.5, 46.5], [23.6, 46.5], [23.6, 46.6]]},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)
        resp = self.other_client.post(
            f'/api/staff/towers/{self.tower.id}/photos/',
            {'image': f'data:image/png;base64,{_tiny_png_b64()}'},
            format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_creator_may_author_into_their_collection(self):
        token = Token.objects.create(user=self.owner)
        owner_client = APIClient()
        owner_client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        resp = owner_client.post(
            '/api/staff/towers/',
            {
                'name': 'Legit', 'category': 1, 'is_active': False,
                'lat': 46.5, 'lng': 23.5, 'collection': self.collection.id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)

    def test_creator_collaborator_may_author(self):
        GameCollaborator.objects.create(
            game=self.game, user=self.other,
            role=GameCollaborator.ROLE_CREATOR,
        )
        resp = self.other_client.post(
            '/api/staff/towers/',
            {
                'name': 'Collab T', 'category': 1, 'is_active': False,
                'lat': 46.5, 'lng': 23.5, 'collection': self.collection.id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)


class FieldAuthoringDraftStagingTest(TestCase):
    """Task 5.6 — inactive field drafts stay out of live session scoping."""

    def setUp(self):
        self.game = _make_game()
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.live_tower = _make_tower(self.game, name='Live', zone=self.zone)
        self.team = _make_team(self.game, self.group)
        self.staff_client, self.staff = _staff_client(
            session=self.team.session, username='curator',
        )
        self.player_client, _ = _authed_client(self.team)

    def _drop_draft(self):
        resp = self.staff_client.post(
            '/api/staff/towers/',
            {
                'name': 'Draft', 'category': 1, 'is_active': False,
                'lat': 46.55, 'lng': 23.55,
                'collection': _game_collection(self.game).id,
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201, resp.content)
        return resp.json()['id']

    def test_inactive_draft_hidden_from_players_until_activated(self):
        draft_id = self._drop_draft()

        resp = self.player_client.get('/api/towers/')
        self.assertEqual(resp.status_code, 200)
        names = [t['name'] for t in resp.json()]
        self.assertIn('Live', names)
        self.assertNotIn('Draft', names)

        # Tower state view also refuses the inactive draft.
        resp = self.player_client.get(f'/api/towers/{draft_id}/state/')
        self.assertEqual(resp.status_code, 404)

        # Activation publishes it to the live session scope.
        resp = self.staff_client.patch(
            f'/api/staff/towers/{draft_id}/', {'is_active': True}, format='json',
        )
        self.assertEqual(resp.status_code, 200, resp.content)
        resp = self.player_client.get('/api/towers/')
        self.assertIn('Draft', [t['name'] for t in resp.json()])

    def test_staff_list_still_shows_drafts(self):
        self._drop_draft()
        resp = self.staff_client.get('/api/staff/towers/')
        self.assertIn('Draft', [t['name'] for t in resp.json()])


# ---------------------------------------------------------------------------
# realtime-and-notifications — broadcasts, consumer, fallback, ASGI smoke
# ---------------------------------------------------------------------------


class _RecorderPushSender(BasePushSender):
    """Test double for the push-sender interface: records, delivers nothing."""

    def __init__(self, fail_with=None):
        self.sent = []
        self.fail_with = fail_with

    def send(self, subscription, payload):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((subscription, payload))


class _BrokenLayer:
    """Channel-layer stand-in whose group_send always fails."""

    async def group_send(self, group, message):
        raise RuntimeError('boom')


@override_settings(REALTIME_SCOREBOARD_THROTTLE_SECONDS=0)
class RealtimeBroadcastTest(TestCase):
    """7.3 — the ownership/zone recompute seams emit typed events."""

    def setUp(self):
        events.reset_throttle()
        self.game = _make_game('Realtime Game')
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.t1 = _make_team(self.game, self.group, name='rt1', color='#111111')
        self.t2 = _make_team(self.game, self.group, name='rt2', color='#222222')
        self.session = self.t1.session

    def _capture(self, team):
        with patch('game.events.broadcast_session_event', return_value=True) as recorder:
            self.tower.assign_to_team(team)
        return recorder.call_args_list

    @staticmethod
    def _of_type(calls, event_type):
        return [call.args for call in calls if call.args[1] == event_type]

    def test_conquer_emits_ownership_zone_and_scoreboard(self):
        calls = self._capture(self.t1)

        ownership = self._of_type(calls, events.EVENT_TOWER_OWNERSHIP_CHANGED)
        self.assertEqual(len(ownership), 1)
        session_id, _, payload = ownership[0]
        self.assertEqual(session_id, self.session.id)
        self.assertEqual(payload['kind'], 'conquered')
        self.assertEqual(payload['tower_id'], self.tower.id)
        self.assertEqual(payload['zone_id'], self.zone.id)
        self.assertEqual(payload['team']['team_id'], self.t1.id)
        self.assertEqual(
            payload['ownership'][self.group.slug]['team_id'], self.t1.id,
        )

        # First capture flips zone control from nobody to t1 → recolor.
        zones = self._of_type(calls, events.EVENT_ZONE_CONTROL_CHANGED)
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0][2]['zone_id'], self.zone.id)
        self.assertEqual(zones[0][2]['colors'][self.group.slug], '#111111')

        # The initial-bonus award goes through Team.update_score, so a
        # capture may emit more than one snapshot; each is complete, so
        # only the LAST one matters to clients.
        scoreboard = self._of_type(calls, events.EVENT_SCOREBOARD_UPDATED)
        self.assertGreaterEqual(len(scoreboard), 1)
        names = [e['team_name'] for e in scoreboard[-1][2]['entries']]
        self.assertCountEqual(names, ['rt1', 'rt2'])
        for entry in scoreboard[-1][2]['entries']:
            for key in ('team_id', 'team_color', 'locked_score',
                        'floating_score', 'current_score'):
                self.assertIn(key, entry)

    def test_steal_emits_stolen_and_zone_flip(self):
        self._capture(self.t1)
        calls = self._capture(self.t2)

        ownership = self._of_type(calls, events.EVENT_TOWER_OWNERSHIP_CHANGED)
        self.assertEqual(len(ownership), 1)
        payload = ownership[0][2]
        self.assertEqual(payload['kind'], 'stolen')
        self.assertEqual(payload['team']['team_id'], self.t2.id)
        self.assertEqual(
            payload['ownership'][self.group.slug]['team_id'], self.t2.id,
        )

        zones = self._of_type(calls, events.EVENT_ZONE_CONTROL_CHANGED)
        self.assertEqual(len(zones), 1)
        self.assertEqual(zones[0][2]['colors'][self.group.slug], '#222222')

    def test_recapture_by_same_team_is_conquered_not_stolen(self):
        self._capture(self.t1)
        calls = self._capture(self.t1)
        payload = self._of_type(calls, events.EVENT_TOWER_OWNERSHIP_CHANGED)[0][2]
        self.assertEqual(payload['kind'], 'conquered')

    def test_unassign_emits_released(self):
        self._capture(self.t1)
        with patch('game.events.broadcast_session_event', return_value=True) as recorder:
            self.tower.unassign()
        calls = recorder.call_args_list

        ownership = self._of_type(calls, events.EVENT_TOWER_OWNERSHIP_CHANGED)
        self.assertEqual(len(ownership), 1)
        payload = ownership[0][2]
        self.assertEqual(payload['kind'], 'released')
        self.assertIsNone(payload['team'])
        self.assertIsNone(payload['ownership'][self.group.slug])

        self.assertEqual(
            len(self._of_type(calls, events.EVENT_ZONE_CONTROL_CHANGED)), 1,
        )
        self.assertGreaterEqual(
            len(self._of_type(calls, events.EVENT_SCOREBOARD_UPDATED)), 1,
        )

    def test_update_score_emits_scoreboard_snapshot(self):
        with patch('game.events.broadcast_session_event', return_value=True) as recorder:
            self.t1.update_score(10)
        scoreboard = self._of_type(
            recorder.call_args_list, events.EVENT_SCOREBOARD_UPDATED,
        )
        self.assertEqual(len(scoreboard), 1)
        entry = next(
            e for e in scoreboard[0][2]['entries'] if e['team_id'] == self.t1.id
        )
        self.assertEqual(entry['locked_score'], 10)

    def test_scoreboard_updates_coalesced_per_session(self):
        with override_settings(REALTIME_SCOREBOARD_THROTTLE_SECONDS=60):
            events.reset_throttle()
            with patch('game.events.broadcast_session_event', return_value=True) as recorder:
                self.t1.update_score(1)
                self.t2.update_score(1)
                scoreboard = self._of_type(
                    recorder.call_args_list, events.EVENT_SCOREBOARD_UPDATED,
                )
                self.assertEqual(len(scoreboard), 1)
                # force=True bypasses the window (used on demand).
                events.emit_scoreboard_update(self.session, force=True)
                scoreboard = self._of_type(
                    recorder.call_args_list, events.EVENT_SCOREBOARD_UPDATED,
                )
                self.assertEqual(len(scoreboard), 2)
        events.reset_throttle()

    def test_session_transition_broadcasts_state_change(self):
        with patch('game.events.broadcast_session_event', return_value=True) as recorder:
            self.session.transition('pause')
        state_events = self._of_type(
            recorder.call_args_list, events.EVENT_SESSION_STATE_CHANGED,
        )
        self.assertEqual(len(state_events), 1)
        payload = state_events[0][2]
        self.assertEqual(payload['state'], Session.PAUSED)
        self.assertEqual(payload['previous'], Session.RUNNING)
        self.assertEqual(payload['action'], 'pause')

    def _consented_member(self):
        Session.objects.filter(pk=self.session.pk).update(
            push_notifications_enabled=True,
        )
        self.session.refresh_from_db()
        # Drop the Teams' cached (stale) Session FK instances too.
        self.t1.refresh_from_db()
        self.t2.refresh_from_db()
        user = User.objects.create_user(
            username='rt-push', email='rt-push@example.com', password='password123',
        )
        TeamMembership.objects.create(team=self.t1, user=user.profile, is_active=True)
        return PushSubscription.objects.create(
            user=user, endpoint='https://push.example/rt', p256dh='k', auth='a',
        )

    def test_capture_hands_off_to_push(self):
        self._consented_member()
        recorder = _RecorderPushSender()
        with patch('organize.push.get_sender', return_value=recorder), \
                patch('game.events.broadcast_session_event', return_value=True):
            self.tower.assign_to_team(self.t1)  # conquer
            self.tower.assign_to_team(self.t2)  # steal
        sent_events = [payload['event'] for _, payload in recorder.sent]
        self.assertEqual(sent_events, ['conquer', 'steal'])
        conquer = recorder.sent[0][1]
        self.assertEqual(conquer['url'], f'/tower/{self.tower.id}')
        self.assertEqual(conquer['tower_id'], self.tower.id)
        self.assertIn(self.tower.name, conquer['body'])

    def test_bonus_emit_broadcasts_and_pushes(self):
        self._consented_member()
        recorder = _RecorderPushSender()
        with patch('organize.push.get_sender', return_value=recorder), \
                patch('game.events.broadcast_session_event', return_value=True) as broadcast:
            events.emit_bonus_appeared(self.session, {'name': 'Double points'})
        bonus = self._of_type(
            broadcast.call_args_list, events.EVENT_BONUS_APPEARED,
        )
        self.assertEqual(len(bonus), 1)
        self.assertEqual(bonus[0][2]['name'], 'Double points')
        self.assertEqual(len(recorder.sent), 1)
        self.assertEqual(recorder.sent[0][1]['event'], 'bonus')
        self.assertIn('Double points', recorder.sent[0][1]['body'])


class RealtimeFallbackTest(TestCase):
    """7.4 — without a channel layer (or with realtime off) REST stays correct."""

    def setUp(self):
        self.game = _make_game('Fallback Game')
        self.group = _make_group(self.game)
        self.zone = _make_zone(self.game)
        self.tower = _make_tower(self.game, zone=self.zone)
        self.team = _make_team(self.game, self.group, name='fb1')
        self.session = self.team.session
        self.api, self.user = _authed_client(self.team, username='fb-player')

    def _assert_rest_snapshot_correct(self):
        towers_resp = self.api.get('/api/towers/')
        self.assertEqual(towers_resp.status_code, 200)
        self.assertIn(self.tower.id, [t['id'] for t in towers_resp.json()])
        state = self.api.get(f'/api/towers/{self.tower.id}/state/').json()
        self.assertEqual(state['ownership']['team_name'], 'fb1')
        resp = self.api.get(f'/api/sessions/{self.session.id}/scoreboard/')
        self.assertEqual(resp.status_code, 200)
        names = [e['team_name'] for e in resp.json()['entries']]
        self.assertIn('fb1', names)

    @override_settings(CHANNEL_LAYERS={})
    def test_no_channel_layer_degrades_to_noop(self):
        self.assertFalse(
            events.broadcast_session_event(self.session.id, 'x', {}),
        )
        self.tower.assign_to_team(self.team)  # must not raise
        self._assert_rest_snapshot_correct()

    def test_realtime_disabled_keeps_rest_path_working(self):
        Session.objects.filter(pk=self.session.pk).update(realtime_enabled=False)
        self.tower.assign_to_team(self.team)
        self._assert_rest_snapshot_correct()
        body = self.api.get('/api/current-session/').json()
        self.assertFalse(body['realtime_enabled'])

    def test_layer_send_failure_is_swallowed(self):
        with patch('game.events._channel_layer', return_value=_BrokenLayer()):
            self.assertFalse(
                events.broadcast_session_event(self.session.id, 'x', {}),
            )
            self.tower.assign_to_team(self.team)  # must not raise
        self._assert_rest_snapshot_correct()


class RealtimeConfigKnobTest(TestCase):
    """7.5 — Game defaults + nullable Session overrides via effective()."""

    def setUp(self):
        self.game = _make_game('Knob Game')
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group, name='kn1')
        self.session = self.team.session

    def test_defaults_preserve_current_behavior(self):
        self.assertTrue(self.game.realtime_enabled)
        self.assertFalse(self.game.push_notifications_enabled)
        self.assertIsNone(self.session.realtime_enabled)
        self.assertIsNone(self.session.push_notifications_enabled)
        self.assertTrue(self.session.effective('realtime_enabled'))
        self.assertFalse(self.session.effective('push_notifications_enabled'))

    def test_session_override_wins_over_game_default(self):
        self.session.realtime_enabled = False
        self.session.push_notifications_enabled = True
        self.session.save()
        self.assertFalse(self.session.effective('realtime_enabled'))
        self.assertTrue(self.session.effective('push_notifications_enabled'))

    def test_fields_are_registered_overridable(self):
        from organize.models import OVERRIDABLE_CONFIG_FIELDS
        self.assertIn('realtime_enabled', OVERRIDABLE_CONFIG_FIELDS)
        self.assertIn('push_notifications_enabled', OVERRIDABLE_CONFIG_FIELDS)

    def test_current_session_payload_carries_effective_values(self):
        api, _ = _authed_client(self.team, username='kn-player')
        self.session.realtime_enabled = False
        self.session.push_notifications_enabled = True
        self.session.save()
        body = api.get('/api/current-session/').json()
        self.assertFalse(body['realtime_enabled'])
        self.assertTrue(body['push_notifications_enabled'])


class RealtimeConsumerTest(TransactionTestCase):
    """7.1 / 7.2 — socket auth, Session scoping, cross-Session isolation.

    Runs against the full ASGI stack (token middleware + URL router +
    consumer) with the InMemory channel layer — no Redis involved.
    """

    def setUp(self):
        events.reset_throttle()
        self.game = _make_game('WS Game')
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group, name='ws1')
        self.session = self.team.session
        _, self.member = _authed_client(self.team, username='ws-member')
        self.member_token = Token.objects.get(user=self.member).key

        self.game_b = _make_game('WS Game B')
        self.group_b = _make_group(self.game_b, name='Explo B', slug='explo-b')
        self.team_b = _make_team(self.game_b, self.group_b, name='ws2')
        self.session_b = self.team_b.session
        _, self.member_b = _authed_client(self.team_b, username='ws-member-b')
        self.member_b_token = Token.objects.get(user=self.member_b).key

    @staticmethod
    def _path(session, token=None):
        suffix = f'?token={token}' if token else ''
        return f'/ws/session/{session.id}/{suffix}'

    async def _connect(self, session, token=None):
        communicator = WebsocketCommunicator(
            asgi_application, self._path(session, token),
        )
        connected, code = await communicator.connect()
        return communicator, connected, code

    async def test_member_connects_and_receives_broadcast(self):
        communicator, connected, _ = await self._connect(
            self.session, self.member_token,
        )
        self.assertTrue(connected)
        await database_sync_to_async(events.emit_scoreboard_update)(
            self.session, force=True,
        )
        message = await communicator.receive_json_from()
        self.assertEqual(message['type'], 'scoreboard.updated')
        self.assertEqual(message['session'], self.session.id)
        self.assertIn('ts', message)
        names = [e['team_name'] for e in message['payload']['entries']]
        self.assertIn('ws1', names)
        # Heartbeat: the only client→server message honoured.
        await communicator.send_json_to({'type': 'ping'})
        self.assertEqual(await communicator.receive_json_from(), {'type': 'pong'})
        await communicator.disconnect()

    async def test_staff_without_membership_admitted(self):
        def _make_staff():
            _, staff = _staff_client(username='ws-staff')
            return Token.objects.get(user=staff).key

        staff_token = await database_sync_to_async(_make_staff)()
        communicator, connected, _ = await self._connect(self.session, staff_token)
        self.assertTrue(connected)
        await communicator.disconnect()

    async def test_unauthenticated_socket_rejected(self):
        communicator, connected, code = await self._connect(self.session)
        self.assertFalse(connected)
        self.assertEqual(code, 4401)
        await communicator.disconnect()

    async def test_bad_token_rejected(self):
        communicator, connected, code = await self._connect(
            self.session, 'not-a-real-token',
        )
        self.assertFalse(connected)
        self.assertEqual(code, 4401)
        await communicator.disconnect()

    async def test_non_member_rejected(self):
        communicator, connected, code = await self._connect(
            self.session, self.member_b_token,
        )
        self.assertFalse(connected)
        self.assertEqual(code, 4403)
        await communicator.disconnect()

    async def test_unknown_session_rejected(self):
        communicator = WebsocketCommunicator(
            asgi_application, f'/ws/session/999999/?token={self.member_token}',
        )
        connected, code = await communicator.connect()
        self.assertFalse(connected)
        self.assertEqual(code, 4404)
        await communicator.disconnect()

    async def test_realtime_disabled_refuses_socket(self):
        await database_sync_to_async(
            lambda: Session.objects.filter(pk=self.session.pk).update(
                realtime_enabled=False,
            )
        )()
        communicator, connected, code = await self._connect(
            self.session, self.member_token,
        )
        self.assertFalse(connected)
        self.assertEqual(code, 4423)
        await communicator.disconnect()

    async def test_events_do_not_leak_across_sessions(self):
        comm_a, connected_a, _ = await self._connect(self.session, self.member_token)
        comm_b, connected_b, _ = await self._connect(
            self.session_b, self.member_b_token,
        )
        self.assertTrue(connected_a)
        self.assertTrue(connected_b)

        await database_sync_to_async(events.emit_scoreboard_update)(
            self.session, force=True,
        )
        message = await comm_a.receive_json_from()
        self.assertEqual(message['session'], self.session.id)
        # The Session-B socket must see NOTHING from Session A.
        self.assertTrue(await comm_b.receive_nothing(timeout=0.2))

        await database_sync_to_async(events.emit_scoreboard_update)(
            self.session_b, force=True,
        )
        message_b = await comm_b.receive_json_from()
        self.assertEqual(message_b['session'], self.session_b.id)

        await comm_a.disconnect()
        await comm_b.disconnect()


class AsgiHttpSmokeTest(TransactionTestCase):
    """7.7 — HTTP behaves identically served under the Channels ASGI app."""

    def setUp(self):
        self.game = _make_game('ASGI Game')
        self.group = _make_group(self.game)
        self.team = _make_team(self.game, self.group, name='asgi1')
        self.session = self.team.session
        _, self.user = _authed_client(self.team, username='asgi-player')
        self.token = Token.objects.get(user=self.user).key

    async def test_health_under_asgi(self):
        communicator = HttpCommunicator(
            asgi_application, 'GET', '/health/',
            headers=[(b'host', b'testserver')],
        )
        response = await communicator.get_response()
        self.assertEqual(response['status'], 200)
        self.assertEqual(json.loads(response['body']), {'status': 'ok'})

    async def test_authed_api_matches_wsgi(self):
        communicator = HttpCommunicator(
            asgi_application, 'GET', '/api/current-session/',
            headers=[
                (b'host', b'testserver'),
                (b'authorization', f'Token {self.token}'.encode()),
            ],
        )
        response = await communicator.get_response()
        self.assertEqual(response['status'], 200)
        asgi_body = json.loads(response['body'])

        def _wsgi_body():
            client = APIClient()
            client.credentials(HTTP_AUTHORIZATION=f'Token {self.token}')
            return client.get('/api/current-session/').json()

        self.assertEqual(asgi_body, await database_sync_to_async(_wsgi_body)())
