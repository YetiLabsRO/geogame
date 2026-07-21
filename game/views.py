import secrets
import uuid

from django.contrib.gis.db.models.functions import Distance as DistanceFunc
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import Distance
from django.db import OperationalError, connection, transaction
from django.db.models import Count, F, FloatField, Q, Value
from django.db.models.functions import Cast, Coalesce, Least
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from rest_framework import permissions, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from game.challenge_types import REVIEW_AUTO, get_handler
from game.discovery import evaluate_discovery, visible_towers, visible_zone_ids
from game.location_api import _active_team
from game.models import (
    NFC_MODE_SECURE_TOKEN,
    Challenge,
    NfcTag,
    TagScan,
    TeamTowerChallenge,
    TeamTowerFailCounter,
    Tower,
    Zone,
)
from game.scoping import (
    GameGeometryScopedViewSetMixin,
    GameScopedViewSetMixin,
    SessionScopedViewSetMixin,
    _current_session,
)
from game.serializers import (
    ChallengeSerializer,
    TeamSerializer,
    TeamTowerChallengeSerializer,
    TowerSerializer,
    ZoneSerializer,
)
from game.trail import (
    on_submission_confirmed,
    on_submission_created,
    revealed_tower_ids,
)
from organize.models import (
    MODE_TRAIL,
    Team,
    TeamGroup,
    TeamMembership,
    effective_allow_player_team_creation,
    effective_mode,
)


class TeamVisibilityMixin:
    """Caller-team resolution + ownership-reveal context (tower-visibility).

    Staff and team-less callers are omniscient: the visibility filter is
    bypassed and ownership colouring stays complete. Player callers are
    filtered to their team's visible geometry, and the serializers are
    handed the context needed to conceal other teams' control when the
    effective `reveal_other_teams_ownership` is False.
    """

    def _visibility_context(self):
        session = _current_session(self.request)
        team = None
        if session is not None and not self.request.user.is_staff:
            team = _active_team(self.request.user, session)
        reveal_others = True
        if session is not None and team is not None:
            reveal_others = bool(session.effective('reveal_other_teams_ownership'))
        return session, team, reveal_others

    def get_serializer_context(self):
        context = super().get_serializer_context()
        session, team, reveal_others = self._visibility_context()
        context['team'] = team
        context['reveal_others'] = reveal_others
        return context


class ZoneViewSet(TeamVisibilityMixin, GameGeometryScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Zone.objects.all()
    serializer_class = ZoneSerializer
    permission_classes = [permissions.IsAuthenticated]
    geometry_resolver = 'zones'

    def get_queryset(self):
        qs = super().get_queryset()
        # Member towers are the many-to-many `towers` reverse
        # (tower-zone-topology) — not the removed single FK.
        qs = qs.annotate(
            num_towers=Count('towers', filter=Q(towers__is_active=True)),
        ).filter(num_towers__gte=1)
        # tower-visibility: hide a zone whose only towers are
        # undiscovered FOG_REVEAL towers. Staff/team-less callers bypass.
        session, team, _reveal = self._visibility_context()
        if session is not None and team is not None:
            qs = qs.filter(pk__in=visible_zone_ids(session, team))
        return qs

    def get_serializer_context(self):
        context = super(ZoneViewSet, self).get_serializer_context()
        group_id = self.request.query_params.get('group')
        group_slug = self.request.query_params.get('group_slug')
        if not group_id and group_slug:
            group = TeamGroup.objects.filter(slug=group_slug).first()
            group_id = group.id if group else 0
        context['group'] = group_id or 0
        return context


class TowerViewSet(TeamVisibilityMixin, GameGeometryScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Tower.objects.exclude(is_active=False).exclude(category=Tower.CATEGORY_RFID)
    serializer_class = TowerSerializer
    permission_classes = [permissions.IsAuthenticated]
    geometry_resolver = 'towers'

    def get_queryset(self):
        queryset = super().get_queryset()
        # tower-visibility + mode-trail-discovery both narrow the tower
        # queryset for the caller; resolve the session/team context once.
        session, team, _reveal = self._visibility_context()
        if session is not None:
            # mode-trail-discovery: on a TRAIL session, mask trail points
            # the caller's party has not revealed yet (per-party map
            # masking — see game.trail.revealed_tower_ids).
            revealed = revealed_tower_ids(
                session,
                team=team,
                profile=self.request.user.profile,
            )
            if revealed is not None:
                queryset = queryset.filter(pk__in=revealed)
        if session is not None and team is not None:
            lat = self.request.query_params.get('lat')
            lng = self.request.query_params.get('lng')
            if lat and lng:
                # A reported position drives discovery evaluation too, so
                # walking near a HIDDEN tower pops it up on the next fetch
                # (discovery-tracking capability).
                evaluate_discovery(
                    session, team,
                    Point(float(lng), float(lat), srid=4326),
                    user=self.request.user,
                )
            # Team-visibility filter at the queryset level: undiscovered
            # HIDDEN/FOG_REVEAL geometry never reaches the client.
            queryset = queryset.filter(
                pk__in=visible_towers(session, team).values('pk'),
            )
        if self.request.query_params.get("lat") and self.request.query_params.get("lng"):
            lat = float(self.request.query_params.get("lat"))
            lng = float(self.request.query_params.get("lng"))
            point = Point(lng, lat, srid=4326)
            accuracy = float(self.request.query_params.get("accuracy", 100.))

            # Effective per-tower radius (zone-conquest-and-scoring-config):
            # the tower's own proximity_meters when set, else the Game's
            # game-wide default — each capped by the reported GPS accuracy,
            # preserving the historical `min(accuracy, game default)` shape.
            session = _current_session(self.request)
            default_radius = float(
                session.game.proximity_meters if session is not None else 50,
            )
            return queryset.annotate(
                _distance=DistanceFunc('location', point),
                _radius=Least(
                    Coalesce(
                        Cast('proximity_meters', FloatField()),
                        Value(default_radius),
                    ),
                    Value(accuracy),
                    output_field=FloatField(),
                ),
            ).filter(_distance__lt=F('_radius'))
        return queryset


def _random_team_color():
    return f'#{secrets.randbelow(0xFFFFFF):06X}'


class TeamViewSet(SessionScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Team.objects.all()
    serializer_class = TeamSerializer
    permission_classes = [permissions.IsAuthenticated]
    session_scope_field = 'session'

    def get_queryset(self):
        qs = super().get_queryset()
        category = int(self.request.query_params.get("category", 0))
        if category:
            qs = qs.filter(category=category)
        return qs

    def get_serializer_context(self):
        context = super(TeamViewSet, self).get_serializer_context()
        context['category'] = self.request.query_params.get('category', 0)
        return context

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        """Create a team in the caller's current Session.

        Staff may always create teams. A player may create one only when
        the effective `allow_player_team_creation` toggle is enabled for
        their current Session; the creator becomes the captain and first
        member (see the team-formation capability).
        """
        user = request.user
        session = user.profile.current_session
        if session is None:
            return Response(
                {'detail': 'You are not in any session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        is_player_create = not user.is_staff
        if is_player_create:
            if not effective_allow_player_team_creation(session):
                return Response(
                    {'detail': 'Player team creation is not enabled for this session.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            if Team.objects.filter(session=session, captain=user).exists():
                return Response(
                    {'detail': 'You have already created a team in this session.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            membership = (
                TeamMembership.objects
                .filter(user=user.profile, is_active=True, game=session.game)
                .select_related('team')
                .first()
            )
            if membership is not None:
                return Response(
                    {
                        'detail': (
                            f'You are already on team "{membership.team.name}" in '
                            f'"{session.game.name}". Leave that team before '
                            'creating another in the same game.'
                        ),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

        data = request.data.copy()
        if not data.get('color'):
            data['color'] = _random_team_color()
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)

        group = serializer.validated_data.get('group')
        if group is not None and group.game_id != session.game_id:
            return Response(
                {'detail': 'That team group belongs to a different game.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        extra = {'session': session}
        if is_player_create:
            # The creator becomes captain and gets an untied join code to
            # share right away. Role-based invite powers are a future
            # change (team-roles-as-mechanics).
            extra['captain'] = user
            extra['join_code'] = uuid.uuid4()
        team = serializer.save(**extra)
        if is_player_create:
            TeamMembership.objects.create(
                team=team, user=user.profile, is_active=True,
            )
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers,
        )


class ChallengeViewSet(GameScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Challenge.objects.all()
    serializer_class = ChallengeSerializer
    permission_classes = [permissions.IsAuthenticated]
    game_scope_field = 'game'


class TeamTowerChallengeViewSet(SessionScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = TeamTowerChallenge.objects.all()
    serializer_class = TeamTowerChallengeSerializer
    permission_classes = [permissions.IsAuthenticated]
    session_scope_field = 'team__session'

    def perform_create(self, serializer):
        ttc = serializer.save()
        if effective_mode(ttc.team.session) == MODE_TRAIL:
            # mode-trail-discovery: geofenced arrival marks the step
            # ARRIVED; a confirmed gate unlocks it. Domination capture
            # (tower ownership + bonus) stays inert in TRAIL mode.
            on_submission_created(ttc)
            if ttc.outcome == TeamTowerChallenge.CONFIRMED:
                on_submission_confirmed(ttc)
        elif ttc.outcome == TeamTowerChallenge.CONFIRMED:
            ttc.tower.assign_to_team(ttc.team)


# ---------------------------------------------------------------------------
# nfc-native-and-secure-links
# ---------------------------------------------------------------------------


def nfc_landing(request, token):
    """GET /nfc/<token>/ — the app-link target for a secure tag.

    Opened by anything other than the installed app this renders a
    plain "open this in the app to scan" page and performs NO capture,
    no tag lookup, no side effect of any kind — a forwarded link is
    inert by construction, and an invalid token is indistinguishable
    from a valid one (no validity oracle).

    App-link wiring notes (deployment, not code):
    - Android App Links: serve /.well-known/assetlinks.json listing the
      app package (settings.NFC_ANDROID_PACKAGE) + its signing cert
      SHA-256 so Android routes https://<host>/nfc/* to the app.
    - iOS Universal Links: serve /.well-known/apple-app-site-association
      with an applinks entry for /nfc/*.
    Both files belong to the reverse-proxy / static layer; the installed
    app deep-links straight into the scan flow and never loads this page.
    """
    return render(request, 'game/nfc_landing.html', {
        'token': token,
        'deep_link': f'cercetador://nfc/{token}',
    })


class NfcCaptureView(APIView):
    """POST /api/nfc/capture/ — the real security boundary for tag scans.

    Accepts {token, lat, lng, accuracy, counter} from the authenticated
    app. Check order mirrors the submission serializer: membership →
    tag resolution → secure-mode/app gates → session scope → replay
    counter → GPS proximity → pause → failure lockout → outcome. Every
    attempt that resolves to a known tag writes a TagScan audit row.

    The "open in the app" page is a UX guard only; this endpoint
    independently enforces auth, session scope, proximity and (when
    enabled) the rolling counter — per the documented threat model, tag
    contents are treated as extractable and forgeable.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request):
        data = request.data
        token = data.get('token')
        if not token:
            return Response({'detail': 'token is required.'}, status=400)
        tag = (
            NfcTag.objects
            .select_related('tower', 'challenge', 'challenge__tower')
            .filter(token=token)
            .first()
        )
        if tag is None:
            # No FK target to audit against; same shape as an unknown
            # RFID code (the legacy path's 400).
            return Response({'detail': 'Cod necunoscut.'}, status=404)

        def _float(key):
            try:
                return float(data.get(key)) if data.get(key) is not None else None
            except (TypeError, ValueError):
                return None

        lat, lng, accuracy = _float('lat'), _float('lng'), _float('accuracy')
        try:
            counter = int(data['counter']) if data.get('counter') is not None else None
        except (TypeError, ValueError):
            counter = None

        membership = (
            request.user.profile.memberships
            .filter(is_active=True)
            .select_related('team__session__game')
            .first()
        )
        session = membership.team.session if membership else None

        def audit(outcome):
            TagScan.objects.create(
                tag=tag, player=request.user, membership=membership,
                session=session, outcome=outcome,
                lat=lat, lng=lng, accuracy=accuracy, counter=counter,
            )

        def reject(outcome, detail, http_status=400):
            audit(outcome)
            return Response({'outcome': 'REJECTED', 'detail': detail}, status=http_status)

        if membership is None:
            return reject(
                TagScan.OUTCOME_REJECTED_NO_TEAM,
                'Nu ești membru al unei echipe active.', 403,
            )
        team = membership.team

        if not tag.is_active:
            return reject(TagScan.OUTCOME_REJECTED_INACTIVE, 'Tag inactiv.')

        # Secure-token captures are opt-in per Game/Session; with the
        # knob off nothing changes for existing games (legacy behavior).
        if tag.mode == NFC_MODE_SECURE_TOKEN and not session.effective('nfc_secure_mode'):
            return reject(
                TagScan.OUTCOME_REJECTED_DISABLED,
                'Modul securizat NFC nu este activ pentru această sesiune.',
            )

        # App-origin marker: a deterrent for raw-browser hits; auth +
        # proximity below stay the real boundary.
        if session.effective('nfc_require_app') and not request.headers.get('X-Cercetador-App'):
            return reject(
                TagScan.OUTCOME_REJECTED_APP,
                'Scanarea funcționează doar din aplicație.', 403,
            )

        challenge = tag.challenge
        tower = tag.capture_tower()
        in_scope = tower is not None and session.game.towers().filter(pk=tower.pk).exists()
        if challenge is not None and challenge.game_id != session.game_id:
            in_scope = False
        if not in_scope:
            return reject(
                TagScan.OUTCOME_REJECTED_SCOPE,
                'Acest tag nu aparține jocului tău.', 404,
            )

        if session.effective('nfc_replay_hardening'):
            if counter is None:
                return reject(
                    TagScan.OUTCOME_REJECTED_REPLAY,
                    'Acest joc cere un contor de scanare (tag cu counter).',
                )
            if tag.last_counter is not None and counter <= tag.last_counter:
                return reject(
                    TagScan.OUTCOME_REJECTED_REPLAY,
                    'Scanare respinsă: contor repetat sau mai mic (replay).',
                )
            tag.last_counter = counter
            tag.save(update_fields=['last_counter'])

        proximity = session.game.proximity_meters
        if lat is None or lng is None or not Tower.objects.filter(
            pk=tower.pk,
            location__distance_lte=(Point(lng, lat), Distance(m=proximity)),
        ).exists():
            return reject(
                TagScan.OUTCOME_REJECTED_PROXIMITY,
                f'Trebuie să fii la maxim {proximity} metri de tag.',
            )

        paused_hold = False
        if session.is_paused():
            if session.effective('pause_rejects_submissions'):
                return reject(
                    TagScan.OUTCOME_REJECTED_STATE,
                    'Sesiunea este în pauză; trimiterile sunt oprite.', 409,
                )
            paused_hold = True

        fail_counter = TeamTowerFailCounter.objects.filter(team=team, tower=tower).first()
        if fail_counter and fail_counter.is_locked():
            return reject(
                TagScan.OUTCOME_REJECTED_STATE,
                'Turn blocat temporar după eșecuri consecutive.', 409,
            )

        # Outcome resolution LAST (parity with the submission pipeline):
        # a paused hold always wins; a tower target auto-confirms exactly
        # like an RFID capture; a challenge target routes through its
        # type handler / review-mode override.
        if paused_hold:
            outcome = TeamTowerChallenge.PENDING
        elif challenge is None:
            outcome = TeamTowerChallenge.CONFIRMED
        else:
            handler = get_handler(challenge.type)
            if handler is None:
                return reject(
                    TagScan.OUTCOME_REJECTED_SCOPE,
                    f'Tip de provocare necunoscut: {challenge.type}.',
                )
            if challenge.effective_review_mode() == REVIEW_AUTO:
                # The physical tag IS the credential: it supplies the
                # expected code by binding, so the handler decides on
                # consumption (single_use) rather than string matching.
                expected = handler.expected_code(challenge, tower)
                outcome = handler.validate(
                    challenge, tower, team, submitted_code=expected,
                )
            else:
                outcome = TeamTowerChallenge.PENDING

        extra = {}
        if outcome != TeamTowerChallenge.PENDING:
            extra['timestamp_verified'] = timezone.now()
        ttc = TeamTowerChallenge(
            team=team,
            tower=tower,
            challenge=challenge,
            submitted_by=request.user,
            outcome=outcome,
            submitted_code=tag.token[:64],
            **extra,
        )
        if outcome == TeamTowerChallenge.REJECTED:
            # e.g. a consumed single_use challenge code: feed the same
            # failure consequences as the typed-code path.
            ttc._system_resolved = True
        ttc.save()
        if outcome == TeamTowerChallenge.CONFIRMED:
            tower.assign_to_team(team)

        outcome_label = {
            TeamTowerChallenge.CONFIRMED: TagScan.OUTCOME_CONFIRMED,
            TeamTowerChallenge.PENDING: TagScan.OUTCOME_PENDING,
            TeamTowerChallenge.REJECTED: TagScan.OUTCOME_REJECTED_CODE,
        }[outcome]
        audit(outcome_label)
        return Response({
            'outcome': outcome_label,
            'submission_id': ttc.id,
            'tower': {'id': tower.id, 'name': tower.name},
            'challenge': challenge.id if challenge else None,
        }, status=status.HTTP_201_CREATED)


def health(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except OperationalError:
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok"})
