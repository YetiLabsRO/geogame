"""SimulationDriver: live-drives a fake game through the REAL engine.

Every action a `SimulationDriver` takes calls the SAME domain
services/models the live API views call — no HTTP self-calls, no
shadow/parallel implementation of game rules:

  * setup()    — Game (new or cloned template), Session, fake users +
                 UserProfiles, teams (via the shuffle/balance team-build
                 helper), LocationConsent, ProximityIdentity, then
                 `Session.transition('open_participation')` + `'start'`
                 (which seeds dementor roles itself when enabled).
  * step()     — one tick: move every player (LocationPing + real
                 `game.discovery.evaluate_discovery`), in dementors mode
                 derive proximity + tick the economy (`ProximityReport` +
                 `game.dementors.run_tick`), then probabilistic captures
                 (`TeamTowerChallenge` CONFIRMED + `Tower.assign_to_team`).
  * pause()/stop() — `Session.transition('pause'/'finish')`.
  * teardown() — delete every sim-created row (users cascade their
                 profiles; the Game cascades its Session and everything
                 session/team-scoped — see the teardown docstring for the
                 exact chain).

Every action is recorded as a `SimulationEvent` for replay/scrub. RNG is
a local `random.Random` seeded from `run.seed` (and the tick index, so
consecutive ticks are not carbon copies of each other) — deterministic,
reproducible, and never shared mutable state between requests (a fresh
`SimulationDriver` is constructed per API call).
"""
import math
import random
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance as DistanceMeasure
from django.db import transaction
from django.utils import timezone

from game.admin_api import AdminSessionViewSet
from game.dementors import run_tick as dementors_run_tick
from game.discovery import evaluate_discovery
from game.models import (
    PROXIMITY_SOURCE_PHONE,
    DementorState,
    LocationConsent,
    LocationPing,
    ProximityIdentity,
    ProximityReport,
    TeamTowerChallenge,
    TeamTowerOwnership,
    Tower,
    effective_proximity,
)
from organize.models import Game, Session, TeamMembership, UserProfile
from simulator.models import SimulatedPlayer, SimulationEvent, SimulationRun

# Cluj-Napoca — matches geogame.settings.LEAFLET_CONFIG['DEFAULT_CENTER'];
# used only when a run supplies no map center and its Game has none either.
DEFAULT_CENTER = (46.068374, 23.571797)

METERS_PER_DEGREE_LAT = 111_320.0


class SimulationDriver:
    """Drives one `SimulationRun`. Stateless between calls — see module docstring."""

    def __init__(self, run):
        self.run = run

    @property
    def config(self):
        return self.run.config or {}

    # ------------------------------------------------------------------
    # Event tape
    # ------------------------------------------------------------------

    def _record(self, action, *, tick=None, actor=None, payload=None, outcome=None):
        return SimulationEvent.objects.create(
            run=self.run,
            tick=self.run.tick_count if tick is None else tick,
            actor=actor,
            action=action,
            payload=payload or {},
            outcome=outcome or {},
        )

    def _transition(self, session, action):
        session.transition(action, actor=self.run.created_by)
        self._record(
            SimulationEvent.TRANSITION,
            actor=self.run.created_by,
            payload={'action': action},
            outcome={'session_state': session.state},
        )

    # ------------------------------------------------------------------
    # setup()
    # ------------------------------------------------------------------

    def setup(self):
        if self.run.status != SimulationRun.DRAFT:
            raise ValueError(f'Cannot set up a run in status {self.run.status}')

        cfg = dict(self.config)
        n_players = max(1, int(cfg.get('n_players', 6)))
        n_teams = max(1, min(int(cfg.get('n_teams', 2)), n_players))
        dementors_enabled = bool(cfg.get('dementors_enabled', False))

        setup_rng = random.Random(f'{self.run.seed}:setup')

        with transaction.atomic():
            game = self._resolve_game(cfg)
            session = self._create_session(game, cfg)
            self.run.game = game
            self.run.session = session

            center_lat, center_lng = self._center(game, cfg)
            radius_m = float(cfg.get('radius_m', 250))
            # Persist the resolved values so later step() calls (a fresh
            # SimulationDriver instance each time) see the same map.
            cfg.setdefault('center_lat', center_lat)
            cfg.setdefault('center_lng', center_lng)
            cfg.setdefault('radius_m', radius_m)
            cfg.setdefault('tick_seconds', 5)
            cfg.setdefault('step_meters', 12)
            cfg.setdefault('capture_probability', 0.5)
            cfg['dementors_enabled'] = dementors_enabled
            self.run.config = cfg
            self.run.save(update_fields=['game', 'session', 'config'])

            self._record(
                SimulationEvent.SPAWN,
                actor=self.run.created_by,
                payload={'kind': 'game_session', 'game_id': game.id, 'session_id': session.id},
            )

            # Live-location + dementors knobs (live-location /
            # mode-dementors capabilities): Session overrides only —
            # never touches the (possibly shared/cloned) Game template.
            session.location_tracking_enabled = True
            session.dementors_enabled = dementors_enabled
            session.save(update_fields=['location_tracking_enabled', 'dementors_enabled'])

            profiles = self._create_players(session, n_players)
            self._build_teams_and_players(
                session, n_teams, profiles, (center_lat, center_lng), radius_m, setup_rng,
            )

            # session-lifecycle: open the roster window then start —
            # `start` seeds dementor roles itself when the mode is on
            # (organize.models.Session._apply_start).
            self._transition(session, 'open_participation')
            self._transition(session, 'start')

        self.run.status = SimulationRun.RUNNING
        self.run.save(update_fields=['status'])
        return self.run

    def _resolve_game(self, cfg):
        template_id = cfg.get('template_game_id')
        slug = f'sim-{self.run.pk}-{uuid.uuid4().hex[:8]}'
        if template_id:
            template = Game.objects.get(pk=template_id)
            # Same code path AdminGameViewSet.clone uses: deep-copies
            # config/roles/challenge bank, shares Collections/Towers/Zones
            # by PK (never duplicates geometry).
            return template.clone(
                slug, name=f'[SIM] {template.name}', created_by=self.run.created_by,
            )
        name = cfg.get('game_name') or self.run.name or f'Simulation {self.run.pk}'
        return Game.objects.create(
            name=f'[SIM] {name}',
            slug=slug,
            created_by=self.run.created_by,
            proximity_meters=int(cfg.get('proximity_meters', 30)),
        )

    def _create_session(self, game, cfg):
        now = timezone.now()
        duration_minutes = int(cfg.get('duration_minutes', 180))
        slug = f'sim-{self.run.pk}-{uuid.uuid4().hex[:6]}'
        return Session.objects.create(
            game=game,
            slug=slug,
            name=f'[SIM] {self.run.name}'[:255],
            start_time=now,
            end_time=now + timedelta(minutes=duration_minutes),
            created_by=self.run.created_by,
        )

    def _center(self, game, cfg):
        if cfg.get('center_lat') is not None and cfg.get('center_lng') is not None:
            return float(cfg['center_lat']), float(cfg['center_lng'])
        if game.base_point is not None:
            return game.base_point.y, game.base_point.x
        return DEFAULT_CENTER

    def _create_players(self, session, n_players):
        User = get_user_model()
        profiles = []
        for i in range(n_players):
            suffix = uuid.uuid4().hex[:8]
            username = f'sim-{self.run.pk}-{i}-{suffix}'
            user = User.objects.create_user(
                username=username,
                email=f'{username}@sim.invalid',
                password=None,
            )
            profile = user.profile
            profile.current_session = session
            profile.save(update_fields=['current_session'])
            profiles.append(profile)
        return profiles

    def _build_teams_and_players(self, session, n_teams, profiles, center, radius_m, rng):
        """Build N teams (reusing the shuffle-teams build helper) and one
        SimulatedPlayer + real TeamMembership per fake profile."""
        # game-config-team-rules / team-formation: the exact team-row
        # creation helper AdminSessionViewSet.shuffle_teams/balance_teams
        # use — see game/admin_api.py ~L1712-1726. Uses no `self.request`
        # state, so it's safe to call on a bare (un-routed) instance.
        viewset = AdminSessionViewSet()
        teams = viewset._build_teams(session, n_teams)

        order = list(profiles)
        rng.shuffle(order)

        sim_players = []
        for i, profile in enumerate(order):
            team = teams[i % n_teams]
            TeamMembership.objects.create(team=team, user=profile, is_active=True)
            lat, lng = self._random_point_near(center[0], center[1], radius_m, rng)
            sim_player = SimulatedPlayer.objects.create(
                run=self.run, profile=profile, team=team, lat=lat, lng=lng,
            )
            sim_players.append(sim_player)

            LocationConsent.grant(profile.user, session)
            ProximityIdentity.issue(session, profile)

            self._record(
                SimulationEvent.SPAWN,
                actor=profile.user,
                payload={'kind': 'player', 'profile_id': profile.id, 'team_id': team.id},
            )
        return teams, sim_players

    # ------------------------------------------------------------------
    # step() — one tick
    # ------------------------------------------------------------------

    def step(self, now=None):
        run = self.run
        if run.status != SimulationRun.RUNNING:
            raise ValueError(f'Cannot step a run in status {run.status}')
        session = run.session
        if session is None:
            raise ValueError('Run has no session; call setup() first.')
        session.refresh_from_db()

        cfg = self.config
        tick_seconds = int(cfg.get('tick_seconds', 5))
        step_m = float(cfg.get('step_meters', 12))
        capture_probability = float(cfg.get('capture_probability', 0.5))
        center = (
            float(cfg.get('center_lat', DEFAULT_CENTER[0])),
            float(cfg.get('center_lng', DEFAULT_CENTER[1])),
        )
        radius_m = float(cfg.get('radius_m', 250))
        dementors_enabled = bool(session.effective('dementors_enabled'))

        tick_index = run.tick_count + 1
        rng = random.Random(f'{run.seed}:{tick_index}')
        now = now or timezone.now()

        self._record(SimulationEvent.TICK, tick=tick_index, payload={'tick_seconds': tick_seconds})

        sim_players = list(
            SimulatedPlayer.objects.filter(run=run).select_related('profile__user', 'team'),
        )
        dementor_states = {}
        if dementors_enabled:
            dementor_states = {
                s.player_id: s for s in DementorState.objects.filter(session=session)
            }

        for sim_player in sim_players:
            state = dementor_states.get(sim_player.profile_id)
            if dementors_enabled and state is not None and not state.alive:
                continue  # out of play — no more movement/pings this tick
            self._move_one(
                session, sim_player, sim_players, dementors_enabled, dementor_states,
                center, radius_m, step_m, tick_index, now, rng,
            )

        if dementors_enabled:
            self._run_proximity_tick(session, sim_players, tick_index, tick_seconds)

        self._attempt_captures(session, sim_players, tick_index, capture_probability, rng)

        run.tick_count = tick_index
        run.save(update_fields=['tick_count'])
        return self.state()

    def play(self, ticks=1):
        results = []
        for _ in range(max(1, int(ticks))):
            results.append(self.step())
        return results

    def pause(self):
        session = self.run.session
        session.transition('pause', actor=self.run.created_by)
        self._record(SimulationEvent.TRANSITION, payload={'action': 'pause'})
        self.run.status = SimulationRun.PAUSED
        self.run.save(update_fields=['status'])
        return self.run

    def resume(self):
        session = self.run.session
        session.transition('resume', actor=self.run.created_by)
        self._record(SimulationEvent.TRANSITION, payload={'action': 'resume'})
        self.run.status = SimulationRun.RUNNING
        self.run.save(update_fields=['status'])
        return self.run

    def stop(self):
        session = self.run.session
        session.transition('finish', actor=self.run.created_by)
        self._record(SimulationEvent.TRANSITION, payload={'action': 'finish'})
        self.run.status = SimulationRun.FINISHED
        self.run.save(update_fields=['status'])
        return self.run

    # ------------------------------------------------------------------
    # Movement
    # ------------------------------------------------------------------

    def _move_one(self, session, sim_player, sim_players, dementors_enabled,
                   dementor_states, center, radius_m, step_m, tick_index, now, rng):
        target = self._pick_target(
            session, sim_player, sim_players, dementors_enabled, dementor_states,
        )
        if target is not None:
            target_lat, target_lng, towards, meta = target
            new_lat, new_lng = self._move_towards(
                sim_player, target_lat, target_lng, step_m, towards, rng,
            )
        else:
            new_lat, new_lng = self._wander(sim_player, step_m, rng)
            meta = {}
        new_lat, new_lng = self._clamp(new_lat, new_lng, center, radius_m)

        old_lat, old_lng = sim_player.lat, sim_player.lng
        sim_player.lat, sim_player.lng = new_lat, new_lng
        sim_player.state = meta
        sim_player.save(update_fields=['lat', 'lng', 'state'])

        point = Point(new_lng, new_lat, srid=4326)
        LocationPing.objects.create(
            user=sim_player.profile.user,
            session=session,
            team=sim_player.team,
            point=point,
            recorded_at=now,
        )
        revealed = []
        if sim_player.team is not None:
            revealed = evaluate_discovery(session, sim_player.team, point, user=sim_player.profile.user)
        self._record(
            SimulationEvent.MOVE,
            tick=tick_index,
            actor=sim_player.profile.user,
            payload={'from': [old_lat, old_lng], 'to': [new_lat, new_lng]},
            outcome={'revealed_towers': [d.tower_id for d in revealed]},
        )

    def _pick_target(self, session, sim_player, sim_players, dementors_enabled, dementor_states):
        if dementors_enabled:
            state = dementor_states.get(sim_player.profile_id)
            role = state.role if state else None
            if role == DementorState.DEMENTOR:
                wizards = [
                    other for other in sim_players
                    if other.pk != sim_player.pk
                    and _alive_role(dementor_states, other.profile_id) == DementorState.WIZARD
                ]
                nearest = self._nearest_player(sim_player, wizards)
                if nearest is None:
                    return None
                return (nearest.lat, nearest.lng, True, {'chasing': nearest.profile_id})
            if role == DementorState.WIZARD:
                dementors = [
                    other for other in sim_players
                    if other.pk != sim_player.pk
                    and _alive_role(dementor_states, other.profile_id) == DementorState.DEMENTOR
                ]
                nearest = self._nearest_player(sim_player, dementors)
                if nearest is None:
                    return None
                return (nearest.lat, nearest.lng, False, {'fleeing': nearest.profile_id})
            return None

        # Domination mode: head for the nearest tower this player's team
        # doesn't already hold.
        if sim_player.team is None:
            return None
        towers = list(session.towers().filter(is_active=True))
        if not towers:
            return None
        candidates = [t for t in towers if t.tower_control(sim_player.team.group) != sim_player.team]
        pool = candidates or towers
        nearest = self._nearest_tower(sim_player, pool)
        if nearest is None:
            return None
        return (nearest.location.y, nearest.location.x, True, {'target_tower_id': nearest.id})

    def _nearest_player(self, sim_player, others):
        best, best_dist = None, None
        for other in others:
            dx, dy = self._meters_offset(sim_player.lat, sim_player.lng, other.lat, other.lng)
            dist = math.hypot(dx, dy)
            if best_dist is None or dist < best_dist:
                best, best_dist = other, dist
        return best

    def _nearest_tower(self, sim_player, towers):
        best, best_dist = None, None
        for tower in towers:
            dx, dy = self._meters_offset(
                sim_player.lat, sim_player.lng, tower.location.y, tower.location.x,
            )
            dist = math.hypot(dx, dy)
            if best_dist is None or dist < best_dist:
                best, best_dist = tower, dist
        return best

    def _move_towards(self, sim_player, target_lat, target_lng, step_m, towards, rng):
        dx, dy = self._meters_offset(sim_player.lat, sim_player.lng, target_lat, target_lng)
        dist = math.hypot(dx, dy)
        if dist < 1e-6:
            angle = rng.uniform(0, 2 * math.pi)
            ux, uy = math.cos(angle), math.sin(angle)
        else:
            ux, uy = dx / dist, dy / dist
        if not towards:
            ux, uy = -ux, -uy
        move = min(step_m, dist) if (towards and dist > 0) else step_m
        jitter_x = rng.uniform(-step_m * 0.25, step_m * 0.25)
        jitter_y = rng.uniform(-step_m * 0.25, step_m * 0.25)
        return self._offset_point(sim_player.lat, sim_player.lng, ux * move + jitter_x, uy * move + jitter_y)

    def _wander(self, sim_player, step_m, rng):
        angle = rng.uniform(0, 2 * math.pi)
        magnitude = step_m * rng.uniform(0.3, 1.0)
        return self._offset_point(
            sim_player.lat, sim_player.lng, math.cos(angle) * magnitude, math.sin(angle) * magnitude,
        )

    def _clamp(self, lat, lng, center, radius_m):
        dx, dy = self._meters_offset(center[0], center[1], lat, lng)
        dist = math.hypot(dx, dy)
        if dist <= radius_m or dist == 0:
            return lat, lng
        scale = radius_m / dist
        return self._offset_point(center[0], center[1], dx * scale, dy * scale)

    def _random_point_near(self, lat, lng, radius_m, rng):
        angle = rng.uniform(0, 2 * math.pi)
        dist = rng.uniform(0, radius_m)
        dx, dy = math.cos(angle) * dist, math.sin(angle) * dist
        return self._offset_point(lat, lng, dx, dy)

    @staticmethod
    def _meters_offset(from_lat, from_lng, to_lat, to_lng):
        """Approximate (dx, dy) meters from one lat/lng to another (flat-earth, fine at this scale)."""
        dy = (to_lat - from_lat) * METERS_PER_DEGREE_LAT
        dx = (to_lng - from_lng) * METERS_PER_DEGREE_LAT * math.cos(math.radians(from_lat))
        return dx, dy

    @staticmethod
    def _offset_point(lat, lng, dx, dy):
        """Apply a (dx, dy) meter offset to a lat/lng."""
        new_lat = lat + dy / METERS_PER_DEGREE_LAT
        denom = METERS_PER_DEGREE_LAT * math.cos(math.radians(lat))
        if abs(denom) < 1e-9:
            denom = 1e-9
        new_lng = lng + dx / denom
        return new_lat, new_lng

    # ------------------------------------------------------------------
    # Proximity / dementors economy
    # ------------------------------------------------------------------

    def _run_proximity_tick(self, session, sim_players, tick_index, tick_seconds):
        now = timezone.now()
        # Backdate the economy's bookkeeping clock by exactly one tick's
        # worth of simulated time, so `game.dementors.economy_tick`'s
        # elapsed-time drain/regen reflects `tick_seconds` of game time
        # regardless of how fast wall-clock calls actually arrive.
        DementorState.objects.filter(session=session, alive=True).update(
            last_tick_at=now - timedelta(seconds=tick_seconds),
        )

        very_close_m = float(self.config.get('ble_very_close_m', 10))
        near_m = float(self.config.get('ble_near_m', 40))

        identities = {}
        for sim_player in sim_players:
            identity = ProximityIdentity.current_for(session, sim_player.profile)
            if identity is None:
                identity = ProximityIdentity.issue(session, sim_player.profile)
            identities[sim_player.profile_id] = identity

        pair_summary = []
        for sim_player in sim_players:
            observations = []
            for other in sim_players:
                if other.pk == sim_player.pk:
                    continue
                dx, dy = self._meters_offset(sim_player.lat, sim_player.lng, other.lat, other.lng)
                dist = math.hypot(dx, dy)
                if dist <= very_close_m:
                    rssi = -50
                elif dist <= near_m:
                    rssi = -70
                else:
                    continue
                observations.append({'token': identities[other.profile_id].token, 'rssi': rssi})
                if sim_player.pk < other.pk:
                    pair_summary.append({
                        'a': sim_player.profile_id, 'b': other.profile_id, 'meters': round(dist, 1),
                    })
            ProximityReport.objects.create(
                session=session,
                reporter=identities[sim_player.profile_id],
                player=sim_player.profile,
                observations=observations,
                source=PROXIMITY_SOURCE_PHONE,
                reported_at=now,
            )

        events = dementors_run_tick(session, now=now)

        states = {s.player_id: s for s in DementorState.objects.filter(session=session)}
        for sim_player in sim_players:
            state = states.get(sim_player.profile_id)
            if state is not None and state.role != sim_player.role:
                sim_player.role = state.role
                sim_player.save(update_fields=['role'])

        self._record(
            SimulationEvent.PROXIMITY,
            tick=tick_index,
            payload={'pairs': pair_summary},
            outcome={
                'derived_events': len(events),
                'roles': {str(pid): s.role for pid, s in states.items()},
                'energy': {str(pid): round(s.energy, 2) for pid, s in states.items()},
            },
        )

    # ------------------------------------------------------------------
    # Captures
    # ------------------------------------------------------------------

    def _attempt_captures(self, session, sim_players, tick_index, capture_probability, rng):
        teams_by_id = {}
        for sim_player in sim_players:
            if sim_player.team_id:
                teams_by_id.setdefault(
                    sim_player.team_id, {'team': sim_player.team, 'members': []},
                )['members'].append(sim_player)

        towers = list(session.towers().filter(is_active=True))
        if not towers:
            return
        game = session.game

        for entry in teams_by_id.values():
            team = entry['team']
            for tower in towers:
                if tower.tower_control(team.group) == team:
                    continue
                radius = effective_proximity(tower, game)
                in_range = any(
                    Tower.objects.filter(
                        pk=tower.pk,
                        location__distance_lte=(
                            Point(member.lng, member.lat, srid=4326), DistanceMeasure(m=radius),
                        ),
                    ).exists()
                    for member in entry['members']
                )
                if not in_range:
                    continue
                if tower.team_in_cooloff(team):
                    continue
                if rng.random() > capture_probability:
                    continue

                challenge = tower.get_next_challenge(team)
                actor_user = entry['members'][0].profile.user
                ttc = TeamTowerChallenge.objects.create(
                    team=team,
                    tower=tower,
                    challenge=challenge,
                    outcome=TeamTowerChallenge.CONFIRMED,
                    submitted_by=actor_user,
                )
                # Mirrors game.views.TeamTowerChallengeViewSet.perform_create:
                # an already-CONFIRMED insert does not itself trigger
                # capture (see TeamTowerChallenge.save's __original_outcome
                # guard) — the caller applies it explicitly, same as here.
                tower.assign_to_team(team, challenge=challenge)
                self._record(
                    SimulationEvent.CAPTURE,
                    tick=tick_index,
                    actor=actor_user,
                    payload={'tower_id': tower.id, 'team_id': team.id},
                    outcome={'ttc_id': ttc.id, 'tower_name': tower.name, 'team_name': team.name},
                )

    # ------------------------------------------------------------------
    # state() / teardown()
    # ------------------------------------------------------------------

    def state(self):
        run = self.run
        session = run.session
        players_payload = []
        dementor_map = {}
        if session is not None and session.effective('dementors_enabled'):
            dementor_map = {s.player_id: s for s in DementorState.objects.filter(session=session)}

        for sim_player in SimulatedPlayer.objects.filter(run=run).select_related('profile__user', 'team'):
            state_row = dementor_map.get(sim_player.profile_id)
            players_payload.append({
                'id': sim_player.id,
                'profile_id': sim_player.profile_id,
                'username': sim_player.profile.user.username,
                'team_id': sim_player.team_id,
                'team_name': sim_player.team.name if sim_player.team else None,
                'lat': sim_player.lat,
                'lng': sim_player.lng,
                'role': state_row.role if state_row else sim_player.role,
                'energy': round(state_row.energy, 2) if state_row else None,
                'alive': state_row.alive if state_row else True,
            })

        scoreboard = []
        towers_payload = []
        if session is not None:
            for team in session.teams.all():
                scoreboard.append({
                    'team_id': team.id, 'name': team.name, 'score': team.current_score(),
                })
            for tower in session.towers().filter(is_active=True):
                ownership = (
                    TeamTowerOwnership.objects
                    .filter(tower=tower, timestamp_end__isnull=True)
                    .select_related('team')
                    .first()
                )
                towers_payload.append({
                    'id': tower.id,
                    'name': tower.name,
                    'owner_team_id': ownership.team_id if ownership else None,
                    'owner_team_name': ownership.team.name if ownership else None,
                })

        return {
            'run_id': run.id,
            'status': run.status,
            'tick_count': run.tick_count,
            'session_state': session.state if session else None,
            'players': players_payload,
            'scoreboard': scoreboard,
            'towers': towers_payload,
        }

    def teardown(self):
        """Delete every sim-created row: session/game cascades own the
        vast majority (Team, TeamMembership, LocationPing/Consent,
        ProximityIdentity/Report/Event, DementorState/Flip,
        TeamTowerOwnership/Challenge, TowerDiscovery, ...); the fake
        Users are deleted explicitly (cascades their UserProfile, which
        cascades this run's SimulatedPlayer rows); the run itself goes
        last (cascades its SimulationEvent tape).
        """
        run = self.run
        User = get_user_model()

        profile_ids = list(
            SimulatedPlayer.objects.filter(run=run).values_list('profile_id', flat=True),
        )
        user_ids = list(
            UserProfile.objects.filter(pk__in=profile_ids).values_list('user_id', flat=True),
        )

        with transaction.atomic():
            if run.game_id:
                Game.objects.filter(pk=run.game_id).delete()
            elif run.session_id:
                Session.objects.filter(pk=run.session_id).delete()
            User.objects.filter(pk__in=user_ids).delete()
            run.delete()


def _alive_role(dementor_states, profile_id):
    state = dementor_states.get(profile_id)
    if state is None or not state.alive:
        return None
    return state.role
