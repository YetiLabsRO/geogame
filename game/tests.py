from datetime import datetime, timedelta

from django.test import TestCase
from unittest.mock import MagicMock, patch
from django.utils import timezone
from jedi.inference.filters import GlobalNameFilter

from game.models import Tower, TeamZoneOwnership, TeamTowerOwnership, TeamTowerChallenge, Challenge
from organize.models import Team, Game, TeamGroup


class ZoneControlTest(TestCase):
    fixtures = ["tower_zones.json"]

    def setUp(self):
        self.game = Game.objects.create(name='game1', start_time=timezone.now(), end_time=timezone.now() + timedelta(hours=1))
        self.group = TeamGroup.objects.create(name='group1', game=self.game)
        self.t1 = Team.objects.create(name="explo1", game=self.game, group=self.group, code="EXPLO1", color="#003366")
        self.t2 = Team.objects.create(name="explo2", game=self.game, group=self.group, code="EXPLO2", color="#003366")

        self.tower1 = Tower.objects.get(name__icontains="Dendroparc")
        self.zone1 = self.tower1.zone

    @patch('game.models.Zone.get_score', MagicMock(return_value=1))
    def test_zone_control_from_empty(self):
        self.tower1.assign_to_team(self.t1)
        self.assertEqual(TeamZoneOwnership.objects.all().count(), 1)
        self.assertEqual(list(self.zone1.zone_control(self.t1.group)), [self.t1.pk])
        self.t1 = Team.objects.get(code="EXPLO1")
        self.t2 = Team.objects.get(code="EXPLO2")
        self.assertEqual(self.t1.score, 0)
        self.assertEqual(self.t2.score, 0)

        self.tower1.assign_to_team(self.t2)
        self.assertEqual(TeamZoneOwnership.objects.all().count(), 2)
        self.assertEqual(list(self.zone1.zone_control(self.t2.group)), [self.t2.pk])
        self.t1 = Team.objects.get(code="EXPLO1")
        self.t2 = Team.objects.get(code="EXPLO2")
        self.assertEqual(self.t1.score, 1)
        self.assertEqual(self.t2.score, 0)

        self.tower1.unassign()
        self.assertEqual(list(self.zone1.zone_control(self.t1.category)), [])
        self.assertEqual(TeamZoneOwnership.objects.all().count(), 2)
        self.t1 = Team.objects.get(code="EXPLO1")
        self.t2 = Team.objects.get(code="EXPLO2")
        self.assertEqual(self.t2.score, 1)
        self.assertEqual(self.t1.score, 1)

        self.tower1.assign_to_team(self.t1)
        self.tower1.unassign()
        self.assertEqual(TeamZoneOwnership.objects.all().count(), 3)
        self.t1 = Team.objects.get(code="EXPLO1")
        self.t2 = Team.objects.get(code="EXPLO2")
        self.assertEqual(self.t1.score, 2)
        self.assertEqual(self.t2.score, 1)

    def tearDown(self) -> None:
        TeamZoneOwnership.objects.all().delete()
        TeamTowerOwnership.objects.all().delete()
        TeamTowerChallenge.objects.all().delete()


class ChallengeTest(TestCase):
    fixtures = ["tower_zones.json"]

    def setUp(self):
        self.t1 = Team.objects.create(name="explo1", category=Team.EXPLORATORI, code="EXPLO1", color="#003366")
        self.t2 = Team.objects.create(name="explo2", category=Team.EXPLORATORI, code="EXPLO2", color="#003366")

        self.tower1 = Tower.objects.get(name__icontains="Dendroparc")
        self.zone1 = self.tower1.zone

        self.tower2 = Tower.objects.get(name__iexact="Piata")

        self.c1 = Challenge.objects.create(text="c1", tower=self.tower1, difficulty=1)
        self.c2 = Challenge.objects.create(text="c2", tower=self.tower1, difficulty=1)
        self.c3 = Challenge.objects.create(text="c3", tower=self.tower1, difficulty=2)
        self.c4 = Challenge.objects.create(text="c4", tower=self.tower1, difficulty=5)
        self.c5 = Challenge.objects.create(text="c5", tower=None, difficulty=1)
        self.c6 = Challenge.objects.create(text="c6", tower=None, difficulty=2)
        self.c7 = Challenge.objects.create(text="c7", tower=None, difficulty=5)

    def test_challenge_assignment_progression1(self):
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c1)

        ttc = TeamTowerChallenge.objects.create(team=self.t1, tower=self.tower1, challenge=self.c1, outcome=TeamTowerChallenge.REJECTED)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c1)
        self.assertEqual(self.tower1.get_next_challenge(self.t2), self.c1)

        ttc = TeamTowerChallenge.objects.create(team=self.t1, tower=self.tower1, challenge=self.c1, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c2)
        self.assertEqual(self.tower1.get_next_challenge(self.t2), self.c1)

        ttc = TeamTowerChallenge.objects.create(team=self.t1, tower=self.tower1, challenge=self.c2, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c3)
        self.assertEqual(self.tower1.get_next_challenge(self.t2), self.c1)

        ttc = TeamTowerChallenge.objects.create(team=self.t1, tower=self.tower1, challenge=self.c3, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c4)
        self.assertEqual(self.tower1.get_next_challenge(self.t2), self.c1)

        ttc = TeamTowerChallenge.objects.create(team=self.t1, tower=self.tower1, challenge=self.c4, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c5)
        self.assertEqual(self.tower1.get_next_challenge(self.t2), self.c1)

        ttc = TeamTowerChallenge.objects.create(team=self.t1, tower=self.tower1, challenge=self.c5, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c6)
        self.assertEqual(self.tower1.get_next_challenge(self.t2), self.c1)

        ttc = TeamTowerChallenge.objects.create(team=self.t1, tower=self.tower1, challenge=self.c6, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c7)
        self.assertEqual(self.tower1.get_next_challenge(self.t2), self.c1)

        ttc = TeamTowerChallenge.objects.create(team=self.t1, tower=self.tower1, challenge=self.c7, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower1.get_next_challenge(self.t1), self.c7)
        self.assertEqual(self.tower1.get_next_challenge(self.t2), self.c1)

        self.assertEqual(self.tower2.get_next_challenge(self.t1), self.c7)
        self.assertEqual(self.tower2.get_next_challenge(self.t2), self.c5)

        ttc = TeamTowerChallenge.objects.create(team=self.t2, tower=self.tower2, challenge=self.c5, outcome=TeamTowerChallenge.REJECTED)
        self.assertEqual(self.tower2.get_next_challenge(self.t1), self.c7)
        self.assertEqual(self.tower2.get_next_challenge(self.t2), self.c5)

        ttc = TeamTowerChallenge.objects.create(team=self.t2, tower=self.tower2, challenge=self.c5, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower2.get_next_challenge(self.t1), self.c7)
        self.assertEqual(self.tower2.get_next_challenge(self.t2), self.c6)

        ttc = TeamTowerChallenge.objects.create(team=self.t2, tower=self.tower2, challenge=self.c6, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower2.get_next_challenge(self.t1), self.c7)
        self.assertEqual(self.tower2.get_next_challenge(self.t2), self.c7)

        ttc = TeamTowerChallenge.objects.create(team=self.t2, tower=self.tower2, challenge=self.c7, outcome=TeamTowerChallenge.CONFIRMED)
        self.assertEqual(self.tower2.get_next_challenge(self.t1), self.c7)
        self.assertEqual(self.tower2.get_next_challenge(self.t2), self.c7)

    def tearDown(self) -> None:
        TeamZoneOwnership.objects.all().delete()
        TeamTowerOwnership.objects.all().delete()
        TeamTowerChallenge.objects.all().delete()
