from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import serializers, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from organize.models import TeamMembership

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
    current_game = serializers.PrimaryKeyRelatedField(read_only=True)
    active_team_id = serializers.SerializerMethodField()
    is_staff = serializers.BooleanField(source='user.is_staff', read_only=True)

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
