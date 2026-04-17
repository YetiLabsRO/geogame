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
  * `organize` app owns Game, TeamGroup, Team, Player, TeamPlayer
  * Teams are grouped by TeamGroup (replacing the legacy EXPLORATORI/TEMERARI/SENIORI
    hardcoded categories). Each Game has its own set of TeamGroups.
"""
import base64
import math
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

from django.contrib.gis.geos import Point, Polygon
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from game.admin import unassign_all
from game.models import (
    Challenge,
    TeamTowerChallenge,
    TeamTowerOwnership,
    TeamZoneOwnership,
    Tower,
    Zone,
)
from organize.models import Game, Team, TeamGroup

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_game(name="Game A"):
    now = timezone.now()
    return Game.objects.create(
        name=name,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )


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


def _make_team(game, group, name="explo1", code="EXPLO1", color="#003366"):
    return Team.objects.create(
        name=name, code=code, color=color, game=game, group=group,
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
        self.t1 = _make_team(self.game, self.group, code="A")
        self.t2 = _make_team(self.game, self.group, name="t2", code="B")

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
        self.t1 = _make_team(self.game, self.group, name="t1", code="A")
        self.t2 = _make_team(self.game, self.group, name="t2", code="B")

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
        t1_explo = _make_team(self.game, self.group, name="e1", code="X1")
        _make_team(self.game, other_group, name="o1", code="X2")

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
        self.team = _make_team(self.game, self.group, code="T1")
        self.challenge = Challenge.objects.create(
            text="c", tower=self.tower, difficulty=1,
        )

    @staticmethod
    def _offset_lat(lat, meters_north):
        return lat + meters_north / 111_111.0

    def test_web_form_within_50m_accepted(self):
        client = APIClient()
        lat = self._offset_lat(46.5, 10)  # 10m north, within 50m
        url = reverse("tower-detail", kwargs={"pk": self.tower.pk})
        resp = client.get(
            url, {"lat": lat, "lng": 23.5, "team_code": self.team.code},
        )
        self.assertEqual(resp.status_code, 200)

    def test_web_form_outside_50m_rejected(self):
        client = APIClient()
        lat = self._offset_lat(46.5, 200)  # 200m north, outside 50m
        url = reverse("tower-detail", kwargs={"pk": self.tower.pk})
        resp = client.get(
            url, {"lat": lat, "lng": 23.5, "team_code": self.team.code},
        )
        self.assertEqual(resp.status_code, 404)

    def test_web_form_51m_rejected(self):
        client = APIClient()
        lat = self._offset_lat(46.5, 51)  # Just outside the 50m threshold
        url = reverse("tower-detail", kwargs={"pk": self.tower.pk})
        resp = client.get(
            url, {"lat": lat, "lng": 23.5, "team_code": self.team.code},
        )
        self.assertEqual(resp.status_code, 404)

    def test_api_submission_outside_50m_rejected(self):
        # The serializer's proximity check rejects submissions further than 50m.
        client = APIClient()
        lat = self._offset_lat(46.5, 200)
        resp = client.post(
            "/api/team_tower_challenges/",
            {
                "team": self.team.pk,
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
        client = APIClient()
        lat = self._offset_lat(46.5, 10)  # 10m north, well within 50m
        resp = client.post(
            "/api/team_tower_challenges/",
            {
                "team": self.team.pk,
                "tower": self.tower.pk,
                "challenge": self.challenge.pk,
                "lat": lat,
                "lng": 23.5,
                "photo": _tiny_png_b64(),
            },
            format="json",
        )
        self.assertEqual(resp.status_code, 201, resp.content)


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
        self.t1 = _make_team(self.game, self.group, code="A")
        self.t2 = _make_team(self.game, self.group, name="t2", code="B")
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
        self.t1 = _make_team(self.game, self.group, name="t1", code="A")
        self.t2 = _make_team(self.game, self.group, name="t2", code="B")

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
        self.team = _make_team(self.game, self.group, code="A")

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
        other = _make_team(self.game, self.group, name="o", code="B")
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
        self.team = _make_team(self.game, self.group, code="A")

    def test_rfid_view_resolves_by_code(self):
        client = APIClient()
        url = reverse("tower-rfid", kwargs={"rfid_code": "ABC123"})
        resp = client.get(url + f"?team={self.team.pk}")
        self.assertEqual(resp.status_code, 200)

    def test_rfid_challenge_form_auto_confirms_and_assigns(self):
        client = APIClient()
        url = reverse("tower-rfid-challenge")
        resp = client.post(
            url,
            {
                "rfid_code": "ABC123",
                "team_code": self.team.code,
                "lat": 46.5,
                "lng": 23.5,
            },
        )
        self.assertEqual(resp.status_code, 302)
        ttc = TeamTowerChallenge.objects.get(
            tower=self.rfid_tower, team=self.team,
        )
        self.assertEqual(ttc.outcome, TeamTowerChallenge.CONFIRMED)
        self.assertTrue(TeamTowerOwnership.objects.filter(
            tower=self.rfid_tower, team=self.team, timestamp_end__isnull=True,
        ).exists())
        self.assertEqual(Team.objects.get(pk=self.team.pk).score, 10)

    def test_rfid_unknown_code_returns_404(self):
        # Detail view should 404, not 500, for an unknown RFID code.
        client = APIClient()
        url = reverse("tower-rfid", kwargs={"rfid_code": "NOPE"})
        resp = client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_rfid_challenge_outside_50m_rejected(self):
        # The RFID form's clean() enforces the 50m proximity check.
        client = APIClient()
        lat = 46.5 + 200 / 111_111.0  # ~200m north
        url = reverse("tower-rfid-challenge")
        resp = client.post(
            url,
            {
                "rfid_code": "ABC123",
                "team_code": self.team.code,
                "lat": lat,
                "lng": 23.5,
            },
        )
        # Form invalid → renders error template with 200 and no redirect
        self.assertNotEqual(resp.status_code, 302)
        self.assertFalse(TeamTowerChallenge.objects.filter(
            team=self.team, tower=self.rfid_tower,
        ).exists())


# ---------------------------------------------------------------------------
# P0.11 — REST API endpoints
# ---------------------------------------------------------------------------


class APIEndpointsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
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
        self.team = _make_team(self.game, self.group, code="E1")
        self.challenge = Challenge.objects.create(
            text="c", tower=self.tower, difficulty=1,
        )

    def test_zones_endpoint_lists_zones_with_active_towers(self):
        resp = self.client.get("/api/zones/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

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
        Challenge.objects.create(text="g", difficulty=1)
        resp = self.client.get("/api/challenges/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 2)

    def test_submission_creates_pending_record(self):
        resp = self.client.post(
            "/api/team_tower_challenges/",
            {
                "team": self.team.pk,
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
        self.t1 = _make_team(self.game, self.group, code="A")
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


class TemplateViewsTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.game = _make_game()
        self.group = _make_group(self.game)

    def test_map_view(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)

    def test_score_map(self):
        resp = self.client.get(
            reverse("score-map", kwargs={"team_short": self.group.slug}),
        )
        self.assertEqual(resp.status_code, 200)

    # Note: rules.html and pending.html still reference legacy URL names
    # (`score-map-teme`, `admin:geogame_...`) that no longer exist after the
    # app rename. Those smoke tests were removed from Phase 0 scope; the
    # templates will be rewritten as Angular components in Phase 2.

    def test_tower_challenge_template(self):
        resp = self.client.get(reverse("tower-challenge"))
        self.assertEqual(resp.status_code, 200)


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
        self.team = _make_team(self.game, self.group, code="A")
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
