from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import generics, serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from game.scoping import SessionScopedViewSetMixin
from organize.emails import send_invite_email
from organize.models import Invite, TeamMembership

User = get_user_model()


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
    is_staff = serializers.BooleanField(source='user.is_staff', read_only=True)

    def get_current_game(self, profile):
        session = profile.current_session
        return session.game_id if session is not None else None

    def get_active_team_id(self, profile):
        membership = profile.memberships.filter(is_active=True).select_related('team').first()
        return membership.team_id if membership else None

    def update(self, profile, validated_data):
        user_data = validated_data.pop('user', {})
        for field, value in user_data.items():
            setattr(profile.user, field, value)
        profile.user.save()
        return profile


class TeamMemberSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(source='user.user.id')
    username = serializers.CharField(source='user.user.username')
    first_name = serializers.CharField(source='user.user.first_name')
    last_name = serializers.CharField(source='user.user.last_name')
    joined_at = serializers.DateTimeField()


class MyTeamSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    code = serializers.CharField()
    color = serializers.CharField()
    score = serializers.IntegerField()
    current_score = serializers.SerializerMethodField()
    members = serializers.SerializerMethodField()

    def get_current_score(self, team):
        return team.current_score()

    def get_members(self, team):
        active = team.memberships.filter(is_active=True).select_related('user__user')
        return TeamMemberSerializer(active, many=True).data


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
        return Response(MyTeamSerializer(membership.team).data)


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

    def get_base_point(self, game):
        if game.base_point is None:
            return None
        return {
            'type': 'Point',
            'coordinates': [game.base_point.x, game.base_point.y],
        }


class CurrentSessionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()
    is_active = serializers.BooleanField()
    start_time = serializers.DateTimeField()
    end_time = serializers.DateTimeField()
    game = GameConfigSerializer()


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
        """Distinct sessions this user is an active member of."""
        from organize.models import Session
        session_ids = (
            user.profile.memberships
            .filter(is_active=True, team__session__is_active=True)
            .values_list('team__session_id', flat=True)
            .distinct()
        )
        return list(
            Session.objects
            .filter(id__in=session_ids, is_active=True)
            .select_related('game')
            .order_by('game__name', 'name')
        )

    def _current_still_valid(self, user, session):
        if session is None or not session.is_active:
            return False
        if user.is_staff:
            return True
        return user.profile.memberships.filter(
            is_active=True, team__session=session,
        ).exists()

    def _staff_fallback(self):
        from organize.models import Session
        return (
            Session.objects
            .filter(is_active=True)
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
        from organize.models import Session
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
        # active membership in. Staff can switch freely.
        if not request.user.is_staff:
            is_member = request.user.profile.memberships.filter(
                is_active=True, team__session=session,
            ).exists()
            if not is_member:
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
            'id', 'token', 'team', 'team_name', 'email',
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


class InvitePreviewSerializer(serializers.Serializer):
    team_name = serializers.CharField()
    team_group = serializers.CharField(allow_blank=True)
    expires_at = serializers.DateTimeField()


class InviteAcceptSerializer(serializers.Serializer):
    # Only used when accepting as a new user. Authenticated users skip these.
    username = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(required=False)
    password = serializers.CharField(write_only=True, min_length=8, required=False)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)


class InviteListCreate(SessionScopedViewSetMixin, generics.ListCreateAPIView):
    serializer_class = InviteSerializer
    permission_classes = [IsAdminUser]
    queryset = Invite.objects.select_related('team', 'created_by', 'accepted_by')
    # Invites are scoped through the team's session. Staff viewing one
    # session's roster will not see invites intended for another
    # session (or another game entirely).
    session_scope_field = 'team__session'

    def get_queryset(self):
        qs = super().get_queryset()
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
        invite = serializer.save(created_by=self.request.user)
        if invite.email:
            send_invite_email(invite)


class InviteDestroy(generics.DestroyAPIView):
    """Revoke a pending invite (soft-delete via revoked=True)."""
    permission_classes = [IsAdminUser]
    queryset = Invite.objects.all()

    def perform_destroy(self, invite):
        invite.revoked = True
        invite.save(update_fields=['revoked'])


@api_view(['POST'])
@permission_classes([IsAdminUser])
def invite_resend(request, pk):
    invite = get_object_or_404(Invite, pk=pk)
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

    if request.user.is_authenticated:
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
    existing = (
        TeamMembership.objects
        .filter(user=user.profile, is_active=True, game=invite_game)
        .exclude(team=invite.team)
        .select_related('team')
        .first()
    )
    if existing is not None:
        return Response(
            {
                'detail': (
                    f'You are already on team "{existing.team.name}" in '
                    f'"{invite_game.name}". Leave that team before joining '
                    'another in the same game.'
                ),
            },
            status=status.HTTP_409_CONFLICT,
        )

    membership, _ = TeamMembership.objects.get_or_create(
        team=invite.team, user=user.profile, is_active=True,
    )
    invite.accepted_by = user
    invite.accepted_at = timezone.now()
    invite.save(update_fields=['accepted_by', 'accepted_at'])

    token_obj, _ = Token.objects.get_or_create(user=user)
    return Response({
        'token': token_obj.key,
        'user_id': user.id,
        'username': user.username,
        'team_id': invite.team.id,
        'team_name': invite.team.name,
    })
