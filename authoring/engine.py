"""Temp-ref resolution, dependency ordering, and the apply engine.

The apply path re-authorizes every operation as the creator (never the
LLM), validates each payload through the SAME staff serializer the
staff API uses (parity), and writes real records in dependency order.
Nothing here is reachable without a prior human approval decision.
"""
from collections import deque

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from game.admin_api import (
    AdminChallengeSerializer,
    AdminCollectionSerializer,
    AdminGameRoleSerializer,
    AdminGameSerializer,
    AdminTowerSerializer,
    AdminZoneSerializer,
)
from game.models import Challenge, Collection, Tower, Zone
from organize.models import (
    OVERRIDABLE_CONFIG_FIELDS,
    Game,
    GameRole,
    Session,
)

from .models import (
    ACTION_CREATE,
    ACTION_LINK,
    ACTION_UNLINK,
    ENTITY_CHALLENGE,
    ENTITY_COLLECTION,
    ENTITY_CONFIG,
    ENTITY_GAME,
    ENTITY_GAME_ROLE,
    ENTITY_TOWER,
    ENTITY_ZONE,
    EVENT_APPLY,
    EVENT_STATE_CHANGE,
    OP_APPLIED,
    OP_APPROVED,
    OP_FAILED,
    PROPOSAL_APPLIED,
    PROPOSAL_FAILED,
    PROPOSAL_PARTIALLY_APPLIED,
    TEMP_REF_PREFIX,
    record_event,
)


class RefError(ValueError):
    """A staged operation references a temp ref that is cyclic/undefined."""


class _AtomicApplyFailed(Exception):
    def __init__(self, operation, error):
        self.operation = operation
        self.error = error


# --- temp-ref helpers ------------------------------------------------------

def _iter_temp_names(value):
    """Yield every `@new:<name>` reference inside a payload value."""
    if isinstance(value, str):
        if value.startswith(TEMP_REF_PREFIX):
            yield value[len(TEMP_REF_PREFIX):]
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_temp_names(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_temp_names(item)


def _substitute(value, tempmap):
    """Replace `@new:` refs in a payload value with resolved PKs."""
    if isinstance(value, str) and value.startswith(TEMP_REF_PREFIX):
        name = value[len(TEMP_REF_PREFIX):]
        if name not in tempmap:
            raise RefError(f'Unresolved temp ref @new:{name}')
        return tempmap[name]
    if isinstance(value, dict):
        return {key: _substitute(item, tempmap) for key, item in value.items()}
    if isinstance(value, list):
        return [_substitute(item, tempmap) for item in value]
    return value


def _op_dep_names(op):
    """Temp names an operation depends on (payload + a `@new:` target)."""
    names = set(_iter_temp_names(op.payload))
    if op.target_ref.startswith(TEMP_REF_PREFIX):
        names.add(op.target_ref[len(TEMP_REF_PREFIX):])
    return names


def topological_order(operations):
    """Order operations so every temp ref is defined before it is used.

    Raises `RefError` on a duplicate temp ref, an undefined ref, or a
    cycle — before any write happens.
    """
    ops = list(operations)
    by_temp = {}
    for op in ops:
        if op.temp_ref:
            if op.temp_ref in by_temp:
                raise RefError(f'Duplicate temp ref @new:{op.temp_ref}')
            by_temp[op.temp_ref] = op

    indeg = {op.id: 0 for op in ops}
    adj = {op.id: [] for op in ops}
    for op in ops:
        for name in _op_dep_names(op):
            dep = by_temp.get(name)
            if dep is None:
                raise RefError(f'Unresolved temp ref @new:{name}')
            if dep.id == op.id:
                raise RefError(f'Self-referential temp ref @new:{name}')
            adj[dep.id].append(op.id)
            indeg[op.id] += 1

    id_to_op = {op.id: op for op in ops}
    ready = deque(
        sorted(
            (op.id for op in ops if indeg[op.id] == 0),
            key=lambda oid: (id_to_op[oid].order, oid),
        )
    )
    ordered = []
    while ready:
        oid = ready.popleft()
        ordered.append(id_to_op[oid])
        newly = []
        for nxt in adj[oid]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                newly.append(nxt)
        for nid in sorted(newly, key=lambda x: (id_to_op[x].order, x)):
            ready.append(nid)
    if len(ordered) != len(ops):
        raise RefError('Cyclic temp-ref dependency among staged operations.')
    return ordered


# --- authorization ---------------------------------------------------------

def _game_from_payload(payload):
    """Resolve an already-substituted game reference to a Game, or None."""
    ref = payload.get('game')
    if isinstance(ref, int):
        return Game.objects.filter(pk=ref).first()
    if isinstance(ref, str) and ref.isdigit():
        return Game.objects.filter(pk=int(ref)).first()
    return None  # still a temp ref → parent CREATE carries authorization


def authorize_operation(user, op, *, target=None, payload=None):
    """Raise `PermissionDenied` when `op` falls outside `user`'s scope.

    Used both at stage time (real-PK targets only; temp refs skipped) and
    at apply time (everything resolved). A temp-ref parent means the
    parent CREATE op already carried the scope check.
    """
    payload = payload if payload is not None else op.payload
    entity, action = op.entity_type, op.action
    staff = bool(getattr(user, 'is_staff', False))

    if not staff:
        raise PermissionDenied('Authoring requires a staff account.')

    if entity == ENTITY_COLLECTION:
        if action == ACTION_CREATE:
            return
        if action in (ACTION_LINK, ACTION_UNLINK):
            if target is not None and not target.can_author(user):
                raise PermissionDenied('Not authorised to author this collection.')
            return
        if target is not None and not target.can_author(user):
            raise PermissionDenied('Not authorised to edit this collection.')
        return

    if entity in (ENTITY_TOWER, ENTITY_ZONE):
        if action == ACTION_CREATE:
            return  # repository geometry; collection filing gated on LINK
        if target is not None:
            for collection in target.collections.all():
                if not collection.can_author(user):
                    raise PermissionDenied(
                        'Not authorised to edit geometry shared by this collection.',
                    )
        return

    if entity == ENTITY_CHALLENGE:
        game = target.game if target is not None else _game_from_payload(payload)
        if game is not None and not game.can_edit(user):
            raise PermissionDenied('Not authorised to author this game\'s challenges.')
        return

    if entity == ENTITY_GAME_ROLE:
        game = target.game if target is not None else _game_from_payload(payload)
        if game is not None and not game.can_edit(user):
            raise PermissionDenied('Not authorised to author this game\'s roles.')
        return

    if entity == ENTITY_GAME:
        if action == ACTION_CREATE:
            return
        if target is not None and not target.can_edit(user):
            raise PermissionDenied('Not authorised to edit this game.')
        return

    if entity == ENTITY_CONFIG:
        game = target.game if isinstance(target, Session) else target
        if isinstance(game, Game) and not game.can_edit(user):
            raise PermissionDenied('Not authorised to edit this game\'s config.')
        return

    raise PermissionDenied(f'Unknown entity type {entity}.')


# --- apply -----------------------------------------------------------------

_CREATE_SERIALIZERS = {
    ENTITY_COLLECTION: AdminCollectionSerializer,
    ENTITY_TOWER: AdminTowerSerializer,
    ENTITY_ZONE: AdminZoneSerializer,
    ENTITY_CHALLENGE: AdminChallengeSerializer,
    ENTITY_GAME_ROLE: AdminGameRoleSerializer,
    ENTITY_GAME: AdminGameSerializer,
}
_MODELS = {
    ENTITY_COLLECTION: Collection,
    ENTITY_TOWER: Tower,
    ENTITY_ZONE: Zone,
    ENTITY_CHALLENGE: Challenge,
    ENTITY_GAME_ROLE: GameRole,
    ENTITY_GAME: Game,
}
# Entities whose row records its author.
_CREATED_BY = {ENTITY_COLLECTION, ENTITY_GAME}


def _resolve_target(op, tempmap):
    """Resolve `target_ref` to an existing model instance (or None)."""
    ref = op.target_ref
    if not ref:
        return None
    if ref.startswith(TEMP_REF_PREFIX):
        name = ref[len(TEMP_REF_PREFIX):]
        if name not in tempmap:
            raise RefError(f'Unresolved temp ref @new:{name}')
        ref = tempmap[name]
    model = _MODELS.get(op.entity_type)
    if op.entity_type == ENTITY_CONFIG:
        # CONFIG target is a Game or Session, tagged in the payload.
        return None
    if model is None:
        return None
    return model.objects.get(pk=int(ref))


def _apply_config(op, user, payload):
    """Apply a CONFIG update to a Game or Session's overridable knobs."""
    scope = payload.get('scope', 'game')
    target_id = payload.get('id')
    fields = payload.get('fields', {})
    if scope == 'session':
        obj = Session.objects.get(pk=int(target_id))
    else:
        obj = Game.objects.get(pk=int(target_id))
    authorize_operation(user, op, target=obj, payload=payload)
    for key, value in fields.items():
        if key not in OVERRIDABLE_CONFIG_FIELDS:
            raise ValidationError(f'{key} is not an overridable config field.')
        setattr(obj, key, value)
    obj.full_clean(exclude=None, validate_unique=False)
    obj.save()
    return obj


def _apply_link(op, user, payload, tempmap):
    """Add/remove Tower/Zone membership on a Collection."""
    collection = _resolve_target(op, tempmap)
    if collection is None:
        raise RefError('LINK operation is missing its collection target.')
    authorize_operation(user, op, target=collection)
    towers = [int(x) for x in _substitute(payload.get('towers', []), tempmap)]
    zones = [int(x) for x in _substitute(payload.get('zones', []), tempmap)]
    if op.action == ACTION_LINK:
        if towers:
            collection.towers.add(*Tower.objects.filter(pk__in=towers))
        if zones:
            collection.zones.add(*Zone.objects.filter(pk__in=zones))
    else:  # UNLINK
        if towers:
            collection.towers.remove(*Tower.objects.filter(pk__in=towers))
        if zones:
            collection.zones.remove(*Zone.objects.filter(pk__in=zones))
    return collection


def apply_operation(op, user, tempmap):
    """Apply a single approved operation as `user`; return the object.

    Raises `PermissionDenied`/`ValidationError`/`RefError` on failure.
    The caller decides transaction boundaries and status bookkeeping.
    """
    if op.entity_type == ENTITY_CONFIG:
        payload = _substitute(op.payload, tempmap)
        return _apply_config(op, user, payload)

    if op.action in (ACTION_LINK, ACTION_UNLINK):
        return _apply_link(op, user, op.payload, tempmap)

    payload = _substitute(op.payload, tempmap)

    if op.action == ACTION_CREATE:
        serializer_cls = _CREATE_SERIALIZERS[op.entity_type]
        authorize_operation(user, op, target=None, payload=payload)
        serializer = serializer_cls(data=payload)
        serializer.is_valid(raise_exception=True)
        save_kwargs = {'created_by': user} if op.entity_type in _CREATED_BY else {}
        return serializer.save(**save_kwargs)

    # UPDATE
    target = _resolve_target(op, tempmap)
    authorize_operation(user, op, target=target, payload=payload)
    serializer_cls = _CREATE_SERIALIZERS[op.entity_type]
    serializer = serializer_cls(instance=target, data=payload, partial=True)
    serializer.is_valid(raise_exception=True)
    return serializer.save()


def _record_applied(op, obj):
    op.applied_object_type = obj._meta.label
    op.applied_object_id = obj.pk
    if op.temp_ref:
        return op.temp_ref, obj.pk
    return None


def apply_proposal(proposal, actor):
    """Apply the APPROVED operations of `proposal` as `actor`.

    Atomic proposals roll the whole set back on the first failure and
    end FAILED; non-atomic proposals apply each independently and end
    APPLIED / PARTIALLY_APPLIED / FAILED.
    """
    approved = [op for op in proposal.operations.all() if op.status == OP_APPROVED]
    ordered = topological_order(approved)
    tempmap = {}

    if proposal.atomic:
        try:
            with transaction.atomic():
                for op in ordered:
                    try:
                        obj = apply_operation(op, actor, tempmap)
                    except Exception as exc:  # noqa: BLE001 - recorded below
                        raise _AtomicApplyFailed(op, str(exc)) from exc
                    mapping = _record_applied(op, obj)
                    if mapping:
                        tempmap[mapping[0]] = mapping[1]
                    op.status = OP_APPLIED
                    op.error = ''
                    op.save(update_fields=[
                        'status', 'error', 'applied_object_type', 'applied_object_id',
                    ])
        except _AtomicApplyFailed as failure:
            failure.operation.refresh_from_db()
            failure.operation.status = OP_FAILED
            failure.operation.error = failure.error
            failure.operation.save(update_fields=['status', 'error'])
            _finish(proposal, PROPOSAL_FAILED, actor, error=failure.error)
            return proposal
        _finish(proposal, PROPOSAL_APPLIED, actor)
        return proposal

    any_ok = any_fail = False
    for op in ordered:
        try:
            with transaction.atomic():
                obj = apply_operation(op, actor, tempmap)
                mapping = _record_applied(op, obj)
                op.status = OP_APPLIED
                op.error = ''
                op.save(update_fields=[
                    'status', 'error', 'applied_object_type', 'applied_object_id',
                ])
            if mapping:
                tempmap[mapping[0]] = mapping[1]
            any_ok = True
        except Exception as exc:  # noqa: BLE001 - recorded on the op
            op.status = OP_FAILED
            op.error = str(exc)
            op.save(update_fields=['status', 'error'])
            any_fail = True
    if any_fail and any_ok:
        status = PROPOSAL_PARTIALLY_APPLIED
    elif any_fail:
        status = PROPOSAL_FAILED
    else:
        status = PROPOSAL_APPLIED
    _finish(proposal, status, actor)
    return proposal


def _finish(proposal, status, actor, error=''):
    proposal.status = status
    proposal.save(update_fields=['status', 'updated_at'])
    record_event(
        EVENT_APPLY,
        created_by=actor,
        session=proposal.session,
        proposal=proposal,
        tool_name='apply_proposal',
        result={'status': status, 'error': error},
    )
    record_event(
        EVENT_STATE_CHANGE,
        created_by=actor,
        session=proposal.session,
        proposal=proposal,
        result={'status': status},
    )
