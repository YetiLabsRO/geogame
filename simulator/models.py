"""Game simulator: staff-driven fake-game runner (game-simulator-backend).

A `SimulationRun` spins up a REAL Game/Session/roster/teams and drives
them through the SAME domain code paths the live API views use —
`LocationPing` + discovery, `ProximityReport` + `game.dementors.run_tick`,
`TeamTowerChallenge` capture, `Session.transition` lifecycle — via
`simulator.driver.SimulationDriver`. Every action taken is recorded as an
append-only `SimulationEvent` so a run can be scrubbed/replayed.

Non-invasive by design: nothing here adds fields to the core `game` /
`organize` models. Sim-created rows in those apps are tracked ONLY
through the FKs on these models (`SimulationRun.game` / `.session`,
`SimulatedPlayer.profile`) plus a "[SIM]" name prefix on the Game and
Session it creates — see `simulator.driver.SimulationDriver.teardown`.
"""
from django.conf import settings
from django.db import models


class SimulationRun(models.Model):
    """One fake-game run: its config, its real Game/Session, and its clock."""

    DRAFT = 'DRAFT'
    RUNNING = 'RUNNING'
    PAUSED = 'PAUSED'
    FINISHED = 'FINISHED'
    STATUS_CHOICES = [
        (DRAFT, 'Draft — not yet set up'),
        (RUNNING, 'Running'),
        (PAUSED, 'Paused'),
        (FINISHED, 'Finished'),
    ]

    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='simulation_runs',
    )
    # The REAL Game/Session this run drives. Set by
    # `SimulationDriver.setup()`; null before setup (or after teardown,
    # for an instant before the row itself is deleted).
    game = models.ForeignKey(
        'organize.Game',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='simulation_runs',
    )
    session = models.ForeignKey(
        'organize.Session',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='simulation_runs',
    )
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=DRAFT)
    # Seeds every `random.Random` draw the driver makes (team shuffling,
    # movement jitter, capture rolls) — same seed ⇒ same replay.
    seed = models.BigIntegerField(default=0)
    # Free-form run configuration: n_players, n_teams, mode,
    # dementors_enabled, tick_seconds, behavior knobs, map center/radius,
    # optionally template_game_id to clone. See simulator.driver for the
    # recognized keys and their defaults.
    config = models.JSONField(default=dict, blank=True)
    tick_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'SimulationRun({self.name}, {self.status})'


class SimulatedPlayer(models.Model):
    """One fake roster member driven by a SimulationRun.

    `profile` is a REAL `organize.UserProfile` (backed by a REAL, but
    sim-only, `auth.User`) so it flows through every domain code path
    unmodified. Position + a small behavior scratchpad live here so the
    driver's movement model is stateless between requests.
    """

    run = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name='players')
    profile = models.ForeignKey(
        'organize.UserProfile', on_delete=models.CASCADE, related_name='+',
    )
    team = models.ForeignKey(
        'organize.Team', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    # Free-text role label — mirrors the effective DementorState.role in
    # dementors-mode runs (kept in sync by the driver each tick); blank
    # in plain domination-mode runs.
    role = models.CharField(max_length=32, blank=True, default='')
    lat = models.FloatField(default=0.0)
    lng = models.FloatField(default=0.0)
    # Small behavior scratchpad (e.g. current movement target) — never
    # consumed by the real game engine, purely a driver bookkeeping aid.
    state = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['run_id', 'id']

    def __str__(self):
        return f'SimulatedPlayer(run={self.run_id}, profile={self.profile_id})'


class SimulationEvent(models.Model):
    """One entry in a run's append-only replay tape."""

    SPAWN = 'SPAWN'
    MOVE = 'MOVE'
    PROXIMITY = 'PROXIMITY'
    CAPTURE = 'CAPTURE'
    TRANSITION = 'TRANSITION'
    TICK = 'TICK'
    ACTION_CHOICES = [
        (SPAWN, 'Spawn'),
        (MOVE, 'Move'),
        (PROXIMITY, 'Proximity / dementors tick'),
        (CAPTURE, 'Tower capture'),
        (TRANSITION, 'Session lifecycle transition'),
        (TICK, 'Tick boundary'),
    ]

    run = models.ForeignKey(SimulationRun, on_delete=models.CASCADE, related_name='events')
    tick = models.PositiveIntegerField(default=0)
    ts = models.DateTimeField(auto_now_add=True)
    # The simulated player (real auth.User) that performed the action;
    # null for system-level events (setup, lifecycle transitions).
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    payload = models.JSONField(default=dict, blank=True)
    outcome = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ['run_id', 'tick', 'id']
        indexes = [
            models.Index(fields=['run', 'tick']),
        ]

    def __str__(self):
        return f'SimulationEvent(run={self.run_id}, tick={self.tick}, {self.action})'
