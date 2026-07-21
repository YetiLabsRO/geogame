"""Trail-mode API (mode-trail-discovery).

Player: GET /api/trail/state/ (party position, revealed steps, active
clues, progress), GET /api/trail/next/ (branch options), GET
/api/trail/leaderboard/. Arrival + gate unlock ride the existing
POST /api/team_tower_challenges/ submission endpoint.

Staff: /api/staff/trails|trail-steps|trail-edges/ CRUD plus per-session
/api/staff/sessions/{id}/trail-routes/ (list / upsert / auto-generate)
and /trail-reveal-start/ (stuck NONE_KNOWN override).
"""
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from game import trail as engine
from game.models import (
    KNOWLEDGE_NONE_KNOWN,
    PARTICIPATION_SOLO,
    STRUCTURE_CIRCUIT,
    STRUCTURE_FIXED_ORDER,
    STRUCTURE_GRAPH,
    TeamTrailProgress,
    TeamTrailRoute,
    TeamTrailRouteStep,
    Trail,
    TrailEdge,
    TrailStep,
)
from game.scoping import _current_session
from organize.models import Session, Team, UserProfile


def _party_for(request, session, trail):
    """Resolve the caller's party: (team, profile) per participation."""
    profile = request.user.profile
    membership = profile.memberships.filter(
        is_active=True, team__session=session,
    ).select_related('team').first()
    team = membership.team if membership else None
    if trail.participation == PARTICIPATION_SOLO:
        return None, profile
    return team, profile


def _step_payload(step, progress_row=None, clue=None):
    payload = {
        'id': step.id,
        'order': step.order,
        'is_start': step.is_start,
        'is_finish': step.is_finish,
        'has_gate': step.gate_challenge_id is not None,
        'gate_challenge': step.gate_challenge_id,
        'tower': {
            'id': step.tower_id,
            'name': step.tower.name,
            'location': {
                'type': 'Point',
                'coordinates': [step.tower.location.x, step.tower.location.y],
            },
        },
        'clue': clue if clue is not None else step.clue_text,
    }
    if progress_row is not None:
        payload.update({
            'state': progress_row.state,
            'revealed_at': progress_row.revealed_at,
            'arrived_at': progress_row.arrived_at,
            'unlocked_at': progress_row.unlocked_at,
        })
    else:
        payload['state'] = None
    return payload


class TrailStateView(APIView):
    """Player trail state: position, revealed steps, active clue(s)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session = _current_session(request)
        trail = engine.trail_for_session(session)
        if trail is None:
            return Response(
                {'detail': 'No trail state for this session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        team, profile = _party_for(request, session, trail)
        route = engine.route_for(session, trail, team=team, profile=profile)
        payload = {
            'trail': {
                'structure': trail.structure,
                'starting_knowledge': trail.starting_knowledge,
                'participation': trail.participation,
            },
            'route': None,
            'steps': [],
            'next_steps': [],
            'finished': False,
            'finished_at': None,
        }
        if route is None:
            return Response(payload)

        # Idempotent lazy seed so the first state call after route
        # assignment reveals the party's starting knowledge.
        engine.seed_initial_reveal(session, trail, route)

        party = {'team': route.team, 'player': route.player}
        progress = {
            row.step_id: row
            for row in TeamTrailProgress.objects.filter(
                session=session, step__trail=trail, **party,
            ).select_related('step__tower', 'step')
        }
        unlocked_ids = {
            sid for sid, row in progress.items()
            if row.state == TeamTrailProgress.UNLOCKED
        }
        last_unlocked = None
        if unlocked_ids:
            last_unlocked = max(
                (row for row in progress.values() if row.step_id in unlocked_ids),
                key=lambda row: (row.unlocked_at, row.id),
            ).step

        upcoming = engine.next_steps(session, trail, route, progress=progress)
        sequence = route.sequence()
        total = len(sequence) if sequence is not None else trail.steps.count()

        payload.update({
            'route': {
                'start_step': route.start_step_id,
                'party': route.party_label(),
                'sequence': [s.id for s in sequence] if sequence is not None else None,
            },
            'steps': [
                _step_payload(row.step, row)
                for row in sorted(
                    progress.values(), key=lambda r: (r.step.order, r.step_id),
                )
            ],
            'next_steps': [
                _step_payload(
                    step,
                    progress.get(step.id),
                    clue=engine.clue_for(trail, last_unlocked, step),
                )
                for step in upcoming
            ],
            'progress': {'unlocked': len(unlocked_ids), 'total': total},
            'finished': route.finished_at is not None,
            'finished_at': route.finished_at,
        })
        # A NONE_KNOWN party that has revealed nothing gets the
        # creator-supplied out-of-band hint for its start.
        if (
            trail.starting_knowledge == KNOWLEDGE_NONE_KNOWN
            and route.start_step_id not in progress
        ):
            payload['start_hint'] = route.start_step.start_hint
        return Response(payload)


class TrailNextView(APIView):
    """Branch options at the party's current position."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session = _current_session(request)
        trail = engine.trail_for_session(session)
        if trail is None:
            return Response(
                {'detail': 'No trail state for this session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        team, profile = _party_for(request, session, trail)
        route = engine.route_for(session, trail, team=team, profile=profile)
        if route is None:
            return Response({'next_steps': []})
        options = engine.next_steps(session, trail, route)
        party = {'team': route.team, 'player': route.player}
        progress = {
            row.step_id: row
            for row in TeamTrailProgress.objects.filter(
                session=session, step__in=[s.id for s in options], **party,
            )
        }
        return Response({
            'next_steps': [
                _step_payload(step, progress.get(step.id))
                for step in options
            ],
            'is_branch': len(options) > 1,
        })


class TrailLeaderboardView(APIView):
    """Completion-and-time ranking for the caller's TRAIL session."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session = _current_session(request)
        trail = engine.trail_for_session(session)
        if trail is None:
            return Response(
                {'detail': 'No trail leaderboard for this session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({'ranking': engine.ranking(session)})


# ---------------------------------------------------------------------------
# Staff authoring
# ---------------------------------------------------------------------------


class AdminTrailSerializer(serializers.ModelSerializer):
    issues = serializers.SerializerMethodField()
    step_count = serializers.SerializerMethodField()

    class Meta:
        model = Trail
        fields = (
            'id', 'game', 'structure', 'starting_knowledge',
            'participation', 'step_count', 'issues', 'created_at',
        )
        read_only_fields = ('created_at',)

    def get_issues(self, trail):
        return trail.validate_structure()

    def get_step_count(self, trail):
        return trail.steps.count()


class AdminTrailViewSet(viewsets.ModelViewSet):
    """Staff CRUD for Trails; ?game=<id> filters. `issues` reports the
    structural validation (reachability / dead-ends / out-of-collection
    towers) on every read so the authoring UI can surface warnings."""

    permission_classes = [IsAdminUser]
    queryset = Trail.objects.select_related('game').order_by('id')
    serializer_class = AdminTrailSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        game_id = self.request.query_params.get('game')
        if game_id:
            qs = qs.filter(game_id=game_id)
        return qs

    @action(detail=True, methods=['get'])
    def validate(self, request, pk=None):
        trail = self.get_object()
        issues = trail.validate_structure()
        return Response({'valid': not issues, 'issues': issues})


class AdminTrailStepSerializer(serializers.ModelSerializer):
    tower_name = serializers.CharField(source='tower.name', read_only=True)

    class Meta:
        model = TrailStep
        fields = (
            'id', 'trail', 'tower', 'tower_name', 'order',
            'is_start', 'is_finish', 'gate_challenge',
            'clue_text', 'start_hint',
        )

    def validate(self, attrs):
        trail = attrs.get('trail') or (self.instance.trail if self.instance else None)
        tower = attrs.get('tower') or (self.instance.tower if self.instance else None)
        if trail is not None and tower is not None:
            if not trail.game.towers().filter(pk=tower.pk).exists():
                raise serializers.ValidationError(
                    "The step's tower must resolve through the Game's Collections.",
                )
        gate = attrs.get('gate_challenge')
        if gate is not None and trail is not None and gate.game_id != trail.game_id:
            raise serializers.ValidationError(
                "gate_challenge must belong to the trail's Game.",
            )
        return attrs


class AdminTrailStepViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
    queryset = TrailStep.objects.select_related('tower', 'trail').order_by('order', 'id')
    serializer_class = AdminTrailStepSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        trail_id = self.request.query_params.get('trail')
        if trail_id:
            qs = qs.filter(trail_id=trail_id)
        return qs


class AdminTrailEdgeSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrailEdge
        fields = ('id', 'trail', 'from_step', 'to_step', 'clue')

    def validate(self, attrs):
        trail = attrs.get('trail') or (self.instance.trail if self.instance else None)
        for field in ('from_step', 'to_step'):
            step = attrs.get(field) or (
                getattr(self.instance, field) if self.instance else None
            )
            if trail is not None and step is not None and step.trail_id != trail.id:
                raise serializers.ValidationError(
                    f'{field} must belong to the same trail.',
                )
        from_step = attrs.get('from_step') or (self.instance.from_step if self.instance else None)
        to_step = attrs.get('to_step') or (self.instance.to_step if self.instance else None)
        if from_step is not None and to_step is not None and from_step.pk == to_step.pk:
            raise serializers.ValidationError('An edge cannot loop onto its own step.')
        return attrs


class AdminTrailEdgeViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAdminUser]
    queryset = TrailEdge.objects.select_related('from_step', 'to_step').order_by('id')
    serializer_class = AdminTrailEdgeSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        trail_id = self.request.query_params.get('trail')
        if trail_id:
            qs = qs.filter(trail_id=trail_id)
        return qs


def _route_payload(route):
    return {
        'id': route.id,
        'team': route.team_id,
        'player': route.player_id,
        'party': route.party_label(),
        'start_step': route.start_step_id,
        'step_ids': [
            rs.step_id
            for rs in route.route_steps.order_by('position')
        ],
        'finished_at': route.finished_at,
    }


class SessionTrailRoutesView(APIView):
    """Per-session route assignment: GET lists, POST upserts one route.

    POST body: {"team": <id>} or {"player": <profile id>} plus
    "start_step" and, optionally, "step_ids" (an explicit ordered
    sequence for FIXED_ORDER / CIRCUIT anti-collision routing).
    """

    permission_classes = [IsAdminUser]

    def _session_trail(self, pk):
        session = get_object_or_404(Session, pk=pk)
        trail = Trail.objects.filter(game=session.game).first()
        return session, trail

    def get(self, request, pk):
        session, trail = self._session_trail(pk)
        if trail is None:
            return Response(
                {'detail': "This session's game has no trail."},
                status=status.HTTP_404_NOT_FOUND,
            )
        routes = (
            TeamTrailRoute.objects
            .filter(session=session)
            .select_related('team', 'player__user')
            .prefetch_related('route_steps')
            .order_by('id')
        )
        return Response({'routes': [_route_payload(r) for r in routes]})

    def post(self, request, pk):
        session, trail = self._session_trail(pk)
        if trail is None:
            return Response(
                {'detail': "This session's game has no trail."},
                status=status.HTTP_404_NOT_FOUND,
            )
        team = player = None
        if trail.participation == PARTICIPATION_SOLO:
            player = UserProfile.objects.filter(pk=request.data.get('player')).first()
            if player is None:
                return Response(
                    {'detail': 'player (profile id) is required for a SOLO trail.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            team = Team.objects.filter(
                pk=request.data.get('team'), session=session,
            ).first()
            if team is None:
                return Response(
                    {'detail': 'team (id, in this session) is required.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        start_step = TrailStep.objects.filter(
            pk=request.data.get('start_step'), trail=trail,
        ).first()
        if start_step is None:
            return Response(
                {'detail': 'start_step (id, on this trail) is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        step_ids = request.data.get('step_ids') or []
        steps = []
        if step_ids:
            by_id = {s.id: s for s in trail.steps.filter(id__in=step_ids)}
            missing = [sid for sid in step_ids if sid not in by_id]
            if missing:
                return Response(
                    {'detail': f'Unknown step ids for this trail: {missing}.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            steps = [by_id[sid] for sid in step_ids]
            if steps and steps[0].id != start_step.id:
                return Response(
                    {'detail': 'step_ids must begin with start_step.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        route, _ = TeamTrailRoute.objects.update_or_create(
            session=session, team=team, player=player,
            defaults={'start_step': start_step, 'finished_at': None},
        )
        route.route_steps.all().delete()
        TeamTrailRouteStep.objects.bulk_create([
            TeamTrailRouteStep(route=route, step=step, position=position)
            for position, step in enumerate(steps)
        ])
        engine.seed_initial_reveal(session, trail, route)
        return Response(_route_payload(route), status=status.HTTP_201_CREATED)


class SessionTrailRoutesGenerateView(APIView):
    """Auto-generate divergent per-party routes (anti-collision).

    FIXED_ORDER: each party gets the base order rotated by an even
    offset (an explicit sequence). CIRCUIT: parties share the cyclic
    order with evenly spaced start offsets. GRAPH: start steps are
    dealt round-robin. Replaces existing routes.
    """

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        trail = Trail.objects.filter(game=session.game).first()
        if trail is None:
            return Response(
                {'detail': "This session's game has no trail."},
                status=status.HTTP_404_NOT_FOUND,
            )
        steps = trail.ordered_steps()
        if not steps:
            return Response(
                {'detail': 'Trail has no steps.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if trail.participation == PARTICIPATION_SOLO:
            parties = [
                {'team': None, 'player': profile}
                for profile in UserProfile.objects.filter(
                    memberships__is_active=True,
                    memberships__team__session=session,
                ).distinct().order_by('id')
            ]
        else:
            parties = [
                {'team': team, 'player': None}
                for team in session.teams.order_by('id')
            ]
        if not parties:
            return Response(
                {'detail': 'No parties (teams/players) in this session.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        TeamTrailRoute.objects.filter(session=session).delete()
        routes = []
        starts = trail.start_steps()
        for index, party in enumerate(parties):
            offset = (index * len(steps)) // len(parties)
            if trail.structure == STRUCTURE_GRAPH:
                route = TeamTrailRoute.objects.create(
                    session=session,
                    start_step=starts[index % len(starts)],
                    **party,
                )
            elif trail.structure == STRUCTURE_CIRCUIT:
                route = TeamTrailRoute.objects.create(
                    session=session, start_step=steps[offset % len(steps)], **party,
                )
            else:  # FIXED_ORDER: explicit rotated sequence
                rotation = steps[offset:] + steps[:offset]
                route = TeamTrailRoute.objects.create(
                    session=session, start_step=rotation[0], **party,
                )
                TeamTrailRouteStep.objects.bulk_create([
                    TeamTrailRouteStep(route=route, step=step, position=position)
                    for position, step in enumerate(rotation)
                ])
            engine.seed_initial_reveal(session, trail, route)
            routes.append(route)
        assert trail.structure in (
            STRUCTURE_FIXED_ORDER, STRUCTURE_GRAPH, STRUCTURE_CIRCUIT,
        )
        return Response(
            {'routes': [_route_payload(r) for r in routes]},
            status=status.HTTP_201_CREATED,
        )


class SessionTrailRevealStartView(APIView):
    """Staff override: reveal a stuck NONE_KNOWN party's start step."""

    permission_classes = [IsAdminUser]

    def post(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        trail = Trail.objects.filter(game=session.game).first()
        if trail is None:
            return Response(
                {'detail': "This session's game has no trail."},
                status=status.HTTP_404_NOT_FOUND,
            )
        filters = {'session': session}
        if request.data.get('team'):
            filters['team_id'] = request.data['team']
        elif request.data.get('player'):
            filters['player_id'] = request.data['player']
        else:
            return Response(
                {'detail': 'team or player is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        route = TeamTrailRoute.objects.filter(**filters).first()
        if route is None:
            return Response(
                {'detail': 'No route assigned to that party.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        row = engine.reveal_start(session, trail, route)
        return Response({
            'revealed_step': row.step_id,
            'state': row.state,
        })


class SessionTrailLeaderboardView(APIView):
    """Staff view of the trail ranking for one session."""

    permission_classes = [IsAdminUser]

    def get(self, request, pk):
        session = get_object_or_404(Session, pk=pk)
        if engine.trail_for_session(session) is None:
            return Response(
                {'detail': 'Not a TRAIL session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response({'ranking': engine.ranking(session)})
