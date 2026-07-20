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
    Game,
    Invite,
    Session,
    Team,
    TeamMembership,
    UserProfile,
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


class SessionStateMigrationTest(TransactionTestCase):
    """game-lifecycle-states 7.2 — the 0012 backfill maps the legacy
    boolean (and open pause windows) onto the new lifecycle states, and
    the derived-active set matches the pre-migration is_active set."""

    migrate_from = [
        ('organize', '0011_session_state'),
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
