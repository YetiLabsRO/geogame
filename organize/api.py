from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import generics, serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import APIException, PermissionDenied
from rest_framework.permissions import (
    SAFE_METHODS,
    AllowAny,
    BasePermission,
    IsAuthenticated,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from game.scoping import SessionScopedViewSetMixin
from organize.emails import send_invite_email
from organize.models import (
    JOIN_CONFIRM_AUTO_APPROVE,
    Invite,
    Session,
    Team,
    TeamJoinRequest,
    TeamMembership,
    active_membership_conflict,
    effective_allow_player_team_creation,
    effective_team_join_confirmation,
    user_can_invite_to_team,
)

User = get_user_model()


class TeamFullError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = 'Team is already at its maximum member count.'
    default_code = 'team_full'


def _can_manage_team_invites(user, team):
    """Centralized invite-management rights (team-formation + team-roles).

    Staff manage any team's invites; a captain manages their own team's
    while player team formation is enabled for its Session; and holders
    of a role whose `builtin_power` is INVITER may create/manage invites
    for their own team regardless of the toggle
    (team-roles-as-mechanics).
    """
    if user.is_staff:
        return True
    if (
        team.captain_id == user.id
        and effective_allow_player_team_creation(team.session)
    ):
        return True
    return user_can_invite_to_team(user, team)


def _can_decide_join_request(user, team):
    """Approve/reject rights: staff for any team, captain for their own."""
    return user.is_staff or team.captain_id == user.id


def _membership_conflict_response(conflict, game):
    return Response(
        {
            'detail': (
                f'You are already on team "{conflict.team.name}" in '
                f'"{game.name}". Leave that team before joining '
                'another in the same game.'
            ),
        },
        status=status.HTTP_409_CONFLICT,
    )


# ---------- Serializers ----------

class RegisterSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)

    def validate_username(self, value):
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError('Username already taken.')
        return value

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('Email already registered.')
        return value


class LoginSerializer(serializers.Serializer):
    # The "login" field accepts either username or email.
    login = serializers.CharField()
    password = serializers.CharField(write_only=True)


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8)


class UserProfileSerializer(serializers.Serializer):
    id = serializers.IntegerField(source='user.id', read_only=True)
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.EmailField(source='user.email')
    first_name = serializers.CharField(source='user.first_name', required=False, allow_blank=True)
    last_name = serializers.CharField(source='user.last_name', required=False, allow_blank=True)
    current_session = serializers.PrimaryKeyRelatedField(read_only=True)
    current_game = serializers.SerializerMethodField()
    active_team_id = serializers.SerializerMethodField()
    active_roles = serializers.SerializerMethodField()
    is_staff = serializers.BooleanField(source='user.is_staff', read_only=True)
    allow_player_team_creation = serializers.SerializerMethodField()
    captain_of_team_id = serializers.SerializerMethodField()

    def get_current_game(self, profile):
        session = profile.current_session
        return session.game_id if session is not None else None

    def _active_membership(self, profile):
        return profile.memberships.filter(is_active=True).select_related('team').first()

    def get_active_team_id(self, profile):
        membership = self._active_membership(profile)
        return membership.team_id if membership else None

    def get_active_roles(self, profile):
        """In-game roles held on the caller's active membership."""
        membership = self._active_membership(profile)
        if membership is None:
            return []
        return _membership_roles(membership)

    def get_allow_player_team_creation(self, profile):
        session = profile.current_session
        if session is None:
            return False
        return effective_allow_player_team_creation(session)

    def get_captain_of_team_id(self, profile):
        membership = (
            profile.memberships
            .filter(is_active=True, team__captain=profile.user)
            .select_related('team')
            .first()
        )
        return membership.team_id if membership else None

    def update(self, profile, validated_data):
        user_data = validated_data.pop('user', {})
        for field, value in user_data.items():
            setattr(profile.user, field, value)
        profile.user.save()
        return profile


def _membership_roles(membership):
    """Serialize a membership's held GameRoles for API payloads."""
    return [
        {
            'id': tr.role.id,
            'slug': tr.role.slug,
            'name': tr.role.name,
            'builtin_power': tr.role.builtin_power,
        }
        for tr in membership.roles.select_related('role').all()
    ]


class TeamMemberSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(source='user.user.id')
    username = serializers.CharField(source='user.user.username')
    first_name = serializers.CharField(source='user.user.first_name')
    last_name = serializers.CharField(source='user.user.last_name')
    joined_at = serializers.DateTimeField()
    roles = serializers.SerializerMethodField()

    def get_roles(self, membership):
        return _membership_roles(membership)


class MyTeamSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    color = serializers.CharField()
    score = serializers.IntegerField()
    current_score = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()
    can_invite = serializers.SerializerMethodField()
    active_member_count = serializers.SerializerMethodField()
    is_ready = serializers.SerializerMethodField()
    members_needed = serializers.SerializerMethodField()

    def get_current_score(self, team):
        return team.current_score()

    def get_members(self, team):
        active = (
            team.memberships
            .filter(is_active=True)
            .select_related('user__user')
            .prefetch_related('roles__role')
        )
        return TeamMemberSerializer(active, many=True).data

    def get_can_invite(self, team):
        """INVITER affordance: may the caller create invites for this team?"""
        request = self.context.get('request')
        if request is None:
            return False
        return user_can_invite_to_team(request.user, team)

    def get_active_member_count(self, team):
        return team.active_member_count()

    def get_is_ready(self, team):
        return team.is_ready()

    def get_members_needed(self, team):
        return team.members_needed()


# ---------- Views ----------

@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    user = User.objects.create_user(
        username=data['username'],
        email=data['email'],
        password=data['password'],
        first_name=data.get('first_name', ''),
        last_name=data.get('last_name', ''),
    )
    token, _ = Token.objects.get_or_create(user=user)
    return Response(
        {'token': token.key, 'user_id': user.id, 'username': user.username},
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    login_value = serializer.validated_data['login']
    password = serializer.validated_data['password']

    username = login_value
    if '@' in login_value:
        match = User.objects.filter(email__iexact=login_value).first()
        if match is not None:
            username = match.username

    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response(
            {'detail': 'Invalid credentials.'}, status=status.HTTP_401_UNAUTHORIZED,
        )
    token, _ = Token.objects.get_or_create(user=user)
    return Response({'token': token.key, 'user_id': user.id, 'username': user.username})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout(request):
    Token.objects.filter(user=request.user).delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_request(request):
    serializer = PasswordResetRequestSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    email = serializer.validated_data['email']
    user = User.objects.filter(email__iexact=email).first()
    # Return 200 whether or not the email exists, to avoid user-enumeration.
    if user is not None:
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        reset_url = f'{settings.BASE_URL}/reset/{uid}/{token}'
        send_mail(
            subject='Reset your cercetador password',
            message=(
                f'Hi {user.get_username()},\n\n'
                f'Use the link below to set a new password:\n\n{reset_url}\n\n'
                'If you did not request this, you can ignore this email.'
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
            fail_silently=False,
        )
    return Response(status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def password_reset_confirm(request):
    serializer = PasswordResetConfirmSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        uid = force_str(urlsafe_base64_decode(serializer.validated_data['uid']))
        user = User.objects.get(pk=uid)
    except (ValueError, TypeError, User.DoesNotExist):
        return Response({'detail': 'Invalid reset link.'}, status=status.HTTP_400_BAD_REQUEST)
    if not default_token_generator.check_token(user, serializer.validated_data['token']):
        return Response({'detail': 'Invalid or expired reset link.'}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(serializer.validated_data['new_password'])
    user.save()
    Token.objects.filter(user=user).delete()
    return Response(status=status.HTTP_200_OK)


class MeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserProfileSerializer(request.user.profile).data)

    def patch(self, request):
        serializer = UserProfileSerializer(request.user.profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class MyTeamView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        membership = (
            TeamMembership.objects
            .filter(user=request.user.profile, is_active=True)
            .select_related('team')
            .first()
        )
        if membership is None:
            return Response(
                {'detail': 'You are not a member of any team.'}, status=status.HTTP_404_NOT_FOUND,
            )
        return Response(
            MyTeamSerializer(membership.team, context={'request': request}).data,
        )


class GameConfigSerializer(serializers.Serializer):
    """Read-only config payload nested under a Session.

    Separate from any write-side Game serializer so clients have a
    stable shape without needing to know Session internals.
    """

    id = serializers.IntegerField()
    name = serializers.CharField()
    slug = serializers.CharField()
    is_active = serializers.BooleanField()
    base_point = serializers.SerializerMethodField()
    base_zoom_level = serializers.IntegerField()
    proximity_meters = serializers.IntegerField()
    cooloff_minutes = serializers.IntegerField()
    initial_bonus_default = serializers.IntegerField()
    allow_player_team_creation = serializers.BooleanField()
    team_join_confirmation = serializers.CharField()
    team_groups = serializers.SerializerMethodField()

    def get_base_point(self, game):
        if game.base_point is None:
            return None
        return {
            'type': 'Point',
            'coordinates': [game.base_point.x, game.base_point.y],
        }

    def get_team_groups(self, game):
        return [
            {'id': g.id, 'name': g.name, 'slug': g.slug}
            for g in game.teamgroup_set.order_by('name')
        ]


class CurrentSessionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()
    state = serializers.CharField()
    is_active = serializers.BooleanField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    game = GameConfigSerializer()
    # Effective (Session override, else Game default) player-team-creation
    # toggle for this session.
    allow_player_team_creation = serializers.SerializerMethodField()
    # Effective live-location config (live-location capability). The app
    # paces streaming off `location_ping_interval_seconds`; there is no
    # player-facing frequency control.
    location = serializers.SerializerMethodField()

    def get_allow_player_team_creation(self, session):
        return effective_allow_player_team_creation(session)

    def get_location(self, session):
        return {
            'tracking_enabled': bool(session.effective('location_tracking_enabled')),
            'ping_interval_seconds': session.effective('location_ping_interval_seconds'),
            'visibility': session.effective('location_visibility'),
            'consent_text': session.effective('location_consent_text') or '',
        }


class MySessionsView(APIView):
    """Active + past Sessions the authenticated user has a membership on.

    Memberships with `is_active=False` (i.e. the player left the team)
    still show up; the per-session scoreboard endpoint locks those out
    on access control if the player has no memberships at all on the
    session.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        session_ids = (
            request.user.profile.memberships
            .values_list('team__session_id', flat=True)
            .distinct()
        )
        sessions = (
            Session.objects
            .filter(id__in=session_ids)
            .select_related('game')
            .order_by('-start_time')
        )
        return Response(
            CurrentSessionSerializer(sessions, many=True).data,
        )


def _user_can_see_session(user, session):
    if user.is_staff:
        return True
    return user.profile.memberships.filter(
        team__session=session,
    ).exists()


class SessionScoreboardView(APIView):
    """Final scoreboard for a Session.

    Staff can view any session. Non-staff need (or needed) a team
    membership in that session.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from organize.models import Session, Team
        session = Session.objects.filter(pk=pk).select_related('game').first()
        if session is None:
            return Response(
                {'detail': 'Session not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not _user_can_see_session(request.user, session):
            return Response(
                {'detail': 'Not your session.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        teams = (
            Team.objects
            .filter(session=session)
            .select_related('group')
            .order_by('name')
        )
        entries = [
            {
                'team_id': t.id,
                'team_name': t.name,
                'team_color': t.color,
                'group_name': t.group.name if t.group else None,
                'group_slug': t.group.slug if t.group else None,
                'locked_score': t.score,
                'floating_score': t.floating_score(),
                'current_score': t.current_score(),
            }
            for t in teams
        ]
        entries.sort(key=lambda e: (-e['current_score'], e['team_name']))
        return Response({
            'session': CurrentSessionSerializer(session).data,
            'entries': entries,
        })


class SessionTimelineView(APIView):
    """Ownership timeline (tower captures) for a Session.

    Returns every TeamTowerOwnership — open and closed — for teams in
    the session, ordered by capture time.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        from game.models import TeamTowerOwnership
        from organize.models import Session
        session = Session.objects.filter(pk=pk).select_related('game').first()
        if session is None:
            return Response(
                {'detail': 'Session not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not _user_can_see_session(request.user, session):
            return Response(
                {'detail': 'Not your session.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        events = (
            TeamTowerOwnership.objects
            .filter(team__session=session)
            .select_related('team', 'tower')
            .order_by('timestamp_start')
        )
        payload = [
            {
                'id': e.id,
                'team_id': e.team_id,
                'team_name': e.team.name,
                'team_color': e.team.color,
                'tower_id': e.tower_id,
                'tower_name': e.tower.name,
                'timestamp_start': e.timestamp_start.isoformat(),
                'timestamp_end': (
                    e.timestamp_end.isoformat() if e.timestamp_end else None
                ),
            }
            for e in events
        ]
        return Response({
            'session': CurrentSessionSerializer(session).data,
            'events': payload,
        })


class CurrentSessionView(APIView):
    """Read / write the authenticated user's active Session.

    GET auto-resolves from the caller's active TeamMemberships when no
    session is set (or the currently-set one is no longer valid):

    - Exactly one active membership on an active session → auto-persist
      and return it.
    - Multiple → return 409 with `candidates` so the UI can show a
      picker.
    - Zero → 404 "You are not in any active session" (unless the caller
      is staff, in which case we fall back to the newest active session
      system-wide so the scoped viewsets still have something to scope
      by).

    POST accepts `{session_id: <int>}`. Non-staff callers must have an
    active membership on a team in that session; staff can pick freely.
    """

    permission_classes = [IsAuthenticated]

    def _candidate_sessions(self, user):
        """Distinct active sessions this user is an active member of.

        "Active" is the derived lifecycle notion: state in
        OPEN_FOR_PARTICIPANTS / RUNNING / PAUSED.
        """
        session_ids = (
            user.profile.memberships
            .filter(
                is_active=True,
                team__session__state__in=Session.ACTIVE_STATES,
            )
            .values_list('team__session_id', flat=True)
            .distinct()
        )
        return list(
            Session.objects
            .filter(id__in=session_ids, state__in=Session.ACTIVE_STATES)
            .select_related('game')
            .order_by('game__name', 'name')
        )

    def _current_still_valid(self, user, session):
        if session is None or not session.is_active:
            return False
        if user.is_staff:
            return True
        if user.profile.memberships.filter(
            is_active=True, team__session=session,
        ).exists():
            return True
        # A teamless player may stay in an "open" session (player team
        # formation enabled) so they can create or browse teams there.
        return effective_allow_player_team_creation(session)

    def _staff_fallback(self):
        return (
            Session.objects
            .filter(state__in=Session.ACTIVE_STATES)
            .select_related('game')
            .order_by('-start_time')
            .first()
        )

    def _persist(self, user, session):
        user.profile.current_session = session
        user.profile.save(update_fields=['current_session'])

    def get(self, request):
        profile = request.user.profile

        if self._current_still_valid(request.user, profile.current_session):
            return Response(
                CurrentSessionSerializer(profile.current_session).data,
            )

        candidates = self._candidate_sessions(request.user)
        if len(candidates) == 1:
            self._persist(request.user, candidates[0])
            return Response(CurrentSessionSerializer(candidates[0]).data)

        if len(candidates) > 1:
            return Response(
                {
                    'detail': 'Multiple active sessions available.',
                    'candidates': CurrentSessionSerializer(
                        candidates, many=True,
                    ).data,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # No memberships. Staff keep a fallback so the scoped viewsets
        # still work; everyone else gets 404.
        if request.user.is_staff:
            fallback = self._staff_fallback()
            if fallback is not None:
                self._persist(request.user, fallback)
                return Response(CurrentSessionSerializer(fallback).data)
        return Response(
            {'detail': 'You are not in any active session.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    def post(self, request):
        session_id = request.data.get('session_id')
        if not session_id:
            return Response(
                {'detail': 'session_id is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        session = (
            Session.objects
            .select_related('game')
            .filter(pk=session_id)
            .first()
        )
        if session is None:
            return Response(
                {'detail': 'Session not found.'},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Players can only set the current session to one they have an
        # active membership in — or an active "open" session (player
        # team formation enabled), so teamless players can go create or
        # join a team there. Staff can switch freely.
        if not request.user.is_staff:
            is_member = request.user.profile.memberships.filter(
                is_active=True, team__session=session,
            ).exists()
            is_open = session.is_active and effective_allow_player_team_creation(session)
            if not is_member and not is_open:
                return Response(
                    {'detail': 'You are not a member of that session.'},
                    status=status.HTTP_403_FORBIDDEN,
                )

        self._persist(request.user, session)
        return Response(CurrentSessionSerializer(session).data)


# ---------- Invites ----------

class InviteSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source='team.name', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default=None)
    status = serializers.SerializerMethodField()

    class Meta:
        model = Invite
        fields = (
            'id', 'token', 'team', 'team_name', 'email', 'kind',
            'created_by', 'created_by_username', 'created_at',
            'expires_at', 'accepted_by', 'accepted_at', 'revoked', 'status',
        )
        read_only_fields = ('token', 'created_by', 'created_at', 'accepted_by', 'accepted_at', 'revoked')

    def get_status(self, invite):
        if invite.revoked:
            return 'revoked'
        if invite.accepted_at is not None:
            return 'accepted'
        if invite.expires_at <= timezone.now():
            return 'expired'
        return 'pending'

    def validate(self, attrs):
        if attrs.get('kind') == Invite.KIND_LINK and not attrs.get('email'):
            raise serializers.ValidationError(
                'A recipient-bound LINK invite requires a recipient email.',
            )
        return attrs


class InvitePreviewSerializer(serializers.Serializer):
    team_name = serializers.CharField()
    team_group = serializers.CharField(allow_blank=True)
    expires_at = serializers.DateTimeField()
    kind = serializers.CharField()
    recipient_bound = serializers.BooleanField()


class InviteAcceptSerializer(serializers.Serializer):
    # Only used when accepting as a new user. Authenticated users skip these.
    username = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False)
    password = serializers.CharField(write_only=True, min_length=8, required=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)


class InviteCreatePermission(BasePermission):
    """Staff everywhere; authenticated players may POST (INVITER power /
    captaincy) — object-checked in `perform_create` against
    `_can_manage_team_invites`, which admits staff, the team captain
    while player team formation is enabled, and holders of a role with
    `builtin_power=INVITER`.

    Listing stays staff-or-captain: a team captain may GET (get_queryset
    scopes their listing to teams they captain); other non-staff players
    are rejected outright.
    """

    def has_permission(self, request, view):
        user = request.user
        if user is None or not user.is_authenticated:
            return False
        if user.is_staff:
            return True
        if request.method not in SAFE_METHODS:
            return True
        return Team.objects.filter(captain=user).exists()


class InviteListCreate(SessionScopedViewSetMixin, generics.ListCreateAPIView):
    """List/create invites.

    Staff manage every invite in their current session. A team captain
    manages their own team's invites while player team formation is
    enabled for that session (see the team-formation capability). A
    role-based INVITER power can plug into `_can_manage_team_invites`
    when team-roles-as-mechanics lands.
    """

    serializer_class = InviteSerializer
    permission_classes = [InviteCreatePermission]
    queryset = Invite.objects.select_related('team', 'created_by', 'accepted_by')
    # Invites are scoped through the team's session. Staff viewing one
    # session's roster will not see invites intended for another
    # session (or another game entirely).
    session_scope_field = 'team__session'

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.user.is_staff:
            qs = qs.filter(team__captain=self.request.user)
        status_filter = self.request.query_params.get('status')
        now = timezone.now()
        if status_filter == 'pending':
            qs = qs.filter(revoked=False, accepted_at__isnull=True, expires_at__gt=now)
        elif status_filter == 'accepted':
            qs = qs.filter(accepted_at__isnull=False)
        elif status_filter == 'revoked':
            qs = qs.filter(revoked=True)
        elif status_filter == 'expired':
            qs = qs.filter(revoked=False, accepted_at__isnull=True, expires_at__lte=now)
        return qs

    def perform_create(self, serializer):
        team = serializer.validated_data['team']
        if not _can_manage_team_invites(self.request.user, team):
            raise PermissionDenied(
                'Only staff, the team captain while player team formation '
                'is enabled, or a holder of an INVITER role may create '
                'invites for this team.',
            )
        invite = serializer.save(created_by=self.request.user)
        if invite.email:
            send_invite_email(invite)


class InviteDestroy(generics.DestroyAPIView):
    """Revoke a pending invite (soft-delete via revoked=True)."""
    permission_classes = [IsAuthenticated]
    queryset = Invite.objects.select_related('team__session__game')

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.user.is_staff:
            qs = qs.filter(team__captain=self.request.user)
        return qs

    def perform_destroy(self, invite):
        if not _can_manage_team_invites(self.request.user, invite.team):
            raise PermissionDenied(
                'Only staff, or the team captain while player team '
                'formation is enabled, may revoke this invite.',
            )
        invite.revoked = True
        invite.save(update_fields=['revoked'])


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def invite_resend(request, pk):
    invite = get_object_or_404(
        Invite.objects.select_related('team__session__game'), pk=pk,
    )
    if not _can_manage_team_invites(request.user, invite.team):
        return Response(
            {'detail': 'You may not manage invites for this team.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not invite.is_usable():
        return Response(
            {'detail': 'Invite is not in a resendable state.'},
            status=status.HTTP_410_GONE,
        )
    if not invite.email:
        return Response(
            {'detail': 'Invite has no email address to resend to.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    send_invite_email(invite)
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(['GET'])
@permission_classes([AllowAny])
def invite_preview(request, token):
    invite = get_object_or_404(Invite, token=token)
    if not invite.is_usable():
        return Response(
            {'detail': 'Invite is no longer usable.'}, status=status.HTTP_410_GONE,
        )
    data = {
        'team_name': invite.team.name,
        'team_group': invite.team.group.name if invite.team.group else '',
        'expires_at': invite.expires_at,
        'kind': invite.kind,
        'recipient_bound': invite.is_recipient_bound(),
    }
    return Response(InvitePreviewSerializer(data).data)


@api_view(['POST'])
@permission_classes([AllowAny])
@transaction.atomic
def invite_accept(request, token):
    invite = (
        Invite.objects
        .select_for_update()
        .select_related('team')
        .filter(token=token)
        .first()
    )
    if invite is None:
        return Response({'detail': 'Invite not found.'}, status=status.HTTP_404_NOT_FOUND)
    if not invite.is_usable():
        return Response({'detail': 'Invite is no longer usable.'}, status=status.HTTP_410_GONE)

    # Session lifecycle roster gating: joining is closed while the
    # session is DRAFT or FINISHED (rosters form once participation
    # opens; see the session-lifecycle capability).
    invite_session = invite.team.session
    if not invite_session.accepts_roster_changes():
        return Response(
            {
                'detail': (
                    'This session is not accepting participants right now '
                    f'(state: {invite_session.state}).'
                ),
            },
            status=status.HTTP_409_CONFLICT,
        )

    bound_email = invite.email if invite.is_recipient_bound() else None

    if request.user.is_authenticated:
        # Recipient binding: a LINK invite may only be accepted by the
        # account whose email matches the bound recipient (403 so a
        # forwarded link cannot be redeemed by someone else).
        if bound_email and request.user.email.lower() != bound_email.lower():
            return Response(
                {'detail': 'This invite link is bound to a different recipient.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        user = request.user
    else:
        serializer = InviteAcceptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        required = ('username', 'email', 'password')
        missing = [f for f in required if not data.get(f)]
        if missing:
            return Response(
                {'detail': f'Missing required fields: {", ".join(missing)}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        # Recipient binding for fresh registrations: the new account must
        # be registered on the bound email itself.
        if bound_email and data['email'].lower() != bound_email.lower():
            return Response(
                {'detail': 'This invite link is bound to a different recipient.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        if User.objects.filter(username__iexact=data['username']).exists():
            return Response(
                {'detail': 'Username already taken.'}, status=status.HTTP_400_BAD_REQUEST,
            )
        if User.objects.filter(email__iexact=data['email']).exists():
            return Response(
                {'detail': 'Email already registered.'}, status=status.HTTP_400_BAD_REQUEST,
            )
        user = User.objects.create_user(
            username=data['username'],
            email=data['email'],
            password=data['password'],
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
        )

    # One active membership per game per player. Surface a friendly 409
    # before letting the DB constraint trip.
    invite_game = invite.team.session.game
    existing = active_membership_conflict(user.profile, invite.team)
    if existing is not None:
        return _membership_conflict_response(existing, invite_game)

    # Join-cap: never grow a team past the effective max_members_per_team
    # (0 = no cap). Re-accepting while already on the team is fine.
    # Raised (not returned) so the surrounding atomic block rolls back
    # any account created above for an anonymous acceptor. The actual
    # membership (or pending join request) is created below by the
    # confirmation-policy routing.
    already_member = TeamMembership.objects.filter(
        team=invite.team, user=user.profile, is_active=True,
    ).exists()
    max_members = invite.team.session.effective('max_members_per_team')
    if (
        not already_member
        and max_members
        and invite.team.active_member_count() >= max_members
    ):
        raise TeamFullError(
            f'Team "{invite.team.name}" is already at its maximum of '
            f'{max_members} member(s).',
        )

    invite.accepted_by = user
    invite.accepted_at = timezone.now()
    invite.save(update_fields=['accepted_by', 'accepted_at'])

    # Route through the team's effective confirmation policy: membership
    # right away under AUTO_APPROVE, else a pending join request that a
    # captain or staff must approve (see the team-formation capability).
    policy = effective_team_join_confirmation(invite.team)
    if policy == JOIN_CONFIRM_AUTO_APPROVE:
        TeamMembership.objects.get_or_create(
            team=invite.team, user=user.profile, is_active=True,
        )
        membership_status = 'ACTIVE'
        join_request_id = None
    else:
        source = (
            TeamJoinRequest.SOURCE_LINK
            if invite.kind == Invite.KIND_LINK
            else TeamJoinRequest.SOURCE_QR
        )
        join_request, _ = TeamJoinRequest.objects.get_or_create(
            team=invite.team,
            user=user.profile,
            status=TeamJoinRequest.STATUS_PENDING,
            defaults={'source': source},
        )
        membership_status = 'PENDING'
        join_request_id = join_request.id

    token_obj, _ = Token.objects.get_or_create(user=user)
    return Response({
        'token': token_obj.key,
        'user_id': user.id,
        'username': user.username,
        'team_id': invite.team.id,
        'team_name': invite.team.name,
        'membership_status': membership_status,
        'join_request_id': join_request_id,
    })


# ---------- Team formation: join codes, browsing, join requests ----------

class TeamJoinRequestSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source='team.name', read_only=True)
    username = serializers.CharField(source='user.user.username', read_only=True)
    first_name = serializers.CharField(source='user.user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.user.last_name', read_only=True)
    decided_by_username = serializers.CharField(
        source='decided_by.username', read_only=True, default=None,
    )

    class Meta:
        model = TeamJoinRequest
        fields = (
            'id', 'team', 'team_name', 'username', 'first_name', 'last_name',
            'status', 'source', 'note', 'requested_at',
            'decided_by_username', 'decided_at',
        )
        read_only_fields = fields


def _join_code_payload(team):
    code = str(team.join_code) if team.join_code else None
    return {
        'team': team.id,
        'team_name': team.name,
        'join_code': code,
        'join_url': f'{settings.BASE_URL}/join/{code}' if code else None,
    }


class TeamJoinCodeView(APIView):
    """Read / rotate / revoke a team's untied, shareable join code.

    Captain-of-that-team or staff only. The code is untied — anyone
    holding it may use it while set — so rotating invalidates every
    previously shared copy at once.
    """

    permission_classes = [IsAuthenticated]

    def _team(self, request, pk):
        team = get_object_or_404(Team.objects.select_related('session__game'), pk=pk)
        if not (request.user.is_staff or team.captain_id == request.user.id):
            raise PermissionDenied(
                'Only the team captain or staff may manage the join code.',
            )
        return team

    def get(self, request, pk):
        return Response(_join_code_payload(self._team(request, pk)))

    def post(self, request, pk):
        team = self._team(request, pk)
        action = request.data.get('action', 'rotate')
        if action == 'rotate':
            team.rotate_join_code()
        elif action == 'revoke':
            team.revoke_join_code()
        else:
            return Response(
                {'detail': 'action must be "rotate" or "revoke".'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_join_code_payload(team))


def _joinable_team_entry(team, profile):
    my_request = (
        team.join_requests.filter(user=profile).order_by('-requested_at').first()
        if profile is not None else None
    )
    return {
        'id': team.id,
        'name': team.name,
        'color': team.color,
        'group_name': team.group.name if team.group else None,
        'member_count': team.memberships.filter(is_active=True).count(),
        'join_confirmation': effective_team_join_confirmation(team),
        'my_request_status': my_request.status if my_request else None,
    }


@api_view(['GET'])
@permission_classes([AllowAny])
def join_code_preview(request, code):
    """Public preview for the untied join QR/link (pre-login rendering)."""
    team = (
        Team.objects
        .filter(join_code=code)
        .select_related('session__game', 'group')
        .first()
    )
    if team is None:
        return Response(
            {'detail': 'Invalid or revoked join code.'},
            status=status.HTTP_404_NOT_FOUND,
        )
    return Response({
        'team_name': team.name,
        'team_group': team.group.name if team.group else '',
        'color': team.color,
        'session_name': team.session.name,
        'game_name': team.session.game.name,
        'join_confirmation': effective_team_join_confirmation(team),
    })


class JoinableTeamsView(APIView):
    """Teams in the caller's current Session that they may request to join."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        session = profile.current_session
        if session is None:
            return Response(
                {'detail': 'You are not in any session.'},
                status=status.HTTP_404_NOT_FOUND,
            )
        if not request.user.is_staff and not effective_allow_player_team_creation(session):
            return Response(
                {'detail': 'Player team formation is not enabled for this session.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        teams = (
            Team.objects
            .filter(session=session)
            .exclude(memberships__user=profile, memberships__is_active=True)
            .select_related('group', 'session__game')
            .order_by('name')
        )
        return Response([_joinable_team_entry(t, profile) for t in teams])


class JoinRequestListCreateView(APIView):
    """GET: requests the caller may see. POST: request to join a team.

    Visibility: a player sees their own requests, a captain additionally
    their team's, staff see every request in their current session.

    POST accepts either `{team: <id>}` (source BROWSE, current-session
    teams only) or `{code: <uuid>}` (source QR, resolved from the team's
    untied join code). The team's effective confirmation policy decides
    between immediate membership (AUTO_APPROVE) and a pending request.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = request.user.profile
        qs = TeamJoinRequest.objects.select_related(
            'team', 'user__user', 'decided_by',
        )
        if request.user.is_staff:
            session = profile.current_session
            if session is None:
                qs = qs.none()
            else:
                qs = qs.filter(team__session=session)
        else:
            qs = qs.filter(
                Q(user=profile) | Q(team__captain=request.user),
            )
        status_filter = request.query_params.get('status')
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        qs = qs.order_by('-requested_at')
        return Response(TeamJoinRequestSerializer(qs, many=True).data)

    @transaction.atomic
    def post(self, request):
        profile = request.user.profile
        code = request.data.get('code')
        team_id = request.data.get('team')

        if code:
            team = (
                Team.objects
                .filter(join_code=code)
                .select_related('session__game')
                .first()
            )
            if team is None:
                return Response(
                    {'detail': 'Invalid or revoked join code.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            source = TeamJoinRequest.SOURCE_QR
        elif team_id:
            session = profile.current_session
            if session is None:
                return Response(
                    {'detail': 'You are not in any session.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            if not effective_allow_player_team_creation(session):
                return Response(
                    {'detail': 'Player team formation is not enabled for this session.'},
                    status=status.HTTP_403_FORBIDDEN,
                )
            team = (
                Team.objects
                .filter(pk=team_id, session=session)
                .select_related('session__game')
                .first()
            )
            if team is None:
                return Response(
                    {'detail': 'Team not found in your current session.'},
                    status=status.HTTP_404_NOT_FOUND,
                )
            source = TeamJoinRequest.SOURCE_BROWSE
        else:
            return Response(
                {'detail': 'Provide either "team" or "code".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if TeamMembership.objects.filter(
            team=team, user=profile, is_active=True,
        ).exists():
            return Response(
                {'detail': 'You are already a member of this team.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        conflict = active_membership_conflict(profile, team)
        if conflict is not None:
            return _membership_conflict_response(conflict, team.session.game)

        note = request.data.get('note') or ''
        policy = effective_team_join_confirmation(team)
        if policy == JOIN_CONFIRM_AUTO_APPROVE:
            join_request = TeamJoinRequest.objects.create(
                team=team, user=profile, source=source, note=note,
                status=TeamJoinRequest.STATUS_APPROVED,
                decided_at=timezone.now(),
            )
            TeamMembership.objects.get_or_create(
                team=team, user=profile, is_active=True,
            )
            # Joining a team drops the player into its session.
            if profile.current_session_id != team.session_id:
                profile.current_session = team.session
                profile.save(update_fields=['current_session'])
            created = True
        else:
            join_request, created = TeamJoinRequest.objects.get_or_create(
                team=team,
                user=profile,
                status=TeamJoinRequest.STATUS_PENDING,
                defaults={'source': source, 'note': note},
            )
        return Response(
            TeamJoinRequestSerializer(join_request).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def join_request_approve(request, pk):
    join_request = get_object_or_404(
        TeamJoinRequest.objects
        .select_for_update()
        .select_related('team__session__game', 'user'),
        pk=pk,
    )
    if not _can_decide_join_request(request.user, join_request.team):
        return Response(
            {'detail': 'Only the team captain or staff may decide this request.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    if join_request.status != TeamJoinRequest.STATUS_PENDING:
        return Response(
            {'detail': 'This request has already been decided.'},
            status=status.HTTP_409_CONFLICT,
        )
    conflict = active_membership_conflict(join_request.user, join_request.team)
    if conflict is not None:
        return Response(
            {
                'detail': (
                    f'{join_request.user.user.get_username()} is already on team '
                    f'"{conflict.team.name}" in '
                    f'"{join_request.team.session.game.name}". They must leave '
                    'that team before joining another in the same game.'
                ),
            },
            status=status.HTTP_409_CONFLICT,
        )
    join_request.approve(decided_by=request.user)
    return Response(TeamJoinRequestSerializer(join_request).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def join_request_reject(request, pk):
    join_request = get_object_or_404(
        TeamJoinRequest.objects
        .select_for_update()
        .select_related('team__session__game', 'user'),
        pk=pk,
    )
    if not _can_decide_join_request(request.user, join_request.team):
        return Response(
            {'detail': 'Only the team captain or staff may decide this request.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    if join_request.status != TeamJoinRequest.STATUS_PENDING:
        return Response(
            {'detail': 'This request has already been decided.'},
            status=status.HTTP_409_CONFLICT,
        )
    join_request.reject(decided_by=request.user)
    return Response(TeamJoinRequestSerializer(join_request).data)
