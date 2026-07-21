"""Tests for organize app: account models, auth endpoints, me/my-team."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from organize.models import (
    BUILTIN_POWER_INVITER,
    Game,
    GameRole,
    Invite,
    Session,
    Team,
    TeamMembership,
    TeamRole,
    UserProfile,
    user_can_invite_to_team,
)

User = get_user_model()


def _make_game(name='Game A', slug=None):
    if slug is None:
        from django.utils.text import slugify
        base = slugify(name) or 'game'
        slug, counter = base, 2
        while Game.objects.filter(slug=slug).exists():
            slug = f'{base}-{counter}'
            counter += 1
    return Game.objects.create(name=name, slug=slug)


def _default_session(game):
    """Create-or-get the default Session, RUNNING so joins/scoring work."""
    session = Session.objects.filter(game=game, slug='default').first()
    if session is None:
        now = timezone.now()
        session = Session.objects.create(
            game=game,
            slug='default',
            name='Default session',
            start_time=now,
            end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
    return session


def _make_team(game, name='Lynx'):
    return Team.objects.create(
        name=name,
        session=_default_session(game),
        color='#ff0000',
    )


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

    def test_exposes_readiness_fields(self):
        session = self.team.session
        session.min_members_per_team = 3
        session.save()
        TeamMembership.objects.create(team=self.team, user=self.user.profile, is_active=True)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['active_member_count'], 1)
        self.assertFalse(data['is_ready'])
        self.assertEqual(data['members_needed'], 2)


class TeamMembershipUniquenessTest(TestCase):
    """P3.4 — one active membership per (user, game), across sessions."""

    def setUp(self):
        from organize.models import Session
        self.game = _make_game()
        now = timezone.now()
        self.session_a = Session.objects.create(
            game=self.game, slug='morning', name='Morning',
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
        self.session_b = Session.objects.create(
            game=self.game, slug='afternoon', name='Afternoon',
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=4),
            state=Session.RUNNING,
        )
        self.team_a = Team.objects.create(
            name='a', session=self.session_a, color='#111',
        )
        self.team_b = Team.objects.create(
            name='b', session=self.session_b, color='#222',
        )
        self.user = User.objects.create_user(
            username='scout', email='s@x.com', password='password123',
        )

    def test_save_denormalises_game_from_session(self):
        membership = TeamMembership.objects.create(
            team=self.team_a, user=self.user.profile, is_active=True,
        )
        self.assertEqual(membership.game_id, self.game.id)

    def test_second_active_membership_on_same_game_blocked(self):
        from django.db import IntegrityError
        TeamMembership.objects.create(
            team=self.team_a, user=self.user.profile, is_active=True,
        )
        with self.assertRaises(IntegrityError):
            TeamMembership.objects.create(
                team=self.team_b, user=self.user.profile, is_active=True,
            )

    def test_inactive_memberships_do_not_collide(self):
        """An archived (left) team doesn't block a new active one."""
        TeamMembership.objects.create(
            team=self.team_a,
            user=self.user.profile,
            is_active=False,
            left_at=timezone.now(),
        )
        # Now the user can join team_b in the same game, actively.
        new_m = TeamMembership.objects.create(
            team=self.team_b, user=self.user.profile, is_active=True,
        )
        self.assertEqual(new_m.game_id, self.game.id)

    def test_active_memberships_across_different_games_ok(self):
        from organize.models import Session
        other_game = _make_game(name='Other', slug='other')
        now = timezone.now()
        other_session = Session.objects.create(
            game=other_game, slug='default', name='O',
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
        other_team = Team.objects.create(
            name='o', session=other_session, color='#333',
        )
        TeamMembership.objects.create(
            team=self.team_a, user=self.user.profile, is_active=True,
        )
        # Second active membership on a different game — must succeed.
        TeamMembership.objects.create(
            team=other_team, user=self.user.profile, is_active=True,
        )
        self.assertEqual(
            TeamMembership.objects
            .filter(user=self.user.profile, is_active=True)
            .count(),
            2,
        )


class SessionModelTest(TestCase):
    def setUp(self):
        self.game = _make_game()

    def test_can_host_multiple_sessions_per_game(self):
        now = timezone.now()
        s1 = Session.objects.create(
            game=self.game, slug='morning', name='Morning',
            start_time=now, end_time=now + timedelta(hours=2),
            state=Session.RUNNING,
        )
        s2 = Session.objects.create(
            game=self.game, slug='afternoon', name='Afternoon',
            start_time=now + timedelta(hours=3),
            end_time=now + timedelta(hours=5),
            state=Session.RUNNING,
        )
        self.assertEqual(self.game.sessions.count(), 2)
        self.assertNotEqual(s1.pk, s2.pk)

    def test_session_slug_unique_per_game_not_global(self):
        from django.db import IntegrityError

        from organize.models import Session

        other_game = _make_game(name='Other', slug='other')
        now = timezone.now()
        Session.objects.create(
            game=self.game, slug='default', name='A',
            start_time=now, end_time=now + timedelta(hours=1),
        )
        # Same slug, different game — OK.
        Session.objects.create(
            game=other_game, slug='default', name='B',
            start_time=now, end_time=now + timedelta(hours=1),
        )
        # Same slug, same game — IntegrityError.
        with self.assertRaises(IntegrityError):
            Session.objects.create(
                game=self.game, slug='default', name='A-dup',
                start_time=now, end_time=now + timedelta(hours=1),
            )


class TeamSessionReparentingTest(TestCase):
    def test_team_attaches_to_session_and_game_is_derived(self):
        game = _make_game()
        team = _make_team(game)
        # _make_team auto-creates a default session for this game.
        self.assertIsNotNone(team.session)
        self.assertEqual(team.session.game, game)
        # The convenience accessor also works.
        self.assertEqual(team.game, game)

    def test_two_sessions_same_game_keep_separate_teams(self):
        from organize.models import Session, Team
        game = _make_game()
        now = timezone.now()
        session_a = Session.objects.create(
            game=game, slug='A', name='A',
            start_time=now, end_time=now + timedelta(hours=1),
        )
        session_b = Session.objects.create(
            game=game, slug='B', name='B',
            start_time=now, end_time=now + timedelta(hours=1),
        )
        Team.objects.create(
            name='a-team', session=session_a, color='#111',
        )
        Team.objects.create(
            name='b-team', session=session_b, color='#222',
        )
        self.assertEqual(session_a.teams.count(), 1)
        self.assertEqual(session_b.teams.count(), 1)
        self.assertNotEqual(
            session_a.teams.first(), session_b.teams.first(),
        )


class CurrentSessionTest(TestCase):
    url = reverse('api-current-session')

    def setUp(self):
        from organize.models import Session
        self.user = User.objects.create_user(
            username='tester', email='t@x.com', password='password123',
        )
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

        self.game = _make_game(name='Live', slug='live')
        self.game.is_active = True
        self.game.save()
        now = timezone.now()
        self.session = Session.objects.create(
            game=self.game, slug='default', name='Live default',
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
        # Give the tester an active membership so the auto-resolver has
        # a candidate. Dedicated tests below cover the 0- and multi-
        # membership paths.
        self.team = _make_team(self.game)
        self.team.session = self.session
        self.team.save()
        TeamMembership.objects.create(
            team=self.team, user=self.user.profile, is_active=True,
        )

    def test_requires_auth(self):
        anon = APIClient()
        resp = anon.get(self.url)
        self.assertIn(resp.status_code, (401, 403))

    def test_get_auto_resolves_single_membership(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['id'], self.session.id)
        self.assertEqual(body['slug'], 'default')
        # Nested game config has the full shape.
        self.assertEqual(body['game']['id'], self.game.id)
        self.assertEqual(body['game']['slug'], 'live')
        self.assertEqual(body['game']['proximity_meters'], 50)
        self.assertEqual(body['game']['cooloff_minutes'], 5)
        # Auto-persist: calling again reads from profile.current_session.
        self.user.profile.refresh_from_db()
        self.assertEqual(
            self.user.profile.current_session_id, self.session.id,
        )

    def test_get_404_when_no_active_session(self):
        self.session.state = Session.FINISHED
        self.session.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 404)

    def test_post_sets_current_session_on_profile(self):
        resp = self.client.post(
            self.url,
            {'session_id': self.session.id},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.user.profile.refresh_from_db()
        self.assertEqual(
            self.user.profile.current_session_id, self.session.id,
        )

    def test_post_404_for_unknown_session(self):
        resp = self.client.post(
            self.url,
            {'session_id': 99999},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_post_requires_session_id(self):
        resp = self.client.post(
            self.url, {}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)


class CurrentSessionAutoResolveTest(TestCase):
    """P3.9 — default-session selection covers 0 / 1 / many memberships."""

    url = reverse('api-current-session')

    def setUp(self):
        self.user = User.objects.create_user(
            username='picker', email='p@x.com', password='password123',
        )
        token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')

    def _session(self, game, slug='default', active=True):
        now = timezone.now()
        return Session.objects.create(
            game=game, slug=slug, name=slug.title(),
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING if active else Session.FINISHED,
        )

    def _join(self, session, name='team'):
        team = Team.objects.create(
            name=name, session=session, color='#111',
        )
        TeamMembership.objects.create(
            team=team, user=self.user.profile, is_active=True,
        )
        return team

    def test_zero_memberships_returns_404(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 404)

    def test_multiple_active_memberships_returns_409_with_candidates(self):
        game_a = _make_game(name='A', slug='a')
        game_b = _make_game(name='B', slug='b')
        s_a = self._session(game_a)
        s_b = self._session(game_b)
        self._join(s_a, name='a1')
        self._join(s_b, name='b1')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 409)
        body = resp.json()
        self.assertEqual(len(body['candidates']), 2)
        ids = {c['id'] for c in body['candidates']}
        self.assertEqual(ids, {s_a.id, s_b.id})

    def test_stale_current_session_is_auto_replaced(self):
        """A current_session the user is no longer a member of is dropped."""
        gone_game = _make_game(name='Gone', slug='gone')
        gone = self._session(gone_game)
        # Set current_session directly, but user has no membership.
        self.user.profile.current_session = gone
        self.user.profile.save(update_fields=['current_session'])
        # Meanwhile, user is a member of exactly one real session.
        live_game = _make_game(name='Live', slug='live-auto')
        live = self._session(live_game)
        self._join(live, name='l1')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['id'], live.id)

    def test_inactive_session_triggers_auto_resolve(self):
        """If current_session went inactive, fall back to an active one."""
        # Inactive session on one game…
        old_game = _make_game(name='Old', slug='old-g')
        old_session = self._session(old_game, slug='old', active=False)
        self._join(old_session, name='old')
        self.user.profile.current_session = old_session
        self.user.profile.save(update_fields=['current_session'])
        # …and an active membership on a different game's session.
        live_game = _make_game(name='Live', slug='live-g')
        new_session = self._session(live_game, slug='new')
        self._join(new_session, name='new')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['id'], new_session.id)

    def test_player_cannot_post_session_they_do_not_belong_to(self):
        other_game = _make_game(name='Other', slug='other')
        other = self._session(other_game)
        resp = self.client.post(
            self.url,
            {'session_id': other.id},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_staff_without_memberships_gets_fallback(self):
        staff = User.objects.create_user(
            username='staff-picker', email='sp@x.com',
            password='password123', is_staff=True,
        )
        token = Token.objects.create(user=staff)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Token {token.key}')
        game = _make_game(name='S', slug='s-auto')
        s = self._session(game)
        resp = c.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['id'], s.id)


class SessionHistoryTest(TestCase):
    """P3.10 — my-sessions, scoreboard, timeline + access control."""

    def setUp(self):
        self.game = _make_game(name='Hist', slug='hist')
        now = timezone.now()
        self.session = Session.objects.create(
            game=self.game, slug='default', name='Default',
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
        self.past_session = Session.objects.create(
            game=self.game, slug='past', name='Past',
            start_time=now - timedelta(days=7),
            end_time=now - timedelta(days=6),
            state=Session.FINISHED,
        )
        self.team = Team.objects.create(
            name='alpha', session=self.session, color='#111',
        )
        self.team.score = 42
        self.team.save()

        self.member = User.objects.create_user(
            username='alpha-player', email='a@x.com', password='password123',
        )
        TeamMembership.objects.create(
            team=self.team, user=self.member.profile, is_active=True,
        )
        self.member_client = APIClient()
        self.member_client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.member).key}',
        )

        self.outsider = User.objects.create_user(
            username='outsider', email='o@x.com', password='password123',
        )
        self.outsider_client = APIClient()
        self.outsider_client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.outsider).key}',
        )

        self.staff = User.objects.create_user(
            username='hist-staff', email='hs@x.com',
            password='password123', is_staff=True,
        )
        self.staff_client = APIClient()
        self.staff_client.credentials(
            HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.staff).key}',
        )

    def test_my_sessions_returns_player_memberships(self):
        resp = self.member_client.get(reverse('api-my-sessions'))
        self.assertEqual(resp.status_code, 200)
        ids = [s['id'] for s in resp.json()]
        self.assertEqual(ids, [self.session.id])

    def test_my_sessions_hides_other_users_sessions(self):
        resp = self.outsider_client.get(reverse('api-my-sessions'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_scoreboard_accessible_to_member(self):
        url = reverse(
            'api-session-scoreboard', args=[self.session.id],
        )
        resp = self.member_client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['session']['id'], self.session.id)
        entry = body['entries'][0]
        self.assertEqual(entry['team_id'], self.team.id)
        self.assertEqual(entry['locked_score'], 42)

    def test_scoreboard_forbidden_to_non_member(self):
        url = reverse(
            'api-session-scoreboard', args=[self.session.id],
        )
        resp = self.outsider_client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_scoreboard_open_to_staff(self):
        url = reverse(
            'api-session-scoreboard', args=[self.session.id],
        )
        resp = self.staff_client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_timeline_returns_ownership_events(self):
        from django.contrib.gis.geos import Point, Polygon

        from game.models import TeamTowerOwnership, Tower, Zone
        zone = Zone.objects.create(
            name='Z', scoring_type=Zone.SCORE_LIN,
            shape=Polygon.from_bbox((23.0, 46.0, 24.0, 47.0)),
            game=self.game,
        )
        tower = Tower.objects.create(
            name='T', zone=zone, location=Point(23.5, 46.5),
            is_active=True, category=Tower.CATEGORY_NORMAL,
            game=self.game,
        )
        TeamTowerOwnership.objects.create(team=self.team, tower=tower)
        url = reverse(
            'api-session-timeline', args=[self.session.id],
        )
        resp = self.member_client.get(url)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body['events']), 1)
        event = body['events'][0]
        self.assertEqual(event['tower_name'], tower.name)
        self.assertEqual(event['team_id'], self.team.id)

    def test_timeline_forbidden_to_non_member(self):
        url = reverse(
            'api-session-timeline', args=[self.session.id],
        )
        resp = self.outsider_client.get(url)
        self.assertEqual(resp.status_code, 403)

    def test_staff_sessions_filter_by_is_active(self):
        self.staff.profile.current_session = self.session
        self.staff.profile.save(update_fields=['current_session'])
        resp = self.staff_client.get('/api/staff/sessions/?is_active=false')
        self.assertEqual(resp.status_code, 200)
        ids = [s['id'] for s in resp.json()]
        self.assertEqual(ids, [self.past_session.id])

    def test_scoreboard_404_for_unknown_session(self):
        url = reverse('api-session-scoreboard', args=[999999])
        resp = self.staff_client.get(url)
        self.assertEqual(resp.status_code, 404)


class InviteAPITest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username='admin', email='a@x.com', password='password123', is_staff=True,
        )
        self.staff_token = Token.objects.create(user=self.staff)
        self.staff_client = APIClient()
        self.staff_client.credentials(HTTP_AUTHORIZATION=f'Token {self.staff_token.key}')

        self.game = _make_game()
        self.team = _make_team(self.game)
        # Phase-3 scoping: staff viewsets filter by current_session.
        self.staff.profile.current_session = self.team.session
        self.staff.profile.save(update_fields=['current_session'])

    def _create_invite(self, **overrides):
        defaults = {
            'team': self.team,
            'email': 'new@example.com',
            'created_by': self.staff,
        }
        defaults.update(overrides)
        return Invite.objects.create(**defaults)

    def test_create_invite_sends_email(self):
        resp = self.staff_client.post(reverse('api-invites'), {
            'team': self.team.id,
            'email': 'scout@example.com',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('scout@example.com', mail.outbox[0].to)
        self.assertIn(self.team.name, mail.outbox[0].subject)

    def test_create_invite_without_email_sends_nothing(self):
        resp = self.staff_client.post(reverse('api-invites'), {
            'team': self.team.id,
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(len(mail.outbox), 0)

    def test_create_invite_requires_staff(self):
        regular = User.objects.create_user(username='r', email='r@x.com', password='password123')
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=regular).key}')
        resp = client.post(reverse('api-invites'), {
            'team': self.team.id, 'email': 'x@y.com',
        }, content_type='application/json')
        self.assertEqual(resp.status_code, 403)

    def test_list_invites_filters_by_status(self):
        pending = self._create_invite()
        self._create_invite(email='rev@x.com', revoked=True)
        self._create_invite(
            email='exp@x.com', expires_at=timezone.now() - timedelta(days=1),
        )
        resp = self.staff_client.get(reverse('api-invites') + '?status=pending')
        self.assertEqual(resp.status_code, 200)
        ids = [i['id'] for i in resp.json()]
        self.assertEqual(ids, [pending.id])

    def test_preview_returns_team_info(self):
        invite = self._create_invite()
        resp = self.client.get(reverse('api-invite-preview', args=[invite.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['team_name'], self.team.name)

    def test_preview_410_for_expired(self):
        invite = self._create_invite(expires_at=timezone.now() - timedelta(days=1))
        resp = self.client.get(reverse('api-invite-preview', args=[invite.token]))
        self.assertEqual(resp.status_code, 410)

    def test_preview_410_for_revoked(self):
        invite = self._create_invite(revoked=True)
        resp = self.client.get(reverse('api-invite-preview', args=[invite.token]))
        self.assertEqual(resp.status_code, 410)

    def test_accept_as_anon_creates_user_and_joins_team(self):
        invite = self._create_invite()
        resp = self.client.post(
            reverse('api-invite-accept', args=[invite.token]),
            {
                'username': 'rookie', 'email': 'rookie@x.com',
                'password': 'password12345', 'first_name': 'R',
            },
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('token', resp.json())
        user = User.objects.get(username='rookie')
        self.assertTrue(
            TeamMembership.objects.filter(
                team=self.team, user=user.profile, is_active=True,
            ).exists()
        )
        invite.refresh_from_db()
        self.assertEqual(invite.accepted_by, user)
        self.assertIsNotNone(invite.accepted_at)

    def test_accept_as_authenticated_user_skips_registration(self):
        existing = User.objects.create_user(
            username='scout', email='s@x.com', password='password123',
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=existing).key}')
        invite = self._create_invite()
        resp = client.post(reverse('api-invite-accept', args=[invite.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['team_id'], self.team.id)

    def test_accept_conflicts_when_already_on_another_team_same_game(self):
        """P3.4 — invite-accept returns 409 when the user already has an
        active membership on a different team in the same game."""
        from organize.models import Session
        now = timezone.now()
        second_session = Session.objects.create(
            game=self.team.session.game,
            slug='second', name='Second',
            start_time=now, end_time=now + timedelta(hours=1),
            state=Session.RUNNING,
        )
        second_team = Team.objects.create(
            name='rival', session=second_session, color='#888',
        )
        existing = User.objects.create_user(
            username='double', email='d@x.com', password='password123',
        )
        TeamMembership.objects.create(
            team=self.team, user=existing.profile, is_active=True,
        )
        client = APIClient()
        token = Token.objects.create(user=existing).key
        client.credentials(HTTP_AUTHORIZATION=f'Token {token}')
        invite = Invite.objects.create(
            team=second_team, email='', created_by=self.staff,
        )
        resp = client.post(reverse('api-invite-accept', args=[invite.token]))
        self.assertEqual(resp.status_code, 409)
        self.assertIn('already on team', resp.json()['detail'])

    def test_accept_twice_returns_410(self):
        invite = self._create_invite()
        self.client.post(
            reverse('api-invite-accept', args=[invite.token]),
            {'username': 'a', 'email': 'a@a.com', 'password': 'password12345'},
            content_type='application/json',
        )
        resp = self.client.post(
            reverse('api-invite-accept', args=[invite.token]),
            {'username': 'b', 'email': 'b@b.com', 'password': 'password12345'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 410)

    def test_accept_expired_returns_410(self):
        invite = self._create_invite(expires_at=timezone.now() - timedelta(days=1))
        resp = self.client.post(
            reverse('api-invite-accept', args=[invite.token]),
            {'username': 'x', 'email': 'x@x.com', 'password': 'password12345'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 410)

    def test_accept_anon_missing_fields_rejected(self):
        invite = self._create_invite()
        resp = self.client.post(
            reverse('api-invite-accept', args=[invite.token]),
            {'username': 'x'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_delete_invite_marks_revoked(self):
        invite = self._create_invite()
        resp = self.staff_client.delete(reverse('api-invite-destroy', args=[invite.id]))
        self.assertEqual(resp.status_code, 204)
        invite.refresh_from_db()
        self.assertTrue(invite.revoked)

    def test_resend_sends_new_email(self):
        invite = self._create_invite()
        resp = self.staff_client.post(reverse('api-invite-resend', args=[invite.id]))
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(len(mail.outbox), 1)

    def test_resend_410_on_expired(self):
        invite = self._create_invite(expires_at=timezone.now() - timedelta(days=1))
        resp = self.staff_client.post(reverse('api-invite-resend', args=[invite.id]))
        self.assertEqual(resp.status_code, 410)


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


# ---------------------------------------------------------------------------
# team-roles-as-mechanics — role models, INVITER power, cloning, API surface
# game-config-team-rules — team-composition knobs, readiness, start-gate
# ---------------------------------------------------------------------------


def _member(team, username):
    """Create a user with an active membership on `team`."""
    user = User.objects.create_user(
        username=username, email=f'{username}@example.com', password='password123',
    )
    membership = TeamMembership.objects.create(
        team=team, user=user.profile, is_active=True,
    )
    return user, membership


def _client_for(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=user).key}')
    return client


class GameRoleModelTest(TestCase):
    """8.1 — GameRole/TeamRole uniqueness and cross-game rejection."""

    def setUp(self):
        self.game = _make_game()
        self.team = _make_team(self.game)

    def test_slug_unique_per_game(self):
        from django.db import IntegrityError
        GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        with self.assertRaises(IntegrityError):
            GameRole.objects.create(game=self.game, name='Chef', slug='cook')

    def test_same_slug_ok_across_games(self):
        other = _make_game(name='Game B')
        GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        GameRole.objects.create(game=other, name='Cook', slug='cook')
        self.assertEqual(GameRole.objects.filter(slug='cook').count(), 2)

    def test_membership_cannot_hold_same_role_twice(self):
        from django.db import IntegrityError
        role = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        _, membership = _member(self.team, 'scout')
        TeamRole.objects.create(membership=membership, role=role)
        with self.assertRaises(IntegrityError):
            TeamRole.objects.create(membership=membership, role=role)

    def test_role_from_other_game_rejected(self):
        from django.core.exceptions import ValidationError
        other = _make_game(name='Game B')
        foreign_role = GameRole.objects.create(game=other, name='Cook', slug='cook')
        _, membership = _member(self.team, 'scout')
        with self.assertRaises(ValidationError):
            TeamRole.objects.create(membership=membership, role=foreign_role)

    def test_role_accessors_ignore_inactive_memberships(self):
        cook = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        medic = GameRole.objects.create(game=self.game, name='Medic', slug='medic')
        _, active_m = _member(self.team, 'active')
        gone_user = User.objects.create_user(
            username='gone', email='gone@example.com', password='password123',
        )
        gone_m = TeamMembership.objects.create(
            team=self.team, user=gone_user.profile, is_active=False,
            left_at=timezone.now(),
        )
        TeamRole.objects.create(membership=active_m, role=cook)
        TeamRole.objects.create(membership=gone_m, role=medic)
        self.assertEqual(active_m.role_slugs(), ['cook'])
        self.assertEqual(self.team.active_role_slugs(), {'cook'})


class InviterPowerTest(TestCase):
    """8.4 — INVITER built-in power extends (never replaces) staff invites."""

    def setUp(self):
        self.game = _make_game()
        self.team = _make_team(self.game)
        self.inviter_role = GameRole.objects.create(
            game=self.game, name='Inviter', slug='inviter',
            builtin_power=BUILTIN_POWER_INVITER,
        )
        self.url = reverse('api-invites')

    def test_inviter_holder_can_create_invite_for_own_team(self):
        user, membership = _member(self.team, 'holder')
        TeamRole.objects.create(membership=membership, role=self.inviter_role)
        resp = _client_for(user).post(
            self.url, {'team': self.team.id}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['created_by'], user.id)

    def test_inviter_holder_cannot_invite_to_other_team(self):
        user, membership = _member(self.team, 'holder')
        TeamRole.objects.create(membership=membership, role=self.inviter_role)
        other_team = Team.objects.create(
            name='Rivals', session=self.team.session, color='#00ff00',
        )
        resp = _client_for(user).post(
            self.url, {'team': other_team.id}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_non_holder_member_cannot_create_invite(self):
        user, _ = _member(self.team, 'plain')
        resp = _client_for(user).post(
            self.url, {'team': self.team.id}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Invite.objects.exists())

    def test_staff_can_still_create_invite(self):
        staff = User.objects.create_user(
            username='boss', email='boss@example.com', password='password123',
            is_staff=True,
        )
        resp = _client_for(staff).post(
            self.url, {'team': self.team.id}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 201)

    def test_without_inviter_role_defined_creation_stays_staff_only(self):
        self.inviter_role.delete()
        user, _ = _member(self.team, 'plain')
        resp = _client_for(user).post(
            self.url, {'team': self.team.id}, content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_inactive_membership_role_does_not_grant_invite(self):
        user, membership = _member(self.team, 'gone')
        TeamRole.objects.create(membership=membership, role=self.inviter_role)
        membership.is_active = False
        membership.left_at = timezone.now()
        membership.save()
        self.assertFalse(user_can_invite_to_team(user, self.team))

    def test_invite_listing_stays_staff_only(self):
        user, membership = _member(self.team, 'holder')
        TeamRole.objects.create(membership=membership, role=self.inviter_role)
        resp = _client_for(user).get(self.url)
        self.assertEqual(resp.status_code, 403)


class GameCloneRolesTest(TestCase):
    """8.6 — cloning a Game copies roles and rewires challenge requirements."""

    def setUp(self):
        from game.models import ROLE_REQUIREMENT_ALL, Challenge
        self.game = _make_game()
        self.cook = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        self.medic = GameRole.objects.create(game=self.game, name='Medic', slug='medic')
        from organize.models import TeamGroup
        TeamGroup.objects.create(game=self.game, name='Explo', slug='explo')
        self.challenge = Challenge.objects.create(
            game=self.game, text='Cook a meal', difficulty=2,
            role_requirement_mode=ROLE_REQUIREMENT_ALL,
        )
        self.challenge.required_roles.set([self.cook, self.medic])

    def test_clone_copies_roles_and_remaps_requirements(self):
        clone = self.game.clone(slug='clone')
        self.assertNotEqual(clone.pk, self.game.pk)
        self.assertFalse(clone.is_active)

        cloned_roles = {r.slug: r for r in clone.roles.all()}
        self.assertEqual(set(cloned_roles), {'cook', 'medic'})
        self.assertNotIn(
            self.cook.pk, [r.pk for r in cloned_roles.values()],
        )

        cloned_challenge = clone.challenges.get()
        required = list(cloned_challenge.required_roles.all())
        self.assertEqual({r.slug for r in required}, {'cook', 'medic'})
        # No reference back to the original's roles.
        for role in required:
            self.assertEqual(role.game_id, clone.pk)

    def test_clone_copies_team_groups_and_config(self):
        self.game.proximity_meters = 75
        self.game.save(update_fields=['proximity_meters'])
        clone = self.game.clone(slug='clone', name='The clone')
        self.assertEqual(clone.name, 'The clone')
        self.assertEqual(clone.proximity_meters, 75)
        from organize.models import TeamGroup
        self.assertTrue(
            TeamGroup.objects.filter(game=clone, slug='explo').exists(),
        )

    def test_original_untouched_by_clone(self):
        self.game.clone(slug='clone')
        self.challenge.refresh_from_db()
        self.assertEqual(
            {r.pk for r in self.challenge.required_roles.all()},
            {self.cook.pk, self.medic.pk},
        )
        self.assertEqual(self.game.roles.count(), 2)


class RolesApiSurfaceTest(TestCase):
    """5.3 — roles surfaced on my-team and me payloads."""

    def setUp(self):
        self.game = _make_game()
        self.team = _make_team(self.game)
        self.cook = GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        self.inviter = GameRole.objects.create(
            game=self.game, name='Inviter', slug='inviter',
            builtin_power=BUILTIN_POWER_INVITER,
        )
        self.user, self.membership = _member(self.team, 'scout')
        TeamRole.objects.create(membership=self.membership, role=self.cook)
        self.client_api = _client_for(self.user)

    def test_my_team_members_expose_roles(self):
        resp = self.client_api.get(reverse('api-my-team'))
        self.assertEqual(resp.status_code, 200)
        member = resp.json()['members'][0]
        self.assertEqual([r['slug'] for r in member['roles']], ['cook'])

    def test_my_team_exposes_can_invite_flag(self):
        resp = self.client_api.get(reverse('api-my-team'))
        self.assertFalse(resp.json()['can_invite'])
        TeamRole.objects.create(membership=self.membership, role=self.inviter)
        resp = self.client_api.get(reverse('api-my-team'))
        self.assertTrue(resp.json()['can_invite'])

    def test_me_exposes_active_roles(self):
        resp = self.client_api.get(reverse('api-me'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            [r['slug'] for r in resp.json()['active_roles']], ['cook'],
        )


class SessionStateMigrationTest(TransactionTestCase):
    """game-lifecycle-states 7.2 — the 0012 backfill maps the legacy
    boolean (and open pause windows) onto the new lifecycle states, and
    the derived-active set matches the pre-migration is_active set."""

    migrate_from = [
        ('organize', '0011_session_state'),
        # Sibling branch heads (game-config-team-rules and
        # player-team-formation): their NOT NULL columns exist in the
        # test DB, so the historical project state must include them for
        # inserts through the old model to succeed.
        ('organize', '0011_game_team_rules'),
        ('organize', '0012_backfill_invite_kind'),
        ('game', '0021_pausewindow_teamtowerfailcounter'),
    ]
    migrate_to = [('organize', '0012_backfill_session_state')]

    def _executor(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        return executor

    def tearDown(self):
        # Return the schema to the latest migration for the tests after us.
        executor = self._executor()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_backfill_maps_boolean_and_open_windows_to_states(self):
        executor = self._executor()
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        OldGame = old_apps.get_model('organize', 'Game')
        OldSession = old_apps.get_model('organize', 'Session')
        OldPauseWindow = old_apps.get_model('game', 'PauseWindow')

        now = timezone.now()
        game = OldGame.objects.create(name='Mig', slug='mig-state')

        def _make(slug, active):
            return OldSession.objects.create(
                game=game, slug=slug, name=slug.title(),
                start_time=now, end_time=now + timedelta(hours=1),
                is_active=active,
            )

        running = _make('running', True)
        finished = _make('finished', False)
        paused = _make('paused', True)
        OldPauseWindow.objects.create(session_id=paused.id, started_at=now)
        active_before = {running.id, paused.id}

        executor = self._executor()
        executor.migrate(self.migrate_to)

        states = dict(Session.objects.values_list('id', 'state'))
        self.assertEqual(states[running.id], Session.RUNNING)
        self.assertEqual(states[finished.id], Session.FINISHED)
        self.assertEqual(states[paused.id], Session.PAUSED)
        # The same set of Sessions is "active" (derived) after migration.
        derived_active = {
            session_id for session_id, state in states.items()
            if state in Session.ACTIVE_STATES
        }
        self.assertEqual(derived_active, active_before)


# ---------------------------------------------------------------------------
# game-config-team-rules — team-composition knobs, readiness, start-gate
# ---------------------------------------------------------------------------


def _member_user(team, username):
    """Create a user and an active membership on `team`."""
    user = User.objects.create_user(
        username=username, email=f'{username}@example.com', password='password123',
    )
    TeamMembership.objects.create(team=team, user=user.profile, is_active=True)
    return user


class TeamRulesEffectiveConfigTest(TestCase):
    """5.1 — Session.effective() resolves the four new team-rule fields."""

    def setUp(self):
        self.game = _make_game()
        self.session = _default_session(self.game)

    def test_defaults_resolve_from_game(self):
        self.assertEqual(self.session.effective('min_teams'), 1)
        self.assertEqual(self.session.effective('max_teams'), 0)
        self.assertEqual(self.session.effective('min_members_per_team'), 1)
        self.assertEqual(self.session.effective('max_members_per_team'), 0)

    def test_game_default_wins_when_override_null(self):
        self.game.min_teams = 3
        self.game.max_teams = 5
        self.game.min_members_per_team = 2
        self.game.max_members_per_team = 6
        self.game.save()
        self.assertEqual(self.session.effective('min_teams'), 3)
        self.assertEqual(self.session.effective('max_teams'), 5)
        self.assertEqual(self.session.effective('min_members_per_team'), 2)
        self.assertEqual(self.session.effective('max_members_per_team'), 6)

    def test_session_override_wins(self):
        self.game.min_teams = 3
        self.game.max_members_per_team = 6
        self.game.save()
        self.session.min_teams = 2
        self.session.max_teams = 4
        self.session.min_members_per_team = 5
        self.session.max_members_per_team = 0  # explicitly uncapped
        self.session.save()
        self.assertEqual(self.session.effective('min_teams'), 2)
        self.assertEqual(self.session.effective('max_teams'), 4)
        self.assertEqual(self.session.effective('min_members_per_team'), 5)
        self.assertEqual(self.session.effective('max_members_per_team'), 0)

    def test_unknown_field_still_raises(self):
        with self.assertRaises(ValueError):
            self.session.effective('not_a_config_field')


class TeamReadinessTest(TestCase):
    """5.2 — Team.active_member_count() / is_ready() against member rules."""

    def setUp(self):
        self.game = _make_game()
        self.session = _default_session(self.game)
        self.team = _make_team(self.game)

    def test_counts_only_active_memberships(self):
        _member_user(self.team, 'active1')
        leaver = User.objects.create_user(
            username='leaver', email='leaver@example.com', password='password123',
        )
        TeamMembership.objects.create(
            team=self.team, user=leaver.profile,
            is_active=False, left_at=timezone.now(),
        )
        self.assertEqual(self.team.active_member_count(), 1)

    def test_below_minimum_is_not_ready_with_shortfall(self):
        self.game.min_members_per_team = 3
        self.game.save()
        _member_user(self.team, 'solo')
        self.assertFalse(self.team.is_ready())
        self.assertEqual(self.team.members_needed(), 2)

    def test_within_range_is_ready(self):
        self.game.min_members_per_team = 1
        self.game.max_members_per_team = 3
        self.game.save()
        _member_user(self.team, 'one')
        _member_user(self.team, 'two')
        self.assertTrue(self.team.is_ready())
        self.assertEqual(self.team.members_needed(), 0)

    def test_zero_maximum_means_uncapped(self):
        for i in range(5):
            _member_user(self.team, f'many{i}')
        self.assertTrue(self.team.is_ready())

    def test_over_nonzero_maximum_is_not_ready(self):
        self.game.max_members_per_team = 2
        self.game.save()
        for i in range(3):
            _member_user(self.team, f'crowd{i}')
        self.assertFalse(self.team.is_ready())

    def test_session_override_applies_to_readiness(self):
        session = self.team.session
        session.min_members_per_team = 2
        session.save()
        _member_user(self.team, 'lonely')
        self.assertFalse(self.team.is_ready())
        self.assertEqual(self.team.members_needed(), 1)


class StartGateTest(TestCase):
    """5.3 / 5.5 — Session.start_blockers() / can_start()."""

    def setUp(self):
        self.game = _make_game()
        self.session = _default_session(self.game)

    def test_defaults_zero_teams_blocked(self):
        blockers = self.session.start_blockers()
        self.assertFalse(self.session.can_start())
        self.assertEqual(blockers[0]['code'], 'too_few_teams')
        self.assertEqual(blockers[0]['required'], 1)
        self.assertEqual(blockers[0]['current'], 0)

    def test_defaults_single_one_member_team_starts(self):
        """5.5 — backward compatibility: defaults keep today's behaviour."""
        team = _make_team(self.game)
        _member_user(team, 'solo')
        self.assertTrue(self.session.can_start())
        self.assertEqual(self.session.start_blockers(), [])
        self.assertEqual(self.session.ready_team_count(), 1)

    def test_below_min_teams_blocked_with_counts(self):
        self.game.min_teams = 2
        self.game.save()
        team = _make_team(self.game)
        _member_user(team, 'a')
        blockers = self.session.start_blockers()
        self.assertFalse(self.session.can_start())
        self.assertEqual(blockers[0]['code'], 'too_few_teams')
        self.assertEqual(blockers[0]['required'], 2)
        self.assertEqual(blockers[0]['current'], 1)

    def test_padding_empty_team_does_not_satisfy_min_teams(self):
        self.game.min_teams = 2
        self.game.save()
        full_team = _make_team(self.game, name='Full')
        _member_user(full_team, 'full1')
        empty_team = _make_team(self.game, name='Empty')
        blockers = self.session.start_blockers()
        self.assertFalse(self.session.can_start())
        codes = [b['code'] for b in blockers]
        self.assertIn('too_few_teams', codes)
        underfilled = [b for b in blockers if b['code'] == 'team_below_minimum']
        self.assertEqual(len(underfilled), 1)
        self.assertEqual(underfilled[0]['team_id'], empty_team.id)
        self.assertEqual(underfilled[0]['team_name'], 'Empty')
        self.assertEqual(underfilled[0]['shortfall'], 1)

    def test_two_ready_teams_satisfy_min_teams(self):
        self.game.min_teams = 2
        self.game.save()
        for name in ('Lynx', 'Wolf'):
            team = _make_team(self.game, name=name)
            _member_user(team, f'member-{name}')
        self.assertTrue(self.session.can_start())

    def test_over_max_teams_blocked(self):
        self.game.max_teams = 1
        self.game.save()
        for name in ('Lynx', 'Wolf'):
            team = _make_team(self.game, name=name)
            _member_user(team, f'member-{name}')
        blockers = self.session.start_blockers()
        self.assertFalse(self.session.can_start())
        self.assertEqual(blockers[0]['code'], 'too_many_teams')
        self.assertEqual(blockers[0]['allowed'], 1)
        self.assertEqual(blockers[0]['current'], 2)

    def test_over_member_cap_blocks_start(self):
        self.game.max_members_per_team = 1
        self.game.save()
        team = _make_team(self.game)
        _member_user(team, 'one')
        # Bypass join-time enforcement to simulate an over-cap roster.
        TeamMembership.objects.create(
            team=team,
            user=User.objects.create_user(
                username='two', email='two@example.com', password='password123',
            ).profile,
            is_active=True,
        )
        blockers = self.session.start_blockers()
        self.assertFalse(self.session.can_start())
        codes = [b['code'] for b in blockers]
        self.assertIn('team_above_maximum', codes)

    def test_session_override_gates_instead_of_game_default(self):
        self.session.min_teams = 2
        self.session.save()
        team = _make_team(self.game)
        _member_user(team, 'only')
        self.assertFalse(self.session.can_start())


class JoinCapTest(TestCase):
    """5.4 — max_members_per_team enforced at join time."""

    def setUp(self):
        self.game = _make_game()
        self.game.max_members_per_team = 2
        self.game.save()
        self.team = _make_team(self.game)
        self.staff = User.objects.create_user(
            username='cap-admin', email='cap@x.com', password='password123',
            is_staff=True,
        )

    def _accept(self, username):
        invite = Invite.objects.create(
            team=self.team, email='', created_by=self.staff,
        )
        return self.client.post(
            reverse('api-invite-accept', args=[invite.token]),
            {
                'username': username,
                'email': f'{username}@example.com',
                'password': 'password12345',
            },
            content_type='application/json',
        )

    def test_join_with_room_succeeds(self):
        resp = self._accept('joiner1')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.team.active_member_count(), 1)

    def test_join_full_team_rejected(self):
        _member_user(self.team, 'seat1')
        _member_user(self.team, 'seat2')
        resp = self._accept('overflow')
        self.assertEqual(resp.status_code, 409)
        self.assertIn('maximum', resp.json()['detail'])
        self.assertEqual(self.team.active_member_count(), 2)
        self.assertFalse(User.objects.filter(username='overflow').exists())

    def test_join_cap_uses_session_override(self):
        self.team.session.max_members_per_team = 1
        self.team.session.save()
        _member_user(self.team, 'seat1')
        resp = self._accept('overflow')
        self.assertEqual(resp.status_code, 409)

    def test_zero_cap_means_unlimited_joins(self):
        self.game.max_members_per_team = 0
        self.game.save()
        _member_user(self.team, 'seat1')
        _member_user(self.team, 'seat2')
        _member_user(self.team, 'seat3')
        resp = self._accept('joiner4')
        self.assertEqual(resp.status_code, 200)

    def test_admin_add_over_cap_fails_validation(self):
        from django.core.exceptions import ValidationError
        _member_user(self.team, 'seat1')
        _member_user(self.team, 'seat2')
        extra = User.objects.create_user(
            username='extra', email='extra@x.com', password='password123',
        )
        membership = TeamMembership(
            team=self.team, user=extra.profile,
            game=self.team.session.game, is_active=True,
        )
        with self.assertRaises(ValidationError):
            membership.full_clean()

    def test_admin_edit_of_existing_member_passes_validation(self):
        _member_user(self.team, 'seat1')
        _member_user(self.team, 'seat2')
        membership = self.team.memberships.filter(is_active=True).first()
        membership.full_clean()  # editing an existing row must not trip the cap


# ---------------------------------------------------------------------------
# Player team formation (player-team-formation change)
# ---------------------------------------------------------------------------

import uuid  # noqa: E402

from organize.models import (  # noqa: E402
    JOIN_CONFIRM_AUTO_APPROVE,
    JOIN_CONFIRM_CAPTAIN,
    JOIN_CONFIRM_STAFF,
    TeamGroup,
    TeamJoinRequest,
    effective_allow_player_team_creation,
    effective_team_join_confirmation,
)


def _auth_client(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=user).key}')
    return client


def _make_user(username, email=None, **kwargs):
    return User.objects.create_user(
        username=username,
        email=email or f'{username}@example.com',
        password='password123',
        **kwargs,
    )


class TeamFormationBase(TestCase):
    """Common fixture: an active game + session and a few users."""

    def setUp(self):
        self.game = _make_game(name='Form', slug='form')
        self.game.is_active = True
        self.game.save()
        now = timezone.now()
        # Lifecycle semantics: "open for joining" is the
        # OPEN_FOR_PARTICIPANTS state (active + accepts roster changes).
        self.session = Session.objects.create(
            game=self.game, slug='default', name='Default',
            start_time=now, end_time=now + timedelta(hours=4),
            state=Session.OPEN_FOR_PARTICIPANTS,
        )

    def _enable_toggle(self):
        self.game.allow_player_team_creation = True
        self.game.save(update_fields=['allow_player_team_creation'])

    def _player(self, username, session=None):
        user = _make_user(username)
        user.profile.current_session = session or self.session
        user.profile.save(update_fields=['current_session'])
        return user, _auth_client(user)

    def _captain_team(self, username='cap', name='Foxes'):
        user = _make_user(username)
        team = Team.objects.create(
            name=name, session=self.session, color='#123456',
            captain=user, join_code=uuid.uuid4(),
        )
        TeamMembership.objects.create(team=team, user=user.profile, is_active=True)
        user.profile.current_session = self.session
        user.profile.save(update_fields=['current_session'])
        return user, team, _auth_client(user)


class ToggleResolutionTest(TeamFormationBase):
    """9.1 — effective-value resolution for the creation toggle."""

    def test_defaults_preserve_staff_only(self):
        self.assertFalse(self.game.allow_player_team_creation)
        self.assertIsNone(self.session.allow_player_team_creation)
        self.assertFalse(effective_allow_player_team_creation(self.session))

    def test_session_override_wins(self):
        self.session.allow_player_team_creation = True
        self.session.save()
        self.assertTrue(effective_allow_player_team_creation(self.session))
        # Game turned on but session explicitly off → off.
        self._enable_toggle()
        self.session.allow_player_team_creation = False
        self.session.save()
        self.session.refresh_from_db()
        self.assertFalse(effective_allow_player_team_creation(self.session))

    def test_null_session_value_falls_back_to_game(self):
        self._enable_toggle()
        self.session.refresh_from_db()
        self.assertTrue(effective_allow_player_team_creation(self.session))

    def test_effective_team_join_confirmation(self):
        team = Team.objects.create(name='t', session=self.session, color='#111')
        self.assertEqual(
            effective_team_join_confirmation(team), JOIN_CONFIRM_AUTO_APPROVE,
        )
        self.game.team_join_confirmation = JOIN_CONFIRM_STAFF
        self.game.save()
        team.refresh_from_db()
        self.assertEqual(
            effective_team_join_confirmation(team), JOIN_CONFIRM_STAFF,
        )
        team.team_join_confirmation = JOIN_CONFIRM_CAPTAIN
        team.save()
        self.assertEqual(
            effective_team_join_confirmation(team), JOIN_CONFIRM_CAPTAIN,
        )


class PlayerTeamCreateAPITest(TeamFormationBase):
    """9.2 — POST /api/teams/ player create."""

    url = '/api/teams/'

    def test_denied_when_toggle_off(self):
        _, client = self._player('p1')
        resp = client.post(self.url, {'name': 'Wolves'}, format='json')
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(Team.objects.count(), 0)

    def test_create_when_enabled_makes_creator_captain(self):
        self._enable_toggle()
        user, client = self._player('p2')
        resp = client.post(self.url, {'name': 'Wolves'}, format='json')
        self.assertEqual(resp.status_code, 201)
        team = Team.objects.get(name='Wolves')
        self.assertEqual(team.captain, user)
        self.assertEqual(team.session, self.session)
        self.assertIsNotNone(team.join_code)
        self.assertTrue(team.color.startswith('#'))
        self.assertTrue(
            TeamMembership.objects.filter(
                team=team, user=user.profile, is_active=True,
            ).exists()
        )

    def test_session_override_enables_creation(self):
        self.session.allow_player_team_creation = True
        self.session.save()
        _, client = self._player('p3')
        resp = client.post(self.url, {'name': 'Owls'}, format='json')
        self.assertEqual(resp.status_code, 201)

    def test_group_must_belong_to_same_game(self):
        self._enable_toggle()
        other_game = _make_game(name='Other', slug='other-form')
        group = TeamGroup.objects.create(name='G', game=other_game, slug='g')
        _, client = self._player('p4')
        resp = client.post(
            self.url, {'name': 'Bad', 'group': group.id}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_staff_can_create_regardless_of_toggle(self):
        staff = _make_user('tf-staff', is_staff=True)
        staff.profile.current_session = self.session
        staff.profile.save(update_fields=['current_session'])
        client = _auth_client(staff)
        resp = client.post(self.url, {'name': 'StaffTeam'}, format='json')
        self.assertEqual(resp.status_code, 201)
        team = Team.objects.get(name='StaffTeam')
        self.assertIsNone(team.captain)

    def test_second_team_same_session_denied(self):
        self._enable_toggle()
        _, client = self._player('p5')
        self.assertEqual(
            client.post(self.url, {'name': 'One'}, format='json').status_code, 201,
        )
        resp = client.post(self.url, {'name': 'Two'}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_conflicts_with_existing_membership(self):
        self._enable_toggle()
        user, client = self._player('p6')
        team = Team.objects.create(name='Existing', session=self.session, color='#222')
        TeamMembership.objects.create(team=team, user=user.profile, is_active=True)
        resp = client.post(self.url, {'name': 'Second'}, format='json')
        self.assertEqual(resp.status_code, 409)

    def test_404_without_current_session(self):
        self._enable_toggle()
        user = _make_user('p7')
        client = _auth_client(user)
        resp = client.post(self.url, {'name': 'NoSession'}, format='json')
        self.assertEqual(resp.status_code, 404)


class OpenSessionSelectionTest(TeamFormationBase):
    """Teamless players may enter an 'open' (formation-enabled) session."""

    url = reverse('api-current-session')

    def test_player_can_enter_open_session(self):
        self._enable_toggle()
        user = _make_user('walkup')
        client = _auth_client(user)
        resp = client.post(self.url, {'session_id': self.session.id}, format='json')
        self.assertEqual(resp.status_code, 200)
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.current_session_id, self.session.id)

    def test_closed_session_still_403(self):
        user = _make_user('walkup2')
        client = _auth_client(user)
        resp = client.post(self.url, {'session_id': self.session.id}, format='json')
        self.assertEqual(resp.status_code, 403)

    def test_open_session_survives_get_auto_resolve(self):
        self._enable_toggle()
        user, client = self._player('walkup3')
        resp = client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['id'], self.session.id)
        self.assertTrue(resp.json()['allow_player_team_creation'])


class JoinCodeAPITest(TeamFormationBase):
    """Untied, rotatable/revocable team join code."""

    def setUp(self):
        super().setUp()
        self._enable_toggle()
        self.captain, self.team, self.captain_client = self._captain_team()

    def _url(self, team=None):
        return f'/api/teams/{(team or self.team).id}/join-code/'

    def test_captain_reads_code_and_join_url(self):
        resp = self.captain_client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['join_code'], str(self.team.join_code))
        self.assertIn(f'/join/{self.team.join_code}', body['join_url'])

    def test_rotate_supersedes_old_code(self):
        old = self.team.join_code
        resp = self.captain_client.post(self._url(), {'action': 'rotate'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.team.refresh_from_db()
        self.assertNotEqual(self.team.join_code, old)
        self.assertEqual(resp.json()['join_code'], str(self.team.join_code))

    def test_revoke_clears_code(self):
        resp = self.captain_client.post(self._url(), {'action': 'revoke'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.team.refresh_from_db()
        self.assertIsNone(self.team.join_code)
        self.assertIsNone(resp.json()['join_code'])

    def test_unknown_action_400(self):
        resp = self.captain_client.post(self._url(), {'action': 'meh'}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_non_captain_member_denied(self):
        member, client = self._player('member1')
        TeamMembership.objects.create(team=self.team, user=member.profile, is_active=True)
        self.assertEqual(client.get(self._url()).status_code, 403)
        self.assertEqual(
            client.post(self._url(), {'action': 'rotate'}, format='json').status_code, 403,
        )

    def test_staff_can_manage_any_code(self):
        staff = _make_user('code-staff', is_staff=True)
        client = _auth_client(staff)
        resp = client.post(self._url(), {'action': 'rotate'}, format='json')
        self.assertEqual(resp.status_code, 200)

    def test_captain_cannot_manage_other_teams_code(self):
        _, other_team, _ = self._captain_team(username='cap2', name='Hawks')
        resp = self.captain_client.post(
            self._url(other_team), {'action': 'rotate'}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_public_preview(self):
        resp = self.client.get(f'/api/join-codes/{self.team.join_code}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['team_name'], self.team.name)

    def test_public_preview_404_for_revoked(self):
        code = self.team.join_code
        self.team.revoke_join_code()
        resp = self.client.get(f'/api/join-codes/{code}/')
        self.assertEqual(resp.status_code, 404)


class JoinViaCodeTest(TeamFormationBase):
    """9.3 / 9.5 — untied QR joins routed through the confirmation policy."""

    def setUp(self):
        super().setUp()
        self._enable_toggle()
        self.captain, self.team, self.captain_client = self._captain_team()
        self.url = '/api/join-requests/'

    def test_auto_approve_creates_membership(self):
        user = _make_user('scanner')
        client = _auth_client(user)
        resp = client.post(
            self.url, {'code': str(self.team.join_code)}, format='json',
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['status'], TeamJoinRequest.STATUS_APPROVED)
        self.assertEqual(body['source'], TeamJoinRequest.SOURCE_QR)
        self.assertTrue(
            TeamMembership.objects.filter(
                team=self.team, user=user.profile, is_active=True,
            ).exists()
        )
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.current_session_id, self.session.id)

    def test_confirmation_policy_defers_membership(self):
        self.game.team_join_confirmation = JOIN_CONFIRM_CAPTAIN
        self.game.save()
        user = _make_user('scanner2')
        client = _auth_client(user)
        resp = client.post(
            self.url, {'code': str(self.team.join_code)}, format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['status'], TeamJoinRequest.STATUS_PENDING)
        self.assertFalse(
            TeamMembership.objects.filter(team=self.team, user=user.profile).exists()
        )

    def test_per_team_override_wins_over_game_default(self):
        # Game auto-approves, but this team demands captain approval.
        self.team.team_join_confirmation = JOIN_CONFIRM_CAPTAIN
        self.team.save()
        user = _make_user('scanner3')
        client = _auth_client(user)
        resp = client.post(
            self.url, {'code': str(self.team.join_code)}, format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['status'], TeamJoinRequest.STATUS_PENDING)

    def test_stale_code_404(self):
        old = str(self.team.join_code)
        self.team.rotate_join_code()
        user = _make_user('scanner4')
        client = _auth_client(user)
        resp = client.post(self.url, {'code': old}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_conflicting_membership_409(self):
        user = _make_user('scanner5')
        other = Team.objects.create(name='Rival', session=self.session, color='#333')
        TeamMembership.objects.create(team=other, user=user.profile, is_active=True)
        client = _auth_client(user)
        resp = client.post(
            self.url, {'code': str(self.team.join_code)}, format='json',
        )
        self.assertEqual(resp.status_code, 409)


class BrowseAndRequestTest(TeamFormationBase):
    """Browse joinable teams and request to join (source BROWSE)."""

    def setUp(self):
        super().setUp()
        self._enable_toggle()
        self.captain, self.team, self.captain_client = self._captain_team()
        self.other_team = Team.objects.create(
            name='Bears', session=self.session, color='#444',
        )
        self.requester, self.requester_client = self._player('req1')

    def test_joinable_teams_lists_session_teams(self):
        resp = self.requester_client.get('/api/joinable-teams/')
        self.assertEqual(resp.status_code, 200)
        names = {t['name'] for t in resp.json()}
        self.assertEqual(names, {'Foxes', 'Bears'})
        entry = next(t for t in resp.json() if t['name'] == 'Foxes')
        self.assertEqual(entry['member_count'], 1)
        self.assertEqual(entry['join_confirmation'], JOIN_CONFIRM_AUTO_APPROVE)
        self.assertIsNone(entry['my_request_status'])

    def test_joinable_teams_403_when_toggle_off(self):
        self.game.allow_player_team_creation = False
        self.game.save()
        resp = self.requester_client.get('/api/joinable-teams/')
        self.assertEqual(resp.status_code, 403)

    def test_joinable_teams_excludes_own_team(self):
        resp = self.captain_client.get('/api/joinable-teams/')
        names = {t['name'] for t in resp.json()}
        self.assertEqual(names, {'Bears'})

    def test_browse_request_pending_under_captain_policy(self):
        self.game.team_join_confirmation = JOIN_CONFIRM_CAPTAIN
        self.game.save()
        resp = self.requester_client.post(
            '/api/join-requests/', {'team': self.team.id}, format='json',
        )
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body['status'], TeamJoinRequest.STATUS_PENDING)
        self.assertEqual(body['source'], TeamJoinRequest.SOURCE_BROWSE)
        self.assertFalse(
            TeamMembership.objects.filter(
                team=self.team, user=self.requester.profile,
            ).exists()
        )

    def test_browse_request_auto_approves(self):
        resp = self.requester_client.post(
            '/api/join-requests/', {'team': self.team.id}, format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['status'], TeamJoinRequest.STATUS_APPROVED)
        self.assertTrue(
            TeamMembership.objects.filter(
                team=self.team, user=self.requester.profile, is_active=True,
            ).exists()
        )

    def test_duplicate_pending_request_returns_existing(self):
        self.game.team_join_confirmation = JOIN_CONFIRM_CAPTAIN
        self.game.save()
        first = self.requester_client.post(
            '/api/join-requests/', {'team': self.team.id}, format='json',
        )
        second = self.requester_client.post(
            '/api/join-requests/', {'team': self.team.id}, format='json',
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['id'], second.json()['id'])

    def test_browse_request_needs_team_or_code(self):
        resp = self.requester_client.post('/api/join-requests/', {}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_browse_request_other_session_team_404(self):
        other_game = _make_game(name='Elsewhere', slug='elsewhere')
        foreign = _make_team(other_game, name='Foreign')
        resp = self.requester_client.post(
            '/api/join-requests/', {'team': foreign.id}, format='json',
        )
        self.assertEqual(resp.status_code, 404)

    def test_already_member_400(self):
        TeamMembership.objects.create(
            team=self.team, user=self.requester.profile, is_active=True,
        )
        resp = self.requester_client.post(
            '/api/join-requests/', {'team': self.team.id}, format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_visibility_and_status_filter(self):
        self.game.team_join_confirmation = JOIN_CONFIRM_CAPTAIN
        self.game.save()
        self.requester_client.post(
            '/api/join-requests/', {'team': self.team.id}, format='json',
        )
        # Requester sees their own request.
        own = self.requester_client.get('/api/join-requests/')
        self.assertEqual(len(own.json()), 1)
        # Captain sees their team's requests.
        cap = self.captain_client.get('/api/join-requests/')
        self.assertEqual(len(cap.json()), 1)
        # An unrelated player sees nothing.
        _, outsider_client = self._player('outsider')
        self.assertEqual(outsider_client.get('/api/join-requests/').json(), [])
        # Staff (scoped to the session) see the request; status filter works.
        staff = _make_user('queue-staff', is_staff=True)
        staff.profile.current_session = self.session
        staff.profile.save(update_fields=['current_session'])
        staff_client = _auth_client(staff)
        self.assertEqual(len(staff_client.get('/api/join-requests/').json()), 1)
        self.assertEqual(
            len(staff_client.get('/api/join-requests/?status=pending').json()), 1,
        )
        self.assertEqual(
            len(staff_client.get('/api/join-requests/?status=rejected').json()), 0,
        )


class JoinRequestDecisionTest(TeamFormationBase):
    """9.4 / 9.6 — approve/reject lifecycle and captain scope isolation."""

    def setUp(self):
        super().setUp()
        self._enable_toggle()
        self.game.team_join_confirmation = JOIN_CONFIRM_CAPTAIN
        self.game.save()
        self.captain, self.team, self.captain_client = self._captain_team()
        self.requester, requester_client = self._player('req2')
        resp = requester_client.post(
            '/api/join-requests/', {'team': self.team.id}, format='json',
        )
        self.request_id = resp.json()['id']
        self.requester_client = requester_client

    def _approve_url(self, pk=None):
        return f'/api/join-requests/{pk or self.request_id}/approve/'

    def _reject_url(self, pk=None):
        return f'/api/join-requests/{pk or self.request_id}/reject/'

    def test_captain_approval_creates_membership(self):
        resp = self.captain_client.post(self._approve_url())
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['status'], TeamJoinRequest.STATUS_APPROVED)
        self.assertEqual(body['decided_by_username'], 'cap')
        self.assertIsNotNone(body['decided_at'])
        self.assertTrue(
            TeamMembership.objects.filter(
                team=self.team, user=self.requester.profile, is_active=True,
            ).exists()
        )

    def test_captain_rejection_creates_no_membership(self):
        resp = self.captain_client.post(self._reject_url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['status'], TeamJoinRequest.STATUS_REJECTED)
        self.assertFalse(
            TeamMembership.objects.filter(
                team=self.team, user=self.requester.profile,
            ).exists()
        )

    def test_requester_cannot_decide_own_request(self):
        self.assertEqual(
            self.requester_client.post(self._approve_url()).status_code, 403,
        )

    def test_other_captain_cannot_decide(self):
        _, _, other_captain_client = self._captain_team(username='cap3', name='Kites')
        self.assertEqual(
            other_captain_client.post(self._approve_url()).status_code, 403,
        )
        self.assertEqual(
            other_captain_client.post(self._reject_url()).status_code, 403,
        )

    def test_staff_can_decide(self):
        staff = _make_user('decider', is_staff=True)
        client = _auth_client(staff)
        resp = client.post(self._approve_url())
        self.assertEqual(resp.status_code, 200)

    def test_double_decision_conflicts(self):
        self.captain_client.post(self._approve_url())
        self.assertEqual(
            self.captain_client.post(self._approve_url()).status_code, 409,
        )
        self.assertEqual(
            self.captain_client.post(self._reject_url()).status_code, 409,
        )

    def test_approval_conflicts_when_requester_joined_elsewhere(self):
        other = Team.objects.create(name='Else', session=self.session, color='#555')
        TeamMembership.objects.create(
            team=other, user=self.requester.profile, is_active=True,
        )
        resp = self.captain_client.post(self._approve_url())
        self.assertEqual(resp.status_code, 409)
        jr = TeamJoinRequest.objects.get(pk=self.request_id)
        self.assertEqual(jr.status, TeamJoinRequest.STATUS_PENDING)


class InviteKindTest(TeamFormationBase):
    """9.3 — untied QR invites vs recipient-bound LINK invites."""

    def setUp(self):
        super().setUp()
        self.team = Team.objects.create(name='Kind', session=self.session, color='#666')
        self.staff = _make_user('kind-staff', is_staff=True)
        self.staff.profile.current_session = self.session
        self.staff.profile.save(update_fields=['current_session'])
        self.staff_client = _auth_client(self.staff)

    def test_default_kind_is_qr(self):
        invite = Invite.objects.create(team=self.team, created_by=self.staff)
        self.assertEqual(invite.kind, Invite.KIND_QR)
        self.assertFalse(invite.is_recipient_bound())

    def test_link_invite_requires_email_on_create(self):
        resp = self.staff_client.post(
            reverse('api-invites'),
            {'team': self.team.id, 'kind': 'LINK'},
            format='json',
        )
        self.assertEqual(resp.status_code, 400)

    def test_qr_invite_accepted_by_anyone(self):
        invite = Invite.objects.create(team=self.team, created_by=self.staff)
        stranger = _make_user('stranger')
        client = _auth_client(stranger)
        resp = client.post(reverse('api-invite-accept', args=[invite.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['membership_status'], 'ACTIVE')

    def test_link_invite_403_for_mismatched_account(self):
        invite = Invite.objects.create(
            team=self.team, created_by=self.staff,
            email='bound@example.com', kind=Invite.KIND_LINK,
        )
        interloper = _make_user('interloper', email='other@example.com')
        client = _auth_client(interloper)
        resp = client.post(reverse('api-invite-accept', args=[invite.token]))
        self.assertEqual(resp.status_code, 403)
        invite.refresh_from_db()
        self.assertIsNone(invite.accepted_at)

    def test_link_invite_accepted_by_bound_recipient(self):
        invite = Invite.objects.create(
            team=self.team, created_by=self.staff,
            email='Bound@Example.com', kind=Invite.KIND_LINK,
        )
        recipient = _make_user('recipient', email='bound@example.com')
        client = _auth_client(recipient)
        resp = client.post(reverse('api-invite-accept', args=[invite.token]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['membership_status'], 'ACTIVE')

    def test_link_invite_anon_signup_must_use_bound_email(self):
        invite = Invite.objects.create(
            team=self.team, created_by=self.staff,
            email='bound2@example.com', kind=Invite.KIND_LINK,
        )
        resp = self.client.post(
            reverse('api-invite-accept', args=[invite.token]),
            {'username': 'sneak', 'email': 'sneak@example.com', 'password': 'password12345'},
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(User.objects.filter(username='sneak').exists())
        ok = self.client.post(
            reverse('api-invite-accept', args=[invite.token]),
            {'username': 'legit', 'email': 'bound2@example.com', 'password': 'password12345'},
            content_type='application/json',
        )
        self.assertEqual(ok.status_code, 200)

    def test_preview_reports_kind_and_binding(self):
        invite = Invite.objects.create(
            team=self.team, created_by=self.staff,
            email='bound3@example.com', kind=Invite.KIND_LINK,
        )
        resp = self.client.get(reverse('api-invite-preview', args=[invite.token]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['kind'], 'LINK')
        self.assertTrue(body['recipient_bound'])

    def test_accept_defers_to_pending_when_confirmation_required(self):
        self.game.team_join_confirmation = JOIN_CONFIRM_STAFF
        self.game.save()
        invite = Invite.objects.create(team=self.team, created_by=self.staff)
        joiner = _make_user('joiner')
        client = _auth_client(joiner)
        resp = client.post(reverse('api-invite-accept', args=[invite.token]))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['membership_status'], 'PENDING')
        self.assertIsNotNone(body['join_request_id'])
        self.assertFalse(
            TeamMembership.objects.filter(team=self.team, user=joiner.profile).exists()
        )
        jr = TeamJoinRequest.objects.get(pk=body['join_request_id'])
        self.assertEqual(jr.source, TeamJoinRequest.SOURCE_QR)
        invite.refresh_from_db()
        self.assertIsNotNone(invite.accepted_at)


class CaptainInviteManagementTest(TeamFormationBase):
    """6.1 — captains manage their own team's invites when enabled."""

    def setUp(self):
        super().setUp()
        self._enable_toggle()
        self.captain, self.team, self.captain_client = self._captain_team()
        _, self.other_team, _ = self._captain_team(username='cap-b', name='Storks')

    def test_captain_creates_invite_for_own_team(self):
        resp = self.captain_client.post(
            reverse('api-invites'), {'team': self.team.id}, format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['kind'], 'QR')

    def test_captain_denied_when_toggle_off(self):
        self.game.allow_player_team_creation = False
        self.game.save()
        resp = self.captain_client.post(
            reverse('api-invites'), {'team': self.team.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_captain_cannot_invite_for_other_team(self):
        resp = self.captain_client.post(
            reverse('api-invites'), {'team': self.other_team.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_captain_list_scoped_to_own_team(self):
        Invite.objects.create(team=self.team, created_by=self.captain)
        Invite.objects.create(team=self.other_team, created_by=self.captain)
        resp = self.captain_client.get(reverse('api-invites'))
        self.assertEqual(resp.status_code, 200)
        teams = {i['team'] for i in resp.json()}
        self.assertEqual(teams, {self.team.id})

    def test_captain_revokes_own_invite(self):
        invite = Invite.objects.create(team=self.team, created_by=self.captain)
        resp = self.captain_client.delete(
            reverse('api-invite-destroy', args=[invite.id]),
        )
        self.assertEqual(resp.status_code, 204)
        invite.refresh_from_db()
        self.assertTrue(invite.revoked)

    def test_captain_cannot_revoke_other_teams_invite(self):
        invite = Invite.objects.create(team=self.other_team, created_by=self.captain)
        resp = self.captain_client.delete(
            reverse('api-invite-destroy', args=[invite.id]),
        )
        self.assertEqual(resp.status_code, 404)
        invite.refresh_from_db()
        self.assertFalse(invite.revoked)

    def test_captain_resends_own_email_invite(self):
        invite = Invite.objects.create(
            team=self.team, created_by=self.captain,
            email='friend@example.com', kind=Invite.KIND_LINK,
        )
        resp = self.captain_client.post(reverse('api-invite-resend', args=[invite.id]))
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(len(mail.outbox), 1)

    def test_plain_member_cannot_create_invites(self):
        member, client = self._player('plainmember')
        TeamMembership.objects.create(team=self.team, user=member.profile, is_active=True)
        resp = client.post(
            reverse('api-invites'), {'team': self.team.id}, format='json',
        )
        self.assertEqual(resp.status_code, 403)


class ShuffleBalanceTest(TeamFormationBase):
    """9.7 — staff shuffle / balanced team building."""

    def setUp(self):
        super().setUp()
        self.staff = _make_user('mixer', is_staff=True)
        self.staff.profile.current_session = self.session
        self.staff.profile.save(update_fields=['current_session'])
        self.staff_client = _auth_client(self.staff)

    def _unassigned(self, username, attributes=None):
        user = _make_user(username)
        user.profile.current_session = self.session
        if attributes is not None:
            user.profile.attributes = attributes
        user.profile.save()
        return user

    def _shuffle(self, payload):
        return self.staff_client.post(
            f'/api/staff/sessions/{self.session.id}/shuffle-teams/',
            payload, format='json',
        )

    def _balance(self, payload):
        return self.staff_client.post(
            f'/api/staff/sessions/{self.session.id}/balance-teams/',
            payload, format='json',
        )

    def test_shuffle_distributes_all_unassigned(self):
        for i in range(7):
            self._unassigned(f'sh{i}')
        resp = self._shuffle({'team_count': 3})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['assigned'], 7)
        self.assertEqual(len(body['teams']), 3)
        sizes = sorted(len(t['members']) for t in body['teams'])
        self.assertEqual(sizes, [2, 2, 3])
        self.assertEqual(
            TeamMembership.objects.filter(
                team__session=self.session, is_active=True,
            ).count(),
            7,
        )

    def test_shuffle_skips_already_assigned_players(self):
        assigned = self._unassigned('taken')
        team = Team.objects.create(name='Set', session=self.session, color='#777')
        TeamMembership.objects.create(team=team, user=assigned.profile, is_active=True)
        self._unassigned('free')
        resp = self._shuffle({'team_count': 1})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['assigned'], 1)
        self.assertEqual(resp.json()['teams'][0]['members'], ['free'])

    def test_shuffle_requires_team_count(self):
        self._unassigned('lonely')
        self.assertEqual(self._shuffle({}).status_code, 400)

    def test_shuffle_400_with_no_unassigned_players(self):
        self.assertEqual(self._shuffle({'team_count': 2}).status_code, 400)

    def test_shuffle_requires_staff(self):
        _, player_client = self._player('nobody')
        resp = player_client.post(
            f'/api/staff/sessions/{self.session.id}/shuffle-teams/',
            {'team_count': 2}, format='json',
        )
        self.assertEqual(resp.status_code, 403)

    def test_balance_spreads_attribute_buckets(self):
        for i in range(3):
            self._unassigned(f'young{i}', attributes={'age': 'young'})
        for i in range(3):
            self._unassigned(f'old{i}', attributes={'age': 'old'})
        resp = self._balance({'team_count': 3, 'attribute_keys': ['age']})
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body['assigned'], 6)
        for team in body['teams']:
            self.assertEqual(len(team['members']), 2)
            ages = {
                UserProfile.objects.get(user__username=m).attributes['age']
                for m in team['members']
            }
            self.assertEqual(ages, {'young', 'old'})

    def test_balance_requires_keys(self):
        self._unassigned('kv')
        self.assertEqual(self._balance({'team_count': 2}).status_code, 400)


class EffectiveConfigPayloadTest(TeamFormationBase):
    """1.4 — effective values surface on /api/me/ and current-session."""

    def test_current_session_payload_carries_toggle_and_policy(self):
        self.session.allow_player_team_creation = True
        self.session.save()
        TeamGroup.objects.create(name='Cubs', game=self.game, slug='cubs')
        _, client = self._player('payload')
        resp = client.get(reverse('api-current-session'))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['allow_player_team_creation'])
        self.assertFalse(body['game']['allow_player_team_creation'])
        self.assertEqual(body['game']['team_join_confirmation'], JOIN_CONFIRM_AUTO_APPROVE)
        self.assertEqual(
            body['game']['team_groups'], [{'id': TeamGroup.objects.get().id, 'name': 'Cubs', 'slug': 'cubs'}],
        )

    def test_me_payload_carries_effective_toggle_and_captaincy(self):
        self._enable_toggle()
        _, _, client = self._captain_team(username='me-cap', name='MeTeam')
        resp = client.get(reverse('api-me'))
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['allow_player_team_creation'])
        self.assertEqual(body['captain_of_team_id'], body['active_team_id'])

    def test_me_toggle_false_without_session(self):
        user = _make_user('sessionless')
        client = _auth_client(user)
        body = client.get(reverse('api-me')).json()
        self.assertFalse(body['allow_player_team_creation'])
        self.assertIsNone(body['captain_of_team_id'])
