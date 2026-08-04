"""Tests for the game simulator backend (game-simulator-backend).

Covers: `setup()` producing a RUNNING session with `[SIM]`-prefixed
naming and real rosters/memberships; `step()` moving players and
recording SimulationEvents; several ticks producing at least one real
CAPTURE with ownership actually changing on the (template-shared) Tower;
a dementors-enabled run draining wizard energy; `teardown()` deleting
every sim-created row while sparing the reusable template + its
geometry; and the staff-only control endpoints (+ non-staff rejection).
"""
import uuid

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point, Polygon
from django.db.models import Sum
from django.test import TestCase
from rest_framework.test import APIClient

from game.models import (
    Collection,
    DementorState,
    LocationConsent,
    LocationPing,
    ProximityIdentity,
    ProximityReport,
    TeamTowerChallenge,
    TeamTowerOwnership,
    Tower,
    Zone,
)
from organize.models import Game, Session, Team, TeamMembership, UserProfile
from simulator.driver import SimulationDriver
from simulator.models import SimulatedPlayer, SimulationEvent, SimulationRun

User = get_user_model()


def _make_game(name='Sim Template'):
    slug = f'{name.lower().replace(" ", "-")}-{uuid.uuid4().hex[:6]}'
    return Game.objects.create(name=name, slug=slug, proximity_meters=50)


def _game_collection(game):
    collection = game.collections.order_by('pk').first()
    if collection is None:
        collection = Collection.objects.create(name=f'{game.name} map', slug=f'{game.slug}-map')
        game.collections.add(collection)
    return collection


def _make_zone(game, name='Zone', shape=None):
    if shape is None:
        shape = Polygon.from_bbox((23.55, 46.06, 23.59, 46.08))
    zone = Zone.objects.create(name=name, scoring_type=Zone.SCORE_LIN, shape=shape)
    _game_collection(game).zones.add(zone)
    return zone


def _make_tower(game, name, lng, lat, zone=None, initial_bonus=5):
    tower = Tower.objects.create(
        name=name, location=Point(lng, lat), is_active=True,
        category=Tower.CATEGORY_NORMAL, initial_bonus=initial_bonus,
    )
    if zone is not None:
        tower.zones.add(zone)
    _game_collection(game).towers.add(tower)
    return tower


def _staff_user(username='staff'):
    return User.objects.create_user(username=username, password='pw', is_staff=True)


class SimulatorDriverTestCase(TestCase):
    """Shared fixture: a small template Game with a zone + two towers."""

    def setUp(self):
        self.game = _make_game()
        self.zone = _make_zone(self.game)
        self.tower_a = _make_tower(self.game, 'Tower A', 23.571797, 46.068374, zone=self.zone)
        self.tower_b = _make_tower(self.game, 'Tower B', 23.573000, 46.069500, zone=self.zone)

    def _run(self, **overrides):
        config = {
            'template_game_id': self.game.id,
            'n_players': 6,
            'n_teams': 2,
            'dementors_enabled': False,
            'tick_seconds': 5,
            'capture_probability': 1.0,
            'center_lat': 46.068374,
            'center_lng': 23.571797,
            'radius_m': 15,
        }
        config.update(overrides)
        return SimulationRun.objects.create(name='Test run', seed=42, config=config)


class SetupTest(SimulatorDriverTestCase):
    def test_setup_creates_running_session_with_naming_and_rosters(self):
        run = self._run()
        driver = SimulationDriver(run)
        driver.setup()

        run.refresh_from_db()
        self.assertEqual(run.status, SimulationRun.RUNNING)
        self.assertIsNotNone(run.game_id)
        self.assertIsNotNone(run.session_id)
        self.assertTrue(run.game.name.startswith('[SIM]'))
        self.assertTrue(run.session.name.startswith('[SIM]'))
        self.assertEqual(run.session.state, Session.RUNNING)

        # 6 fake players, 2 teams, every player on a real active membership
        # with location consent + a proximity identity granted.
        sim_players = list(SimulatedPlayer.objects.filter(run=run))
        self.assertEqual(len(sim_players), 6)
        self.assertEqual(Team.objects.filter(session=run.session).count(), 2)
        for sim_player in sim_players:
            self.assertIsNotNone(sim_player.team_id)
            self.assertTrue(
                TeamMembership.objects.filter(
                    team=sim_player.team, user=sim_player.profile, is_active=True,
                ).exists(),
            )
            self.assertTrue(LocationConsent.objects.filter(
                user=sim_player.profile.user, session=run.session, withdrawn_at__isnull=True,
            ).exists())
            self.assertTrue(
                ProximityIdentity.objects.filter(
                    session=run.session, player=sim_player.profile,
                ).exists(),
            )

        # SPAWN events: one for the game/session + one per player.
        spawn_events = SimulationEvent.objects.filter(run=run, action=SimulationEvent.SPAWN)
        self.assertEqual(spawn_events.count(), 1 + 6)
        transitions = SimulationEvent.objects.filter(
            run=run, action=SimulationEvent.TRANSITION,
        ).order_by('id')
        self.assertEqual(
            [event.payload['action'] for event in transitions],
            ['open_participation', 'start'],
        )

        # The template itself is never mutated — the run drives a clone.
        self.game.refresh_from_db()
        self.assertFalse(self.game.name.startswith('[SIM]'))
        self.assertNotEqual(run.game_id, self.game.id)

    def test_setup_twice_raises(self):
        run = self._run()
        SimulationDriver(run).setup()
        with self.assertRaises(ValueError):
            SimulationDriver(run).setup()


class StepAndCaptureTest(SimulatorDriverTestCase):
    def test_step_records_events_and_moves_players(self):
        run = self._run()
        driver = SimulationDriver(run)
        driver.setup()

        before = {sp.id: (sp.lat, sp.lng) for sp in SimulatedPlayer.objects.filter(run=run)}
        driver.step()
        run.refresh_from_db()
        self.assertEqual(run.tick_count, 1)

        move_events = SimulationEvent.objects.filter(run=run, action=SimulationEvent.MOVE, tick=1)
        self.assertEqual(move_events.count(), 6)
        self.assertTrue(
            SimulationEvent.objects.filter(run=run, action=SimulationEvent.TICK, tick=1).exists(),
        )
        self.assertTrue(LocationPing.objects.filter(session=run.session).exists())

        after = {sp.id: (sp.lat, sp.lng) for sp in SimulatedPlayer.objects.filter(run=run)}
        self.assertNotEqual(before, after)

    def test_step_requires_running_status(self):
        run = self._run()
        driver = SimulationDriver(run)
        driver.setup()
        driver.stop()
        with self.assertRaises(ValueError):
            driver.step()

    def test_several_ticks_capture_tower_and_ownership_changes(self):
        run = self._run()
        driver = SimulationDriver(run)
        driver.setup()

        self.assertFalse(
            TeamTowerOwnership.objects.filter(
                tower=self.tower_a, timestamp_end__isnull=True,
            ).exists(),
        )

        driver.play(4)

        capture_events = SimulationEvent.objects.filter(run=run, action=SimulationEvent.CAPTURE)
        self.assertGreaterEqual(capture_events.count(), 1)

        # Real ownership changed on the real (template-shared-by-pk) Tower.
        open_ownerships = TeamTowerOwnership.objects.filter(
            tower_id__in=[self.tower_a.id, self.tower_b.id], timestamp_end__isnull=True,
        )
        self.assertTrue(open_ownerships.exists())
        for ownership in open_ownerships:
            self.assertEqual(ownership.team.session_id, run.session_id)

        self.assertTrue(TeamTowerChallenge.objects.filter(team__session=run.session).exists())

        capture_event = capture_events.first()
        self.assertIn(capture_event.payload['tower_id'], [self.tower_a.id, self.tower_b.id])
        self.assertIn('ttc_id', capture_event.outcome)


class DementorsTest(SimulatorDriverTestCase):
    def test_dementors_mode_drains_wizard_energy(self):
        run = self._run(dementors_enabled=True, capture_probability=0.0, radius_m=10)
        driver = SimulationDriver(run)
        driver.setup()

        self.assertTrue(run.session.effective('dementors_enabled'))
        states = list(DementorState.objects.filter(session=run.session))
        self.assertEqual(len(states), 6)
        wizards_before = [s for s in states if s.role == DementorState.WIZARD]
        self.assertGreaterEqual(len(wizards_before), 1)
        total_before = sum(s.energy for s in wizards_before)

        driver.play(2)

        total_after = DementorState.objects.filter(
            session=run.session, role=DementorState.WIZARD,
        ).aggregate(total=Sum('energy'))['total'] or 0.0
        self.assertLess(total_after, total_before)

        self.assertTrue(ProximityReport.objects.filter(session=run.session).exists())
        self.assertTrue(
            SimulationEvent.objects.filter(run=run, action=SimulationEvent.PROXIMITY).exists(),
        )


class TeardownTest(SimulatorDriverTestCase):
    def test_teardown_deletes_everything_and_spares_the_template(self):
        run = self._run(dementors_enabled=True, capture_probability=1.0)
        driver = SimulationDriver(run)
        driver.setup()
        driver.play(3)

        run_id = run.id
        game_id = run.game_id
        session_id = run.session_id
        profile_ids = list(SimulatedPlayer.objects.filter(run=run).values_list('profile_id', flat=True))
        user_ids = list(
            UserProfile.objects.filter(pk__in=profile_ids).values_list('user_id', flat=True),
        )
        self.assertEqual(len(user_ids), 6)

        driver.teardown()

        self.assertFalse(SimulationRun.objects.filter(pk=run_id).exists())
        self.assertFalse(SimulationEvent.objects.filter(run_id=run_id).exists())
        self.assertFalse(SimulatedPlayer.objects.filter(run_id=run_id).exists())
        self.assertFalse(Game.objects.filter(pk=game_id).exists())
        self.assertFalse(Session.objects.filter(pk=session_id).exists())
        self.assertFalse(Team.objects.filter(session_id=session_id).exists())
        self.assertFalse(TeamMembership.objects.filter(game_id=game_id).exists())
        self.assertFalse(User.objects.filter(pk__in=user_ids).exists())
        self.assertFalse(UserProfile.objects.filter(pk__in=profile_ids).exists())
        self.assertFalse(LocationPing.objects.filter(session_id=session_id).exists())
        self.assertFalse(LocationConsent.objects.filter(session_id=session_id).exists())
        self.assertFalse(ProximityReport.objects.filter(session_id=session_id).exists())
        self.assertFalse(ProximityIdentity.objects.filter(session_id=session_id).exists())
        self.assertFalse(DementorState.objects.filter(session_id=session_id).exists())
        self.assertFalse(TeamTowerOwnership.objects.filter(team__session_id=session_id).exists())
        self.assertFalse(TeamTowerChallenge.objects.filter(team__session_id=session_id).exists())

        # The reusable template + its geometry are completely untouched.
        self.assertTrue(Game.objects.filter(pk=self.game.id).exists())
        self.assertTrue(Tower.objects.filter(pk=self.tower_a.id).exists())
        self.assertTrue(Tower.objects.filter(pk=self.tower_b.id).exists())
        self.assertTrue(Zone.objects.filter(pk=self.zone.id).exists())

    def test_teardown_without_captures_is_still_complete(self):
        run = self._run(capture_probability=0.0)
        driver = SimulationDriver(run)
        driver.setup()
        session_id = run.session_id
        driver.teardown()
        self.assertFalse(SimulationRun.objects.filter(pk=run.id).exists())
        self.assertFalse(Session.objects.filter(pk=session_id).exists())


class SimulatorApiTest(SimulatorDriverTestCase):
    def setUp(self):
        super().setUp()
        self.staff = _staff_user('staff1')
        self.player = User.objects.create_user(username='player1', password='pw', is_staff=False)
        self.client = APIClient()

    def _create_payload(self):
        return {
            'name': 'API test run',
            'seed': 7,
            'template_game_id': self.game.id,
            'n_players': 6,
            'n_teams': 2,
            'dementors_enabled': False,
            'tick_seconds': 5,
            'capture_probability': 1.0,
            'center_lat': 46.068374,
            'center_lng': 23.571797,
            'radius_m': 15,
        }

    def test_full_staff_flow(self):
        self.client.force_authenticate(self.staff)

        resp = self.client.post('/api/staff/simulator/runs/', self._create_payload(), format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        run_id = resp.data['id']
        self.assertEqual(resp.data['status'], SimulationRun.RUNNING)
        self.assertIsNotNone(resp.data['session'])
        self.assertIsNotNone(resp.data['game'])

        resp = self.client.get('/api/staff/simulator/runs/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)

        resp = self.client.get(f'/api/staff/simulator/runs/{run_id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('players', resp.data['state'])
        self.assertEqual(len(resp.data['state']['players']), 6)

        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/step/', {'ticks': 2}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['tick_count'], 2)

        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/play/', {'ticks': 2}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['tick_count'], 4)

        resp = self.client.get(f'/api/staff/simulator/runs/{run_id}/timeline/')
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.data), 0)
        self.assertTrue(any(e['action'] == 'CAPTURE' for e in resp.data))

        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/pause/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], SimulationRun.PAUSED)

        # Stepping a paused run is rejected...
        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/step/')
        self.assertEqual(resp.status_code, 409)

        # ...but `finish` is a legal transition from PAUSED too (closes
        # ownerships, keeps history) — mirrors Session.TRANSITIONS.
        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/stop/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], SimulationRun.FINISHED)

    def test_stop_from_running_and_delete(self):
        self.client.force_authenticate(self.staff)
        resp = self.client.post('/api/staff/simulator/runs/', self._create_payload(), format='json')
        run_id = resp.data['id']

        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/stop/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], SimulationRun.FINISHED)

        resp = self.client.delete(f'/api/staff/simulator/runs/{run_id}/')
        self.assertEqual(resp.status_code, 204)

        resp = self.client.get(f'/api/staff/simulator/runs/{run_id}/')
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(SimulationRun.objects.filter(pk=run_id).exists())

    def test_create_rejects_bad_seed(self):
        self.client.force_authenticate(self.staff)
        payload = self._create_payload()
        payload['seed'] = 'not-an-int'
        resp = self.client.post('/api/staff/simulator/runs/', payload, format='json')
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(SimulationRun.objects.exists())

    def test_create_with_bad_template_cleans_up_the_failed_run(self):
        self.client.force_authenticate(self.staff)
        payload = self._create_payload()
        payload['template_game_id'] = 999999  # does not exist
        resp = self.client.post('/api/staff/simulator/runs/', payload, format='json')
        self.assertEqual(resp.status_code, 400)
        # setup() raised mid-way — no half-built run left behind.
        self.assertFalse(SimulationRun.objects.exists())

    def test_play_and_pause_and_stop_conflicts(self):
        self.client.force_authenticate(self.staff)
        resp = self.client.post('/api/staff/simulator/runs/', self._create_payload(), format='json')
        run_id = resp.data['id']

        # play() on a paused run is rejected the same way step() is.
        self.client.post(f'/api/staff/simulator/runs/{run_id}/pause/')
        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/play/', {'ticks': 1}, format='json')
        self.assertEqual(resp.status_code, 409)

        # pause() a second time (PAUSED -> PAUSED is not a legal edge).
        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/pause/')
        self.assertEqual(resp.status_code, 409)

        # finish, then finish again (FINISHED -> FINISHED is not legal).
        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/stop/')
        self.assertEqual(resp.status_code, 200)
        resp = self.client.post(f'/api/staff/simulator/runs/{run_id}/stop/')
        self.assertEqual(resp.status_code, 409)

    def test_non_staff_forbidden(self):
        self.client.force_authenticate(self.player)
        resp = self.client.post('/api/staff/simulator/runs/', self._create_payload(), format='json')
        self.assertEqual(resp.status_code, 403)

        resp = self.client.get('/api/staff/simulator/runs/')
        self.assertEqual(resp.status_code, 403)

    def test_anonymous_forbidden(self):
        resp = self.client.get('/api/staff/simulator/runs/')
        self.assertEqual(resp.status_code, 403)
