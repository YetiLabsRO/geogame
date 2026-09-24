"""Tests for the MCP authoring server (mcp-authoring capability).

Covers auth/scope, the suggest-only guarantee, the human approval gate,
temp-ref dependency apply, partial apply, staff-API parity,
append-only audit, and stage→apply re-authorization.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from authoring.engine import RefError, apply_proposal, topological_order
from authoring.models import (
    OP_APPROVED,
    OP_FAILED,
    PROPOSAL_APPLIED,
    PROPOSAL_APPROVED,
    PROPOSAL_FAILED,
    PROPOSAL_PARTIALLY_APPLIED,
    AuthoringAuditEvent,
    AuthoringProposal,
    AuthoringSession,
    McpCredential,
    ProposedOperation,
)
from authoring.tools import AuthoringTools
from game.models import Challenge, Collection, Tower
from organize.models import Game, Session, Team

User = get_user_model()


def _staff(username, superuser=False):
    return User.objects.create_user(
        username=username, password='pw', is_staff=True, is_superuser=superuser,
    )


def _game(creator, name):
    slug = name.lower().replace(' ', '-')
    return Game.objects.create(name=name, slug=slug, created_by=creator)


def _tools(user, **session_kwargs):
    session = AuthoringSession.objects.create(created_by=user, **session_kwargs)
    return AuthoringTools(user, session=session)


class CredentialAndScopeTests(TestCase):
    """Task 8.1 — credential binds to creator; reads are creator-scoped."""

    def test_credential_issue_verify_revoke(self):
        user = _staff('alice')
        credential, raw = McpCredential.issue(user, label='laptop')
        self.assertTrue(raw.startswith('mcp_'))
        self.assertEqual(McpCredential.verify(raw), credential)
        self.assertIsNone(McpCredential.verify('mcp_wrong'))
        credential.revoke()
        self.assertIsNone(McpCredential.verify(raw))

    def test_reads_are_creator_scoped(self):
        alice, bob = _staff('alice'), _staff('bob')
        game_a = _game(alice, 'Alba Run')
        _game(bob, 'Bob Town')
        tools = _tools(alice)
        games = tools.list_games()
        self.assertEqual({g['id'] for g in games}, {game_a.id})

    def test_out_of_scope_read_denied(self):
        alice, bob = _staff('alice'), _staff('bob')
        game_b = _game(bob, 'Bob Town')
        tools = _tools(alice)
        with self.assertRaises(PermissionDenied):
            tools.get_game(game_b.id)

    def test_non_staff_cannot_get_tools(self):
        player = User.objects.create_user(username='p', password='pw', is_staff=False)
        with self.assertRaises(PermissionDenied):
            AuthoringTools(player)


class NoLiveWriteTests(TestCase):
    """Task 8.2 — staging never touches real tables."""

    def test_propose_and_suggest_write_nothing(self):
        alice = _staff('alice')
        game = _game(alice, 'Alba Run')
        tools = _tools(alice)
        before = (Collection.objects.count(), Tower.objects.count(), Challenge.objects.count())

        tools.propose_collection('Old Town', temp_ref='c1', rationale='landmarks cluster')
        tools.propose_tower('Clock Tower', lat=46.07, lng=23.57, temp_ref='t1',
                            rationale='central', collection='@new:c1')
        tools.suggest_challenge(
            game_ref=game.id, text='How old is the clock?', difficulty=2,
            rationale='ties to the landmark', tower_ref='@new:t1',
        )

        after = (Collection.objects.count(), Tower.objects.count(), Challenge.objects.count())
        self.assertEqual(before, after)
        proposal = AuthoringProposal.objects.get()
        self.assertEqual(proposal.operations.count(), 3)


class HumanGateTests(TestCase):
    """Task 8.3 — only a human approves; unapproved cannot apply."""

    def setUp(self):
        self.alice = _staff('alice')
        self.tools = _tools(self.alice)
        self.tools.propose_collection('Old Town', rationale='cluster')
        self.proposal = AuthoringProposal.objects.get()

    def test_mcp_tools_expose_no_approval(self):
        # Structural guarantee: no self-approval path on the LLM surface.
        self.assertFalse(hasattr(self.tools, 'approve'))
        self.assertFalse(hasattr(self.tools, 'apply'))

    def test_unapproved_cannot_apply(self):
        self.tools.submit_for_approval(self.proposal.id)
        client = APIClient()
        client.force_authenticate(self.alice)
        resp = client.post(f'/api/staff/authoring/proposals/{self.proposal.id}/apply/')
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(Collection.objects.count(), 0)

    def test_approved_then_applied_writes(self):
        self.tools.submit_for_approval(self.proposal.id)
        client = APIClient()
        client.force_authenticate(self.alice)
        approve = client.post(f'/api/staff/authoring/proposals/{self.proposal.id}/approve/')
        self.assertEqual(approve.status_code, 200)
        apply = client.post(f'/api/staff/authoring/proposals/{self.proposal.id}/apply/')
        self.assertEqual(apply.status_code, 200)
        self.assertEqual(apply.data['status'], PROPOSAL_APPLIED)
        self.assertTrue(Collection.objects.filter(name='Old Town').exists())

    def test_another_creator_cannot_review(self):
        bob = _staff('bob')
        client = APIClient()
        client.force_authenticate(bob)
        resp = client.post(f'/api/staff/authoring/proposals/{self.proposal.id}/approve/')
        self.assertEqual(resp.status_code, 403)


class TempRefApplyTests(TestCase):
    """Task 8.4 — dependency-ordered apply; bad refs rejected pre-write."""

    def test_collection_towers_challenges_apply_in_order(self):
        alice = _staff('alice')
        game = _game(alice, 'Alba Run')
        tools = _tools(alice)
        tools.propose_collection('Old Town', temp_ref='c1', rationale='cluster')
        tools.propose_tower('Clock Tower', lat=46.07, lng=23.57, temp_ref='t1',
                            rationale='central', collection='@new:c1')
        tools.suggest_challenge(
            game_ref=game.id, text='How old is the clock?', difficulty=2,
            rationale='landmark', tower_ref='@new:t1',
        )
        proposal = AuthoringProposal.objects.get()
        tools.submit_for_approval(proposal.id)
        _approve_and_apply(alice, proposal)

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, PROPOSAL_APPLIED)
        collection = Collection.objects.get(name='Old Town')
        tower = Tower.objects.get(name='Clock Tower')
        challenge = Challenge.objects.get(text='How old is the clock?')
        self.assertIn(tower, collection.towers.all())
        self.assertEqual(challenge.tower_id, tower.id)
        self.assertEqual(challenge.game_id, game.id)

    def test_unresolved_ref_rejected_before_write(self):
        alice = _staff('alice')
        tools = _tools(alice)
        tools.propose_tower('Ghost', lat=46.0, lng=23.0, rationale='x',
                            collection='@new:missing')
        proposal = AuthoringProposal.objects.get()
        for op in proposal.operations.all():
            op.status = OP_APPROVED
            op.save()
        with self.assertRaises(RefError):
            apply_proposal(proposal, actor=alice)
        self.assertEqual(Tower.objects.count(), 0)

    def test_cyclic_refs_rejected(self):
        alice = _staff('alice')
        proposal = AuthoringProposal.objects.create(
            session=AuthoringSession.objects.create(created_by=alice),
            created_by=alice,
        )
        a = ProposedOperation.objects.create(
            proposal=proposal, entity_type='COLLECTION', action='CREATE',
            temp_ref='a', payload={'name': '@new:b'}, order=0, status=OP_APPROVED,
        )
        ProposedOperation.objects.create(
            proposal=proposal, entity_type='COLLECTION', action='CREATE',
            temp_ref='b', payload={'name': '@new:a'}, order=1, status=OP_APPROVED,
        )
        with self.assertRaises(RefError):
            topological_order([a, *proposal.operations.exclude(pk=a.pk)])


class PartialApplyTests(TestCase):
    """Task 8.5 — per-op decisions; failure isolation vs atomic rollback."""

    def _proposal(self, alice, atomic):
        game = _game(alice, 'Alba Run')
        tools = _tools(alice)
        tools.propose_collection('Good', temp_ref='c1', rationale='ok')
        # An invalid challenge: it points at a tower that does not exist,
        # so the serializer rejects it at apply time.
        tools.suggest_challenge(
            game_ref=game.id, text='bad one', difficulty=1, rationale='bad',
            tower_ref=999999,
        )
        proposal = AuthoringProposal.objects.get()
        proposal.atomic = atomic
        proposal.save()
        return proposal

    def test_per_operation_reject_applies_only_approved(self):
        alice = _staff('alice')
        tools = _tools(alice)
        tools.propose_collection('Keep', temp_ref='c1', rationale='ok')
        tools.propose_collection('Drop', temp_ref='c2', rationale='no')
        proposal = AuthoringProposal.objects.get()
        drop = proposal.operations.get(payload__name='Drop')
        client = APIClient()
        client.force_authenticate(alice)
        client.post(
            f'/api/staff/authoring/proposals/{proposal.id}/operations/{drop.id}/reject/',
        )
        _approve_and_apply(alice, proposal)
        self.assertTrue(Collection.objects.filter(name='Keep').exists())
        self.assertFalse(Collection.objects.filter(name='Drop').exists())

    def test_non_atomic_failure_is_isolated(self):
        alice = _staff('alice')
        proposal = self._proposal(alice, atomic=False)
        _approve_and_apply(alice, proposal)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, PROPOSAL_PARTIALLY_APPLIED)
        self.assertTrue(Collection.objects.filter(name='Good').exists())
        self.assertTrue(proposal.operations.filter(status=OP_FAILED).exists())

    def test_atomic_failure_rolls_back(self):
        alice = _staff('alice')
        proposal = self._proposal(alice, atomic=True)
        _approve_and_apply(alice, proposal)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, PROPOSAL_FAILED)
        self.assertFalse(Collection.objects.filter(name='Good').exists())


class ParityTests(TestCase):
    """Task 8.6 — a stitched proposal produces the staff-API record."""

    def test_collection_apply_matches_staff_api(self):
        alice = _staff('alice', superuser=True)
        payload = {'name': 'Parity Town', 'description': 'same both ways'}

        client = APIClient()
        client.force_authenticate(alice)
        api_resp = client.post('/api/staff/collections/', payload, format='json')
        self.assertEqual(api_resp.status_code, 201, api_resp.content)

        tools = _tools(alice)
        tools.propose_collection('Parity Town 2', description='same both ways',
                                rationale='parity')
        proposal = AuthoringProposal.objects.get()
        _approve_and_apply(alice, proposal)

        staged = Collection.objects.get(name='Parity Town 2')
        api_made = Collection.objects.get(name='Parity Town')
        self.assertEqual(staged.description, api_made.description)
        self.assertEqual(staged.created_by_id, api_made.created_by_id)


class AuditTests(TestCase):
    """Task 8.7 — every action recorded, append-only."""

    def test_tool_calls_and_transitions_recorded(self):
        alice = _staff('alice')
        tools = _tools(alice)
        tools.list_games()
        tools.propose_collection('Town', rationale='x')
        proposal = AuthoringProposal.objects.get()
        tools.submit_for_approval(proposal.id)
        _approve_and_apply(alice, proposal)

        events = AuthoringAuditEvent.objects.filter(created_by=alice)
        names = set(events.values_list('tool_name', flat=True))
        self.assertIn('list_games', names)
        self.assertIn('stage_operation', names)
        self.assertIn('approve', names)
        self.assertIn('apply_proposal', names)

    def test_audit_events_are_immutable(self):
        alice = _staff('alice')
        event = AuthoringAuditEvent.objects.create(
            event_type='TOOL_CALL', created_by=alice, tool_name='x',
        )
        event.tool_name = 'y'
        with self.assertRaises(NotImplementedError):
            event.save()
        with self.assertRaises(NotImplementedError):
            event.delete()
        with self.assertRaises(NotImplementedError):
            AuthoringAuditEvent.objects.filter(pk=event.pk).delete()


class ReauthorizationTests(TestCase):
    """Task 8.8 — losing access between stage and apply fails at apply."""

    def test_lost_access_fails_at_apply(self):
        alice, bob = _staff('alice'), _staff('bob')
        game = _game(alice, 'Alba Run')
        tools = _tools(alice)
        # Stage an UPDATE to the game's name while alice still owns it.
        tools._stage(
            'GAME', 'UPDATE', {'name': 'Renamed'}, rationale='rename',
            target_ref=str(game.id),
        )
        proposal = AuthoringProposal.objects.get()
        # Ownership moves to bob before approval/apply; alice loses edit rights.
        game.created_by = bob
        game.save(update_fields=['created_by'])

        _approve_and_apply(alice, proposal)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, PROPOSAL_FAILED)
        game.refresh_from_db()
        self.assertEqual(game.name, 'Alba Run')


def _approve_and_apply(user, proposal):
    """Approve (as the creator) then apply — mirrors the staff UI flow."""
    client = APIClient()
    client.force_authenticate(user)
    approve = client.post(f'/api/staff/authoring/proposals/{proposal.id}/approve/')
    assert approve.status_code == 200, approve.content
    proposal.refresh_from_db()
    assert proposal.status == PROPOSAL_APPROVED
    client.post(f'/api/staff/authoring/proposals/{proposal.id}/apply/')


class ReadToolsTests(TestCase):
    """Read surface: every discovery tool, all creator-scoped."""

    def setUp(self):
        from django.contrib.gis.geos import Point

        from game.models import Zone
        from organize.models import GameRole, TeamGroup
        self.alice = _staff('alice')
        self.game = _game(self.alice, 'Alba Run')
        self.collection = Collection.objects.create(
            name='Old Town', slug='old-town', created_by=self.alice,
        )
        self.tower = Tower.objects.create(
            name='Clock', location=Point(23.57, 46.07), category=1, is_active=True,
        )
        self.zone = Zone.objects.create(name='Centre', scoring_type=Zone.SCORE_LIN)
        self.collection.towers.add(self.tower)
        self.collection.zones.add(self.zone)
        Challenge.objects.create(game=self.game, text='Q1', difficulty=1)
        TeamGroup.objects.create(game=self.game, name='Explorers', slug='exp')
        GameRole.objects.create(game=self.game, name='Cook', slug='cook')
        self.tools = _tools(self.alice)

    def test_all_read_tools(self):
        self.assertEqual(len(self.tools.list_collections()), 1)
        self.assertEqual(self.tools.get_collection(self.collection.id)['name'], 'Old Town')
        self.assertEqual(len(self.tools.list_towers()), 1)
        self.assertEqual(len(self.tools.list_towers(collection_id=self.collection.id)), 1)
        self.assertEqual(len(self.tools.list_zones()), 1)
        self.assertEqual(len(self.tools.list_challenges()), 1)
        self.assertEqual(len(self.tools.list_challenges(game_id=self.game.id)), 1)
        self.assertEqual(self.tools.get_game(self.game.id)['name'], 'Alba Run')
        self.assertEqual(len(self.tools.list_team_groups(self.game.id)), 1)
        self.assertEqual(len(self.tools.list_game_roles(self.game.id)), 1)
        schema = self.tools.describe_config_schema()
        self.assertGreater(schema['count'], 0)

    def test_out_of_scope_challenge_list_denied(self):
        bob = _staff('bob')
        other = _game(bob, 'Bob Town')
        with self.assertRaises(PermissionDenied):
            self.tools.list_challenges(game_id=other.id)

    def test_out_of_scope_team_groups_denied(self):
        bob = _staff('bob')
        other = _game(bob, 'Bob Town')
        with self.assertRaises(PermissionDenied):
            self.tools.list_team_groups(other.id)
        with self.assertRaises(PermissionDenied):
            self.tools.list_game_roles(other.id)
        with self.assertRaises(PermissionDenied):
            self.tools.get_collection(
                Collection.objects.create(name='x', slug='bob-x', created_by=bob).id,
            )


class StageToolsTests(TestCase):
    """Every suggest/stage tool + proposal management."""

    def setUp(self):
        self.alice = _staff('alice')
        self.game = _game(self.alice, 'Alba Run')
        self.tools = _tools(self.alice)

    def test_stage_all_entity_kinds(self):
        opened = self.tools.open_proposal(summary='full draft', atomic=False)
        self.assertEqual(opened['operation_count'], 0)
        self.tools.propose_collection('Town', temp_ref='c1', rationale='x')
        self.tools.propose_zone('Sq', vertices=[[23.0, 46.0], [23.1, 46.0], [23.1, 46.1]],
                               temp_ref='z1', rationale='plaza')
        self.tools.propose_game('New Game', temp_ref='g1', rationale='fresh')
        self.tools.propose_game_role('@new:g1', 'Cook', temp_ref='r1', rationale='role')
        self.tools.propose_config(self.game.id, {'cooloff_minutes': 3}, rationale='tune')
        self.tools.propose_link('@new:c1', towers=[], zones=[], rationale='link')
        self.tools.suggest_challenges([
            {'game_ref': self.game.id, 'text': 'A', 'difficulty': 1, 'rationale': 'a'},
            {'game_ref': self.game.id, 'text': 'B', 'difficulty': 2, 'rationale': 'b'},
        ])
        proposal = AuthoringProposal.objects.filter(created_by=self.alice).first()
        detail = self.tools.get_proposal(proposal.id)
        self.assertGreaterEqual(detail['operation_count'], 8)
        self.assertEqual(len(self.tools.list_my_proposals()), 1)

    def test_suggest_challenge_requires_rationale(self):
        with self.assertRaises(ValueError):
            self.tools.suggest_challenge(
                game_ref=self.game.id, text='x', difficulty=1, rationale='',
            )

    def test_submit_empty_proposal_rejected(self):
        opened = self.tools.open_proposal()
        with self.assertRaises(ValueError):
            self.tools.submit_for_approval(opened['id'])

    def test_withdraw_proposal(self):
        self.tools.propose_collection('Town', rationale='x')
        proposal = AuthoringProposal.objects.get()
        result = self.tools.withdraw_proposal(proposal.id)
        self.assertEqual(result['status'], 'WITHDRAWN')

    def test_stage_out_of_scope_existing_target_denied(self):
        bob = _staff('bob')
        other = _game(bob, 'Bob Town')
        with self.assertRaises(PermissionDenied):
            self.tools._stage('GAME', 'UPDATE', {'name': 'Nope'},
                              rationale='x', target_ref=str(other.id))


class ReviewApiTests(TestCase):
    """The staff review + credential endpoints."""

    def setUp(self):
        self.alice = _staff('alice')
        self.tools = _tools(self.alice)
        self.tools.propose_collection('Keep', temp_ref='c1', rationale='ok')
        self.tools.propose_collection('Drop', temp_ref='c2', rationale='no')
        self.proposal = AuthoringProposal.objects.get()
        self.client = APIClient()
        self.client.force_authenticate(self.alice)

    def test_list_and_detail(self):
        resp = self.client.get('/api/staff/authoring/proposals/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data), 1)
        detail = self.client.get(f'/api/staff/authoring/proposals/{self.proposal.id}/')
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(len(detail.data['operations']), 2)

    def test_reject_whole(self):
        resp = self.client.post(f'/api/staff/authoring/proposals/{self.proposal.id}/reject/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'REJECTED')

    def test_withdraw_via_api(self):
        resp = self.client.post(f'/api/staff/authoring/proposals/{self.proposal.id}/withdraw/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['status'], 'WITHDRAWN')

    def test_per_operation_approve_endpoint(self):
        op = self.proposal.operations.first()
        resp = self.client.post(
            f'/api/staff/authoring/proposals/{self.proposal.id}/operations/{op.id}/approve/',
        )
        self.assertEqual(resp.status_code, 200)
        op.refresh_from_db()
        self.assertEqual(op.status, OP_APPROVED)

    def test_audit_endpoint(self):
        resp = self.client.get('/api/staff/authoring/audit/')
        self.assertEqual(resp.status_code, 200)
        self.assertGreater(len(resp.data), 0)

    def test_credential_lifecycle(self):
        create = self.client.post('/api/staff/authoring/credentials/', {'label': 'cli'})
        self.assertEqual(create.status_code, 201)
        self.assertIn('token', create.data)
        listed = self.client.get('/api/staff/authoring/credentials/')
        self.assertEqual(len(listed.data), 1)
        cred_id = create.data['id']
        revoke = self.client.post(f'/api/staff/authoring/credentials/{cred_id}/revoke/')
        self.assertEqual(revoke.status_code, 200)
        self.assertFalse(revoke.data['is_active'])

    def test_detail_forbidden_for_other_creator(self):
        bob = _staff('bob')
        client = APIClient()
        client.force_authenticate(bob)
        resp = client.get(f'/api/staff/authoring/proposals/{self.proposal.id}/')
        self.assertEqual(resp.status_code, 403)


class EngineConfigLinkTests(TestCase):
    """CONFIG apply + LINK apply paths through the engine."""

    def test_config_apply_updates_game(self):
        alice = _staff('alice')
        game = _game(alice, 'Alba Run')
        self.assertTrue(game.realtime_enabled)
        tools = _tools(alice)
        tools.propose_config(game.id, {'realtime_enabled': False}, rationale='tune')
        proposal = AuthoringProposal.objects.get()
        _approve_and_apply(alice, proposal)
        game.refresh_from_db()
        self.assertFalse(game.realtime_enabled)

    def test_link_apply_files_geometry(self):
        from django.contrib.gis.geos import Point
        alice = _staff('alice')
        tools = _tools(alice)
        collection = Collection.objects.create(name='Repo', created_by=alice)
        tower = Tower.objects.create(
            name='T', location=Point(23.5, 46.5), category=1, is_active=True,
        )
        tools.propose_link(str(collection.id), towers=[tower.id], rationale='file it')
        proposal = AuthoringProposal.objects.get()
        _approve_and_apply(alice, proposal)
        self.assertIn(tower, collection.towers.all())

    def test_config_rejects_unknown_field(self):
        from authoring.engine import apply_proposal
        alice = _staff('alice')
        game = _game(alice, 'Alba Run')
        tools = _tools(alice)
        tools.propose_config(game.id, {'not_a_field': 1}, rationale='bad')
        proposal = AuthoringProposal.objects.get()
        proposal.operations.update(status=OP_APPROVED)
        apply_proposal(proposal, actor=alice)
        proposal.refresh_from_db()
        self.assertEqual(proposal.status, PROPOSAL_FAILED)


class McpTransportTests(TestCase):
    """The MCP ASGI transport: auth gate + credential binding + build."""

    def _run(self, app, scope):
        from asgiref.sync import async_to_sync
        sent = []

        async def receive():
            return {'type': 'http.request', 'body': b'', 'more_body': False}

        async def send(msg):
            sent.append(msg)

        async_to_sync(app)(scope, receive, send)
        return sent

    def _http_scope(self, headers):
        return {'type': 'http', 'path': '/mcp/authoring/', 'headers': headers}

    def test_missing_token_401(self):
        from authoring.mcp_server import authoring_asgi_app
        sent = self._run(authoring_asgi_app(), self._http_scope([]))
        self.assertEqual(sent[0]['status'], 401)

    def test_invalid_token_401(self):
        from authoring.mcp_server import authoring_asgi_app
        headers = [(b'authorization', b'Bearer mcp_bogus')]
        sent = self._run(authoring_asgi_app(), self._http_scope(headers))
        self.assertEqual(sent[0]['status'], 401)

    def test_authenticate_binds_creator(self):
        from asgiref.sync import async_to_sync

        from authoring.mcp_server import _authenticate
        alice = _staff('alice')
        _cred, raw = McpCredential.issue(alice, label='cli')
        tools = async_to_sync(_authenticate)(
            raw, [(b'x-mcp-client', b'claude'), (b'x-mcp-model', b'opus')],
        )
        self.assertIsNotNone(tools)
        self.assertEqual(tools.user, alice)
        self.assertEqual(tools.session.client_name, 'claude')
        self.assertEqual(AuthoringSession.objects.filter(created_by=alice).count(), 1)

    def test_authenticate_rejects_bad_token(self):
        from asgiref.sync import async_to_sync

        from authoring.mcp_server import _authenticate
        self.assertIsNone(async_to_sync(_authenticate)('mcp_nope', []))

    def test_server_registers_all_tools(self):
        from asgiref.sync import async_to_sync

        from authoring.mcp_server import _build_server
        server = _build_server()
        tools = async_to_sync(server.list_tools)()
        names = {t.name for t in tools}
        self.assertIn('list_collections', names)
        self.assertIn('suggest_challenge', names)
        self.assertIn('propose_config', names)
        self.assertGreaterEqual(len(names), 20)


# --- Session & team authoring (mcp-session-authoring) ----------------------

def _session(game, slug='run-1', **kwargs):
    fields = {
        'name': kwargs.pop('name', 'Run 1'),
        'start_time': timezone.now() + timedelta(days=1),
        'end_time': timezone.now() + timedelta(days=1, hours=4),
    }
    fields.update(kwargs)
    return Session.objects.create(game=game, slug=slug, **fields)


def _window():
    """A valid future session window as ISO strings, as an LLM would send."""
    start = timezone.now() + timedelta(days=2)
    return start.isoformat(), (start + timedelta(hours=3)).isoformat()


class SessionReadToolTests(TestCase):
    """Tasks 7.1, 7.2 — session reads are creator-scoped and show provenance."""

    def test_list_sessions_is_creator_scoped(self):
        alice, bob = _staff('alice'), _staff('bob')
        mine = _session(_game(alice, 'Alba Run'))
        _session(_game(bob, 'Bob Town'), slug='theirs')
        listed = _tools(alice).list_sessions()
        self.assertEqual({s['id'] for s in listed}, {mine.id})

    def test_list_sessions_filtered_by_out_of_scope_game_denied(self):
        alice, bob = _staff('alice'), _staff('bob')
        theirs = _game(bob, 'Bob Town')
        with self.assertRaises(PermissionDenied):
            _tools(alice).list_sessions(game_id=theirs.id)

    def test_get_session_out_of_scope_denied(self):
        alice, bob = _staff('alice'), _staff('bob')
        theirs = _session(_game(bob, 'Bob Town'))
        with self.assertRaises(PermissionDenied):
            _tools(alice).get_session(theirs.id)

    def test_get_session_reports_override_versus_inherited(self):
        alice = _staff('alice')
        game = _game(alice, 'Alba Run')
        game.max_teams = 8
        game.save(update_fields=['max_teams'])
        session = _session(game, max_teams=4)

        config = _tools(alice).get_session(session.id)['config']

        # Overridden on the session: reported as an override, not inherited.
        self.assertEqual(config['max_teams']['override'], 4)
        self.assertEqual(config['max_teams']['effective'], 4)
        self.assertFalse(config['max_teams']['inherited'])
        # Left null: no override, effective value falls back to the game.
        self.assertIsNone(config['min_teams']['override'])
        self.assertTrue(config['min_teams']['inherited'])
        self.assertEqual(config['min_teams']['effective'], game.min_teams)

    def test_config_schema_declares_session_scope(self):
        knobs = _tools(_staff('alice')).describe_config_schema()['knobs']
        self.assertTrue(all(k['scopes'] == ['game', 'session'] for k in knobs))


class ProposeSessionTests(TestCase):
    """Tasks 7.3, 7.5, 7.10 — staging a session stays suggest-only."""

    def setUp(self):
        self.alice = _staff('alice')
        self.game = _game(self.alice, 'Alba Run')
        self.tools = _tools(self.alice)

    def test_propose_session_stages_without_writing(self):
        start, end = _window()
        op = self.tools.propose_session(
            self.game.id, name='Saturday', slug='saturday',
            start_time=start, end_time=end, rationale='Weekend run.',
        )
        self.assertEqual(op['entity_type'], 'SESSION')
        self.assertEqual(Session.objects.count(), 0)

    def test_applied_session_lands_in_draft(self):
        start, end = _window()
        self.tools.propose_session(
            self.game.id, name='Saturday', slug='saturday',
            start_time=start, end_time=end, rationale='Weekend run.',
        )
        proposal = self.tools._current_proposal()
        self.tools.submit_for_approval(proposal.id)
        _approve_and_apply(self.alice, proposal)

        session = Session.objects.get(slug='saturday')
        self.assertEqual(session.state, Session.DRAFT)
        self.assertEqual(session.created_by, self.alice)

    def test_proposed_state_is_never_written(self):
        start, end = _window()
        self.tools.propose_session(
            self.game.id, name='Saturday', slug='saturday',
            start_time=start, end_time=end, rationale='Weekend run.',
            state=Session.RUNNING,
        )
        op = self.tools._current_proposal().operations.get()
        self.assertNotIn('state', op.payload)

        proposal = self.tools._current_proposal()
        self.tools.submit_for_approval(proposal.id)
        _approve_and_apply(self.alice, proposal)
        self.assertEqual(Session.objects.get(slug='saturday').state, Session.DRAFT)

    def test_colliding_slug_fails_the_operation(self):
        _session(self.game, slug='saturday')
        start, end = _window()
        self.tools.propose_session(
            self.game.id, name='Saturday', slug='saturday',
            start_time=start, end_time=end, rationale='Duplicate.',
        )
        proposal = self.tools._current_proposal()
        self.tools.submit_for_approval(proposal.id)
        _approve_and_apply(self.alice, proposal)

        proposal.refresh_from_db()
        self.assertEqual(proposal.status, PROPOSAL_FAILED)
        op = proposal.operations.get()
        self.assertEqual(op.status, OP_FAILED)
        self.assertTrue(op.error)
        self.assertEqual(Session.objects.filter(game=self.game).count(), 1)

    def test_out_of_scope_session_staging_refused(self):
        bob = _staff('bob')
        theirs = _game(bob, 'Bob Town')
        start, end = _window()
        with self.assertRaises(PermissionDenied):
            self.tools.propose_session(
                theirs.id, name='Nope', slug='nope',
                start_time=start, end_time=end, rationale='Not mine.',
            )


class ProposeTeamTests(TestCase):
    """Tasks 7.4, 7.7 — teams stage under a session and apply empty."""

    def setUp(self):
        self.alice = _staff('alice')
        self.tools = _tools(self.alice)

    def test_game_session_team_chain_applies_in_order(self):
        start, end = _window()
        self.tools.propose_game(
            'Chain Town', slug='chain-town', temp_ref='g1', rationale='New town.',
        )
        self.tools.propose_session(
            '@new:g1', name='Saturday', slug='saturday',
            start_time=start, end_time=end, temp_ref='s1', rationale='Weekend.',
        )
        self.tools.propose_team(
            '@new:s1', name='Vulturii', color='#ff0000', rationale='One patrol.',
        )
        proposal = self.tools._current_proposal()
        self.tools.submit_for_approval(proposal.id)
        _approve_and_apply(self.alice, proposal)

        proposal.refresh_from_db()
        self.assertEqual(
            proposal.status, PROPOSAL_APPLIED,
            [(op.entity_type, op.status, op.error) for op in proposal.operations.all()],
        )
        team = Team.objects.get(name='Vulturii')
        self.assertEqual(team.session.slug, 'saturday')
        self.assertEqual(team.session.game.name, 'Chain Town')

    def test_applied_team_has_no_members(self):
        game = _game(self.alice, 'Alba Run')
        session = _session(game)
        self.tools.propose_team(
            session.id, name='Vulturii', color='#ff0000', rationale='One patrol.',
        )
        proposal = self.tools._current_proposal()
        self.tools.submit_for_approval(proposal.id)
        _approve_and_apply(self.alice, proposal)

        team = Team.objects.get(name='Vulturii')
        self.assertEqual(team.members.count(), 0)
        self.assertIsNone(team.captain)

    def test_membership_in_payload_is_refused_and_audited(self):
        game = _game(self.alice, 'Alba Run')
        session = _session(game)
        before = AuthoringAuditEvent.objects.count()
        with self.assertRaises(PermissionDenied):
            self.tools.propose_team(
                session.id, name='Vulturii', color='#ff0000',
                rationale='Roster.', members=[1, 2],
            )
        self.assertEqual(Team.objects.filter(name='Vulturii').count(), 0)
        self.assertGreater(AuthoringAuditEvent.objects.count(), before)

    def test_out_of_scope_team_staging_refused(self):
        bob = _staff('bob')
        theirs = _session(_game(bob, 'Bob Town'))
        with self.assertRaises(PermissionDenied):
            self.tools.propose_team(
                theirs.id, name='Nope', color='#ff0000', rationale='Not mine.',
            )


class SessionConfigScopeTests(TestCase):
    """Task 7.9 — session-scoped config is checked against the knob list."""

    def setUp(self):
        self.alice = _staff('alice')
        self.game = _game(self.alice, 'Alba Run')
        self.session = _session(self.game)
        self.tools = _tools(self.alice)

    def test_session_scoped_override_stages(self):
        op = self.tools.propose_config(
            self.session.id, {'max_teams': 6}, scope='session',
            rationale='Smaller field.',
        )
        self.assertEqual(op['entity_type'], 'CONFIG')

    def test_non_overridable_knob_rejected_with_scopes(self):
        with self.assertRaises(ValueError) as caught:
            self.tools.propose_config(
                self.session.id, {'slug': 'nope'}, scope='session',
                rationale='Bad knob.',
            )
        self.assertIn('scope "game" only', str(caught.exception))


class LifecycleIsNotAuthorableTests(TestCase):
    """Task 7.6 — no tool stages or performs a lifecycle transition."""

    def test_no_transition_tool_is_published(self):
        from asgiref.sync import async_to_sync

        from authoring.mcp_server import _build_server
        names = {t.name for t in async_to_sync(_build_server().list_tools)()}
        self.assertIn('propose_session', names)
        self.assertIn('propose_team', names)
        self.assertIn('list_sessions', names)
        for action, _from, _to in Session.TRANSITIONS:
            self.assertNotIn(action, names)
            self.assertNotIn(f'propose_{action}', names)

    def test_tools_expose_no_transition_method(self):
        for action, _from, _to in Session.TRANSITIONS:
            self.assertFalse(hasattr(AuthoringTools, action))

    def test_apply_cannot_transition_an_existing_session(self):
        alice = _staff('alice')
        game = _game(alice, 'Alba Run')
        session = _session(game)
        tools = _tools(alice)
        # A CONFIG update naming `state` is not an overridable knob.
        with self.assertRaises(ValueError):
            tools.propose_config(
                session.id, {'state': Session.RUNNING}, scope='session',
                rationale='Sneaky start.',
            )
        session.refresh_from_db()
        self.assertEqual(session.state, Session.DRAFT)
