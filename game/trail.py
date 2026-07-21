"""Trail-mode progression engine (mode-trail-discovery).

Pure service layer over the trail models: party resolution, initial
reveal seeding, next-step computation, the submission hooks that mark
ARRIVED / UNLOCKED, and the completion-and-time ranking. Domination
scoring is never touched here — in TRAIL mode the submission pipeline
routes captures to these hooks INSTEAD of tower/zone ownership.

Reveal note: per-team map masking is implemented via
`revealed_tower_ids()` (consumed by the player tower listing) because
the `tower-visibility` capability is not present in this integration
state; when it ships, that function is the seam to delegate through.
"""
from django.db import transaction

from game.models import (
    KNOWLEDGE_ALL_KNOWN,
    KNOWLEDGE_NONE_KNOWN,
    KNOWLEDGE_ONE_KNOWN,
    PARTICIPATION_SOLO,
    STRUCTURE_GRAPH,
    TeamTrailProgress,
    TeamTrailRoute,
    Trail,
)
from organize.models import MODE_TRAIL, effective_mode


def trail_for_session(session):
    """The Session's Trail when its effective mode is TRAIL, else None."""
    if session is None or effective_mode(session) != MODE_TRAIL:
        return None
    return Trail.objects.filter(game=session.game).first()


def party_kwargs(trail, *, team=None, profile=None):
    """The (team / player) filter binding progress rows to one party.

    TEAM participation binds to the team (a member's action counts for
    the whole team); SOLO binds to the individual player's profile.
    """
    if trail.participation == PARTICIPATION_SOLO:
        return {'player': profile, 'team': None}
    return {'team': team, 'player': None}


def route_for(session, trail, *, team=None, profile=None):
    return TeamTrailRoute.objects.filter(
        session=session, **party_kwargs(trail, team=team, profile=profile),
    ).select_related('start_step__trail').first()


def _progress_map(session, party):
    rows = TeamTrailProgress.objects.filter(
        session=session, **party,
    ).select_related('step')
    return {row.step_id: row for row in rows}


def _reveal(session, party, step, when=None):
    row, _created = TeamTrailProgress.objects.get_or_create(
        session=session, step=step, **party,
        defaults={'state': TeamTrailProgress.REVEALED},
    )
    row.advance(TeamTrailProgress.REVEALED, when=when)
    return row


def seed_initial_reveal(session, trail, route):
    """Seed the party's initial reveal from the trail's starting knowledge.

    ALL_KNOWN reveals every step, ONE_KNOWN only the party's start,
    NONE_KNOWN nothing (the start must be discovered on the ground —
    the geofence + gate with no prior reveal). Idempotent.
    """
    party = {'team': route.team, 'player': route.player}
    if trail.starting_knowledge == KNOWLEDGE_NONE_KNOWN:
        return
    if trail.starting_knowledge == KNOWLEDGE_ONE_KNOWN:
        _reveal(session, party, route.start_step)
        return
    if trail.starting_knowledge == KNOWLEDGE_ALL_KNOWN:
        for step in trail.steps.all():
            _reveal(session, party, step)


def reveal_start(session, trail, route):
    """Staff override: reveal a stuck NONE_KNOWN party's start step."""
    party = {'team': route.team, 'player': route.player}
    return _reveal(session, party, route.start_step)


def next_steps(session, trail, route, progress=None):
    """The step(s) the party may unlock next, in order.

    FIXED_ORDER / CIRCUIT: the single first step of the party's
    sequence not yet UNLOCKED. GRAPH: the start step until it is
    unlocked, then every outgoing-edge target of the most recently
    unlocked step that is not itself unlocked (two or more = a branch
    the party chooses from).
    """
    if route is None:
        return []
    if progress is None:
        progress = _progress_map(session, {'team': route.team, 'player': route.player})
    unlocked = {
        step_id for step_id, row in progress.items()
        if row.state == TeamTrailProgress.UNLOCKED
    }

    sequence = route.sequence()
    if sequence is not None:
        for step in sequence:
            if step.id not in unlocked:
                return [step]
        return []

    # GRAPH: follow the unlock trail through edge choices.
    if route.start_step_id not in unlocked:
        return [route.start_step]
    last = (
        TeamTrailProgress.objects
        .filter(
            session=session, state=TeamTrailProgress.UNLOCKED,
            step__trail=trail,
            **{'team': route.team, 'player': route.player},
        )
        .order_by('-unlocked_at', '-id')
        .select_related('step')
        .first()
    )
    if last is None or last.step.is_finish:
        return []
    return [
        edge.to_step
        for edge in last.step.outgoing_edges.select_related('to_step').order_by('id')
        if edge.to_step_id not in unlocked
    ]


def clue_for(trail, from_step, to_step):
    """The clue pointing from `from_step` toward `to_step`.

    GRAPH branch clues live on the edge; linear structures carry the
    clue on the target step itself.
    """
    if trail.structure == STRUCTURE_GRAPH and from_step is not None:
        edge = from_step.outgoing_edges.filter(to_step=to_step).first()
        if edge is not None and edge.clue:
            return edge.clue
    return to_step.clue_text


def is_finished(trail, route, unlocked_ids):
    """Whether the party has completed its run."""
    sequence = route.sequence()
    if sequence is not None:
        return bool(sequence) and all(step.id in unlocked_ids for step in sequence)
    return trail.steps.filter(is_finish=True, id__in=unlocked_ids).exists()


def _step_for_submission(session, trail, route, tower, progress):
    """The next-step row this submission's tower corresponds to, or None.

    Progression is strictly structural: a submission at a tower that is
    not one of the party's current next steps advances nothing, even
    when the point is already visible (ALL_KNOWN).
    """
    for step in next_steps(session, trail, route, progress=progress):
        if step.tower_id == tower.id:
            return step
    return None


@transaction.atomic
def on_submission_created(ttc):
    """Arrival hook: a proximity-validated submission landed at a tower.

    Marks the matching next step ARRIVED for the party; when the step
    has a read-only gate (no gate_challenge) the arrival itself unlocks
    it (the confirmed hook completes the rest).
    """
    session = ttc.team.session
    trail = trail_for_session(session)
    if trail is None:
        return None
    profile = ttc.submitted_by.profile if ttc.submitted_by_id else None
    route = route_for(session, trail, team=ttc.team, profile=profile)
    if route is None:
        return None
    party = {'team': route.team, 'player': route.player}
    progress = _progress_map(session, party)
    step = _step_for_submission(session, trail, route, ttc.tower, progress)
    if step is None:
        return None
    row = progress.get(step.id)
    if row is None:
        row = TeamTrailProgress(session=session, step=step, **party)
    row.advance(TeamTrailProgress.ARRIVED)
    return step


@transaction.atomic
def on_submission_confirmed(ttc):
    """Unlock hook: the submission's gate resolved CONFIRMED.

    Unlocks the matching next step when the confirmed challenge is that
    step's gate (or the step is read-only), reveals the following
    step(s) + clue(s) to this party only, and records the finish time
    when the run completes.
    """
    session = ttc.team.session
    trail = trail_for_session(session)
    if trail is None:
        return None
    profile = ttc.submitted_by.profile if ttc.submitted_by_id else None
    route = route_for(session, trail, team=ttc.team, profile=profile)
    if route is None:
        return None
    party = {'team': route.team, 'player': route.player}
    progress = _progress_map(session, party)
    step = _step_for_submission(session, trail, route, ttc.tower, progress)
    if step is None:
        return None
    if step.gate_challenge_id is not None and ttc.challenge_id != step.gate_challenge_id:
        # A stray confirmed submission at the right tower but not the
        # gate counts as arrival only.
        return None

    row = progress.get(step.id)
    if row is None:
        row = TeamTrailProgress(session=session, step=step, **party)
    row.advance(TeamTrailProgress.UNLOCKED)
    progress[step.id] = row

    # Reveal what comes next for this party only.
    for upcoming in next_steps(session, trail, route, progress=progress):
        _reveal(session, party, upcoming)

    unlocked_ids = {
        step_id for step_id, p in progress.items()
        if p.state == TeamTrailProgress.UNLOCKED
    }
    if route.finished_at is None and is_finished(trail, route, unlocked_ids):
        route.finished_at = row.unlocked_at
        route.save(update_fields=['finished_at'])
    return step


def read_only_gate_step(session, team, profile, tower):
    """The gate-less next step this challenge-less submission acknowledges.

    Used by the submission serializer: in TRAIL mode a challenge-less
    POST at the party's current gate-less step auto-confirms (the
    "read the clue and move on" gate) instead of entering staff review.
    """
    trail = trail_for_session(session)
    if trail is None:
        return None
    route = route_for(session, trail, team=team, profile=profile)
    if route is None:
        return None
    step = _step_for_submission(
        session, trail, route, tower,
        _progress_map(session, {'team': route.team, 'player': route.player}),
    )
    if step is not None and step.gate_challenge_id is None:
        return step
    return None


def revealed_tower_ids(session, *, team=None, profile=None):
    """Tower ids visible to this party on a TRAIL session's map.

    The per-party masking seam (see module docstring): a trail point
    stays hidden until this party's progress row reveals it.
    """
    trail = trail_for_session(session)
    if trail is None:
        return None
    party = {}
    if trail.participation == PARTICIPATION_SOLO:
        party['player'] = profile
    else:
        party['team'] = team
    return set(
        TeamTrailProgress.objects.filter(
            session=session, step__trail=trail, **party,
        ).values_list('step__tower_id', flat=True),
    )


def ranking(session):
    """Completion-and-time ranking for a TRAIL Session.

    Orders parties by steps unlocked (desc), then finish time (asc,
    unfinished last), then name — distinct from domination floating
    points, which stay inert in TRAIL mode.
    """
    trail = trail_for_session(session)
    if trail is None:
        return []
    rows = []
    routes = (
        TeamTrailRoute.objects
        .filter(session=session)
        .select_related('team', 'player__user', 'start_step')
    )
    for route in routes:
        progress = TeamTrailProgress.objects.filter(
            session=session, team=route.team, player=route.player,
            step__trail=trail,
        )
        unlocked = progress.filter(state=TeamTrailProgress.UNLOCKED).count()
        rows.append({
            'party': route.party_label(),
            'team_id': route.team_id,
            'player_id': route.player_id,
            'team_color': route.team.color if route.team_id else None,
            'steps_unlocked': unlocked,
            'finished': route.finished_at is not None,
            'finished_at': route.finished_at,
        })
    rows.sort(key=lambda r: (
        -r['steps_unlocked'],
        r['finished_at'].timestamp() if r['finished_at'] else float('inf'),
        r['party'],
    ))
    for position, row in enumerate(rows, start=1):
        row['rank'] = position
    return rows
