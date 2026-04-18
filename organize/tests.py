"""Tests for organize app: account models, auth endpoints, me/my-team."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from organize.models import (
    Game,
    Invite,
    Team,
    TeamMembership,
    UserProfile,
)

User = get_user_model()


def _make_game(name='Game A'):
    now = timezone.now()
    return Game.objects.create(
        name=name,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )


def _make_team(game, name='Lynx', code='LYNX'):
    return Team.objects.create(name=name, game=game, code=code, color='#ff0000')


class UserProfileSignalTest(TestCase):
    def test_profile_auto_created_on_user_creation(self):
        user = User.objects.create_user(username='sam', email='sam@example.com', password='password123')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_profile_not_duplicated_on_save(self):
        user = User.objects.create_user(username='sam', email='sam@example.com', password='password123')
        user.first_name = 'Sam'
        user.save()
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)


class RegisterTest(TestCase):
    url = reverse('api-auth-register')

    def test_register_creates_user_and_returns_token(self):
        resp = self.client.post(self.url, {
            'username': 'alex',
            'email': 'alex@example.com',
            'password': 'secret12345',
            'first_name': 'Alex',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertIn('token', resp.json())
        user = User.objects.get(username='alex')
        self.assertTrue(UserProfile.objects.filter(user=user).exists())
        self.assertTrue(Token.objects.filter(user=user).exists())

    def test_register_rejects_duplicate_username(self):
        User.objects.create_user(username='taken', email='a@b.com', password='password123')
        resp = self.client.post(self.url, {
            'username': 'taken', 'email': 'other@b.com', 'password': 'secret12345',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_register_rejects_duplicate_email(self):
        User.objects.create_user(username='first', email='dup@example.com', password='password123')
        resp = self.client.post(self.url, {
            'username': 'second', 'email': 'dup@example.com', 'password': 'secret12345',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_register_rejects_short_password(self):
        resp = self.client.post(self.url, {
            'username': 'x', 'email': 'x@y.com', 'password': 'abc',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class LoginTest(TestCase):
    url = reverse('api-auth-login')

    def setUp(self):
        self.user = User.objects.create_user(
            username='jordan', email='jordan@example.com', password='password123',
        )

    def test_login_with_username(self):
        resp = self.client.post(
            self.url, {'login': 'jordan', 'password': 'password123'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.json())

    def test_login_with_email(self):
        resp = self.client.post(
            self.url, {'login': 'jordan@example.com', 'password': 'password123'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

    def test_login_wrong_password(self):
        resp = self.client.post(
            self.url, {'login': 'jordan', 'password': 'wrong'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)

    def test_login_unknown_user(self):
        resp = self.client.post(
            self.url, {'login': 'nobody', 'password': 'password123'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 401)


class LogoutTest(TestCase):
    def test_logout_invalidates_token(self):
        user = User.objects.create_user(username='ali', email='ali@x.com', password='password123')
        token = Token.objects.create(user=user)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        resp = client.post(reverse('api-auth-logout'))
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Token.objects.filter(user=user).exists())

    def test_logout_requires_auth(self):
        resp = self.client.post(reverse('api-auth-logout'))
        # DRF returns 403 for unauthenticated requests when no auth header is sent
        # (reserves 401 for requests that present credentials that fail to validate).
        self.assertEqual(resp.status_code, 403)


class PasswordResetRequestTest(TestCase):
    url = reverse('api-password-reset')

    def test_request_sends_email_when_user_exists(self):
        User.objects.create_user(username='kai', email='kai@example.com', password='password123')
        resp = self.client.post(self.url, {'email': 'kai@example.com'}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('kai@example.com', mail.outbox[0].to)

    def test_request_is_silent_when_user_missing(self):
        resp = self.client.post(self.url, {'email': 'nobody@example.com'}, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)


class PasswordResetConfirmTest(TestCase):
    url = reverse('api-password-reset-confirm')

    def setUp(self):
        self.user = User.objects.create_user(
            username='lee', email='lee@example.com', password='oldpassword123',
        )
        self.uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.token = default_token_generator.make_token(self.user)

    def test_confirm_sets_new_password_and_invalidates_tokens(self):
        Token.objects.create(user=self.user)
        resp = self.client.post(self.url, {
            'uid': self.uid, 'token': self.token, 'new_password': 'brandnewpassword',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('brandnewpassword'))
        self.assertFalse(Token.objects.filter(user=self.user).exists())

    def test_confirm_rejects_invalid_token(self):
        resp = self.client.post(self.url, {
            'uid': self.uid, 'token': 'bogus', 'new_password': 'brandnewpassword',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_confirm_rejects_invalid_uid(self):
        resp = self.client.post(self.url, {
            'uid': 'XXXX', 'token': self.token, 'new_password': 'brandnewpassword',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 400)


class MeEndpointTest(TestCase):
    url = reverse('api-me')

    def setUp(self):
        self.user = User.objects.create_user(
            username='mo', email='mo@example.com', password='password123',
            first_name='Mo', last_name='Khan',
        )
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')

    def test_get_me_returns_profile(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['username'], 'mo')
        self.assertEqual(data['email'], 'mo@example.com')
        self.assertIsNone(data['active_team_id'])
        self.assertFalse(data['is_staff'])

    def test_get_me_exposes_active_team(self):
        game = _make_game()
        team = _make_team(game)
        TeamMembership.objects.create(team=team, user=self.user.profile, is_active=True)
        resp = self.client.get(self.url)
        self.assertEqual(resp.json()['active_team_id'], team.id)

    def test_patch_me_updates_user_fields(self):
        resp = self.client.patch(
            self.url, {'first_name': 'Moira'}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, 'Moira')

    def test_me_requires_auth(self):
        anon = APIClient()
        self.assertEqual(anon.get(self.url).status_code, 403)


class MyTeamEndpointTest(TestCase):
    url = reverse('api-my-team')

    def setUp(self):
        self.user = User.objects.create_user(username='nadia', email='n@x.com', password='password123')
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        self.game = _make_game()
        self.team = _make_team(self.game)

    def test_returns_team_when_user_is_member(self):
        TeamMembership.objects.create(team=self.team, user=self.user.profile, is_active=True)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['id'], self.team.id)
        self.assertEqual(len(data['members']), 1)

    def test_returns_404_when_user_has_no_team(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 404)

    def test_ignores_inactive_memberships(self):
        TeamMembership.objects.create(
            team=self.team, user=self.user.profile, is_active=False, left_at=timezone.now(),
        )
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 404)


class InviteModelTest(TestCase):
    def setUp(self):
        self.game = _make_game()
        self.team = _make_team(self.game)
        self.creator = User.objects.create_user(username='c', email='c@x.com', password='password123')

    def test_default_expiry_is_two_weeks(self):
        invite = Invite.objects.create(team=self.team, email='a@b.com', created_by=self.creator)
        delta = invite.expires_at - invite.created_at
        self.assertGreater(delta, timedelta(days=13))
        self.assertLess(delta, timedelta(days=15))

    def test_is_usable_true_for_fresh_invite(self):
        invite = Invite.objects.create(team=self.team, email='a@b.com', created_by=self.creator)
        self.assertTrue(invite.is_usable())

    def test_is_usable_false_when_revoked(self):
        invite = Invite.objects.create(team=self.team, email='a@b.com', created_by=self.creator, revoked=True)
        self.assertFalse(invite.is_usable())

    def test_is_usable_false_when_expired(self):
        invite = Invite.objects.create(
            team=self.team, email='a@b.com', created_by=self.creator,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.assertFalse(invite.is_usable())

    def test_is_usable_false_when_accepted(self):
        invite = Invite.objects.create(
            team=self.team, email='a@b.com', created_by=self.creator,
            accepted_by=self.creator, accepted_at=timezone.now(),
        )
        self.assertFalse(invite.is_usable())
