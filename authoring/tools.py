"""The authoring tool surface: creator-scoped reads + suggest-only stages.

Every function here runs AS a specific creator user (never the LLM's own
identity) and touches only that user's authorable elements. Read tools
serialize through the staff serializers; stage tools append
`ProposedOperation`s and never write real game content. The MCP server
(`authoring.mcp_server`) is a thin transport over this class; the DRF
tests exercise it directly.
"""
from django.core.exceptions import PermissionDenied

from game.admin_api import (
    AdminChallengeSerializer,
    AdminCollectionSerializer,
    AdminGameRoleSerializer,
    AdminGameSerializer,
    AdminTeamGroupSerializer,
)
from game.models import Challenge, Collection, Tower, Zone
from organize.models import Game, GameRole, TeamGroup

from .config_schema import describe_config_schema
from .engine import authorize_operation
from .models import (
    ACTION_CREATE,
    ACTION_LINK,
    ACTION_UPDATE,
    ENTITY_CHALLENGE,
    ENTITY_COLLECTION,
    ENTITY_CONFIG,
    ENTITY_GAME,
    ENTITY_GAME_ROLE,
    ENTITY_TOWER,
    ENTITY_ZONE,
    EVENT_TOOL_CALL,
    PROPOSAL_DRAFT,
    PROPOSAL_PENDING,
    TEMP_REF_PREFIX,
    AuthoringProposal,
    ProposedOperation,
    record_event,
)

_STAFF_CONTEXT = {'request': None}


def authorable_games(user):
    """Games this creator may edit (template-authoring scope)."""
    return [game for game in Game.objects.all().order_by('name') if game.can_edit(user)]


def authorable_collections(user):
    """Collections this creator may author into."""
    return [
        collection
        for collection in Collection.objects.all().order_by('name')
        if collection.can_author(user)
    ]


class AuthoringTools:
    """Bound tool surface for one creator + one authoring session."""

    def __init__(self, user, session=None):
        self.user = user
        self.session = session
        if not getattr(user, 'is_staff', False):
            raise PermissionDenied('Authoring requires a staff account.')

    # -- audit -------------------------------------------------------------

    def _audit(self, tool_name, args=None, result=None, proposal=None):
        record_event(
            EVENT_TOOL_CALL,
            created_by=self.user,
            session=self.session,
            proposal=proposal,
            tool_name=tool_name,
            client_name=getattr(self.session, 'client_name', '') if self.session else '',
            llm_model=getattr(self.session, 'llm_model', '') if self.session else '',
            args=args or {},
            result=result or {},
        )

    # -- read / discovery --------------------------------------------------

    def list_collections(self):
        data = AdminCollectionSerializer(
            authorable_collections(self.user), many=True, context=_STAFF_CONTEXT,
        ).data
        self._audit('list_collections', result={'count': len(data)})
        return list(data)

    def get_collection(self, collection_id):
        collection = Collection.objects.get(pk=collection_id)
        if not collection.can_author(self.user):
            raise PermissionDenied('Collection is outside your authoring scope.')
        self._audit('get_collection', args={'collection_id': collection_id})
        return AdminCollectionSerializer(collection, context=_STAFF_CONTEXT).data

    def _scoped_geometry(self, model):
        """Towers/Zones reachable through the creator's collections."""
        collection_ids = [c.pk for c in authorable_collections(self.user)]
        related = 'collections__in'
        return model.objects.filter(**{related: collection_ids}).distinct().order_by('name')

    def list_towers(self, collection_id=None):
        qs = self._scoped_geometry(Tower)
        if collection_id is not None:
            qs = qs.filter(collections__id=collection_id)
        rows = [
            {
                'id': t.id, 'name': t.name, 'category': t.category,
                'is_active': t.is_active,
                'location': {'lng': t.location.x, 'lat': t.location.y} if t.location else None,
                'collections': list(t.collections.values_list('id', flat=True)),
            }
            for t in qs
        ]
        self._audit('list_towers', result={'count': len(rows)})
        return rows

    def list_zones(self, collection_id=None):
        qs = self._scoped_geometry(Zone)
        if collection_id is not None:
            qs = qs.filter(collections__id=collection_id)
        rows = [
            {
                'id': z.id, 'name': z.name, 'color': z.color,
                'scoring_type': z.scoring_type,
                'collections': list(z.collections.values_list('id', flat=True)),
            }
            for z in qs
        ]
        self._audit('list_zones', result={'count': len(rows)})
        return rows

    def list_challenges(self, game_id=None):
        games = {g.id for g in authorable_games(self.user)}
        qs = Challenge.objects.filter(game_id__in=games).order_by('id')
        if game_id is not None:
            if game_id not in games:
                raise PermissionDenied('Game is outside your authoring scope.')
            qs = qs.filter(game_id=game_id)
        data = AdminChallengeSerializer(qs, many=True, context=_STAFF_CONTEXT).data
        self._audit('list_challenges', result={'count': len(data)})
        return list(data)

    def list_games(self):
        data = AdminGameSerializer(
            authorable_games(self.user), many=True, context=_STAFF_CONTEXT,
        ).data
        self._audit('list_games', result={'count': len(data)})
        return list(data)

    def get_game(self, game_id):
        game = Game.objects.get(pk=game_id)
        if not game.can_edit(self.user):
            raise PermissionDenied('Game is outside your authoring scope.')
        self._audit('get_game', args={'game_id': game_id})
        return AdminGameSerializer(game, context=_STAFF_CONTEXT).data

    def list_team_groups(self, game_id):
        game = Game.objects.get(pk=game_id)
        if not game.can_edit(self.user):
            raise PermissionDenied('Game is outside your authoring scope.')
        data = AdminTeamGroupSerializer(
            TeamGroup.objects.filter(game=game).order_by('name'),
            many=True, context=_STAFF_CONTEXT,
        ).data
        self._audit('list_team_groups', args={'game_id': game_id}, result={'count': len(data)})
        return list(data)

    def list_game_roles(self, game_id):
        game = Game.objects.get(pk=game_id)
        if not game.can_edit(self.user):
            raise PermissionDenied('Game is outside your authoring scope.')
        data = AdminGameRoleSerializer(
            GameRole.objects.filter(game=game).order_by('name'),
            many=True, context=_STAFF_CONTEXT,
        ).data
        self._audit('list_game_roles', args={'game_id': game_id}, result={'count': len(data)})
        return list(data)

    def describe_config_schema(self):
        self._audit('describe_config_schema')
        return describe_config_schema()

    # -- proposal management ----------------------------------------------

    def _require_session(self):
        if self.session is None:
            raise PermissionDenied('No authoring session bound to these tools.')

    def open_proposal(self, summary='', atomic=True):
        self._require_session()
        proposal = AuthoringProposal.objects.create(
            session=self.session,
            created_by=self.user,
            summary=summary,
            atomic=atomic,
        )
        self._audit('open_proposal', args={'summary': summary}, proposal=proposal)
        return self._proposal_summary(proposal)

    def _current_proposal(self):
        """The creator's open (DRAFT) proposal for this session, or a new one."""
        self._require_session()
        proposal = (
            AuthoringProposal.objects
            .filter(session=self.session, created_by=self.user, status=PROPOSAL_DRAFT)
            .order_by('-created_at')
            .first()
        )
        if proposal is None:
            proposal = AuthoringProposal.objects.create(
                session=self.session, created_by=self.user,
            )
        return proposal

    def get_proposal(self, proposal_id):
        proposal = self._get_own_proposal(proposal_id)
        return self._proposal_detail(proposal)

    def list_my_proposals(self):
        proposals = AuthoringProposal.objects.filter(created_by=self.user).order_by('-created_at')
        return [self._proposal_summary(p) for p in proposals]

    def _get_own_proposal(self, proposal_id):
        proposal = AuthoringProposal.objects.get(pk=proposal_id)
        if proposal.created_by_id != self.user.id:
            raise PermissionDenied('Proposal belongs to a different creator.')
        return proposal

    def withdraw_proposal(self, proposal_id):
        from .models import PROPOSAL_WITHDRAWN
        proposal = self._get_own_proposal(proposal_id)
        proposal.status = PROPOSAL_WITHDRAWN
        proposal.save(update_fields=['status', 'updated_at'])
        self._audit('withdraw_proposal', proposal=proposal)
        return self._proposal_summary(proposal)

    def submit_for_approval(self, proposal_id=None):
        proposal = (
            self._get_own_proposal(proposal_id) if proposal_id is not None
            else self._current_proposal()
        )
        if not proposal.operations.exists():
            raise ValueError('Cannot submit a proposal with no staged operations.')
        proposal.status = PROPOSAL_PENDING
        proposal.save(update_fields=['status', 'updated_at'])
        self._audit('submit_for_approval', proposal=proposal)
        return self._proposal_summary(proposal)

    # -- suggest / stage write tools --------------------------------------

    def _stage(self, entity_type, action, payload, rationale='', temp_ref='', target_ref=''):
        proposal = self._current_proposal()
        if not proposal.is_open:
            raise ValueError('The open proposal is no longer accepting operations.')
        # Scope gate: an operation whose target is an EXISTING object must
        # be inside the creator's scope right now (temp refs are checked
        # at apply time — their defining CREATE carries the authorization).
        target = self._resolve_existing_target(entity_type, action, target_ref, payload)
        try:
            authorize_operation(
                self.user,
                _StubOp(entity_type, action, target_ref, payload),
                target=target, payload=payload,
            )
        except PermissionDenied:
            self._audit(
                'stage_operation_denied',
                args={'entity_type': entity_type, 'action': action, 'target_ref': target_ref},
                proposal=proposal,
            )
            raise
        order = proposal.operations.count()
        op = ProposedOperation.objects.create(
            proposal=proposal,
            entity_type=entity_type,
            action=action,
            temp_ref=temp_ref,
            target_ref=str(target_ref or ''),
            payload=payload,
            rationale=rationale,
            order=order,
        )
        self._audit(
            'stage_operation',
            args={'entity_type': entity_type, 'action': action, 'temp_ref': temp_ref},
            proposal=proposal,
        )
        return self._op_summary(op)

    def _resolve_existing_target(self, entity_type, action, target_ref, payload):
        """Load an existing-PK target for the stage-time scope check.

        Temp-ref targets and CONFIG (whose target lives in the payload)
        return None here; their scope is enforced at apply time.
        """
        if entity_type == ENTITY_CONFIG:
            return None
        ref = str(target_ref or '')
        if not ref or ref.startswith(TEMP_REF_PREFIX):
            # CREATE of a challenge/role under an EXISTING game still needs
            # a scope check, handled by authorize_operation via payload.
            return None
        from .engine import _MODELS
        model = _MODELS.get(entity_type)
        return model.objects.get(pk=int(ref)) if model else None

    def propose_collection(self, name, description='', temp_ref='', rationale=''):
        payload = {'name': name, 'description': description}
        return self._stage(ENTITY_COLLECTION, ACTION_CREATE, payload, rationale, temp_ref)

    def propose_tower(self, name, lat, lng, category=1, is_active=True,
                      temp_ref='', rationale='', **extra):
        payload = {
            'name': name, 'lat': lat, 'lng': lng,
            'category': category, 'is_active': is_active, **extra,
        }
        return self._stage(ENTITY_TOWER, ACTION_CREATE, payload, rationale, temp_ref)

    def propose_zone(self, name, vertices, temp_ref='', rationale='', **extra):
        payload = {'name': name, 'vertices': vertices, **extra}
        return self._stage(ENTITY_ZONE, ACTION_CREATE, payload, rationale, temp_ref)

    def propose_game(self, name, temp_ref='', rationale='', **extra):
        payload = {'name': name, **extra}
        return self._stage(ENTITY_GAME, ACTION_CREATE, payload, rationale, temp_ref)

    def propose_game_role(self, game_ref, name, temp_ref='', rationale='', **extra):
        payload = {'game': game_ref, 'name': name, **extra}
        return self._stage(ENTITY_GAME_ROLE, ACTION_CREATE, payload, rationale, temp_ref)

    def propose_config(self, target_id, fields, scope='game', rationale=''):
        payload = {'scope': scope, 'id': target_id, 'fields': fields}
        return self._stage(ENTITY_CONFIG, ACTION_UPDATE, payload, rationale)

    def propose_link(self, collection_ref, towers=None, zones=None, rationale=''):
        payload = {'towers': towers or [], 'zones': zones or []}
        return self._stage(
            ENTITY_COLLECTION, ACTION_LINK, payload, rationale,
            target_ref=collection_ref,
        )

    def suggest_challenge(self, game_ref, text, difficulty, rationale, tower_ref=None, **extra):
        if not rationale:
            raise ValueError('suggest_challenge requires a rationale.')
        payload = {'game': game_ref, 'text': text, 'difficulty': difficulty, **extra}
        if tower_ref is not None:
            payload['tower'] = tower_ref
        return self._stage(ENTITY_CHALLENGE, ACTION_CREATE, payload, rationale)

    def suggest_challenges(self, suggestions):
        """Batch several challenge suggestions in one call."""
        return [self.suggest_challenge(**s) for s in suggestions]

    # -- serialization -----------------------------------------------------

    def _op_summary(self, op):
        return {
            'id': op.id, 'entity_type': op.entity_type, 'action': op.action,
            'temp_ref': op.temp_ref, 'target_ref': op.target_ref,
            'rationale': op.rationale, 'status': op.status, 'order': op.order,
        }

    def _proposal_summary(self, proposal):
        return {
            'id': proposal.id, 'status': proposal.status, 'atomic': proposal.atomic,
            'summary': proposal.summary, 'operation_count': proposal.operations.count(),
        }

    def _proposal_detail(self, proposal):
        data = self._proposal_summary(proposal)
        data['operations'] = [
            {**self._op_summary(op), 'payload': op.payload}
            for op in proposal.operations.all()
        ]
        return data


class _StubOp:
    """Minimal duck-typed operation for the stage-time scope check."""

    def __init__(self, entity_type, action, target_ref, payload):
        self.entity_type = entity_type
        self.action = action
        self.target_ref = str(target_ref or '')
        self.payload = payload
