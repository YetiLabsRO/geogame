"""Staging models for the MCP authoring server (mcp-authoring capability).

An LLM never writes live game content. It authenticates with a
creator-scoped `McpCredential`, reads the authoring surface, and stages
`ProposedOperation`s onto an `AuthoringProposal`. A human then approves,
and only then does the apply engine (see `authoring.engine`) write real
records — within the creator's own permission scope, re-checked at apply
time. Every tool call and lifecycle transition is recorded, append-only,
on `AuthoringAuditEvent`.
"""
import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

# --- Entity / action / status vocabularies ---------------------------------

ENTITY_COLLECTION = 'COLLECTION'
ENTITY_TOWER = 'TOWER'
ENTITY_ZONE = 'ZONE'
ENTITY_CHALLENGE = 'CHALLENGE'
ENTITY_GAME = 'GAME'
ENTITY_GAME_ROLE = 'GAME_ROLE'
ENTITY_CONFIG = 'CONFIG'
ENTITY_CHOICES = [
    (ENTITY_COLLECTION, 'Collection'),
    (ENTITY_TOWER, 'Tower'),
    (ENTITY_ZONE, 'Zone'),
    (ENTITY_CHALLENGE, 'Challenge'),
    (ENTITY_GAME, 'Game'),
    (ENTITY_GAME_ROLE, 'Game role'),
    (ENTITY_CONFIG, 'Config'),
]

ACTION_CREATE = 'CREATE'
ACTION_UPDATE = 'UPDATE'
ACTION_LINK = 'LINK'
ACTION_UNLINK = 'UNLINK'
ACTION_CHOICES = [
    (ACTION_CREATE, 'Create'),
    (ACTION_UPDATE, 'Update'),
    (ACTION_LINK, 'Link'),
    (ACTION_UNLINK, 'Unlink'),
]

# Proposal lifecycle: DRAFT → PENDING → (APPROVED →) APPLIED /
# PARTIALLY_APPLIED / FAILED, or REJECTED / WITHDRAWN off to the side.
PROPOSAL_DRAFT = 'DRAFT'
PROPOSAL_PENDING = 'PENDING'
PROPOSAL_APPROVED = 'APPROVED'
PROPOSAL_APPLIED = 'APPLIED'
PROPOSAL_PARTIALLY_APPLIED = 'PARTIALLY_APPLIED'
PROPOSAL_REJECTED = 'REJECTED'
PROPOSAL_WITHDRAWN = 'WITHDRAWN'
PROPOSAL_FAILED = 'FAILED'
PROPOSAL_STATUS_CHOICES = [
    (PROPOSAL_DRAFT, 'Draft — the LLM is still staging operations'),
    (PROPOSAL_PENDING, 'Pending — submitted for human approval'),
    (PROPOSAL_APPROVED, 'Approved — awaiting apply'),
    (PROPOSAL_APPLIED, 'Applied — all approved operations written'),
    (PROPOSAL_PARTIALLY_APPLIED, 'Partially applied — some operations failed'),
    (PROPOSAL_REJECTED, 'Rejected'),
    (PROPOSAL_WITHDRAWN, 'Withdrawn by the author'),
    (PROPOSAL_FAILED, 'Failed — apply rolled back'),
]
# States from which the LLM may still stage / mutate operations.
PROPOSAL_OPEN_STATES = {PROPOSAL_DRAFT}
# States from which a human may still make an approve/reject decision. A
# creator may approve their own DRAFT directly (the LLM cannot — approval
# is a staff-API action, never an MCP tool).
PROPOSAL_DECIDABLE_STATES = {PROPOSAL_DRAFT, PROPOSAL_PENDING, PROPOSAL_APPROVED}

OP_PENDING = 'PENDING'
OP_APPROVED = 'APPROVED'
OP_REJECTED = 'REJECTED'
OP_APPLIED = 'APPLIED'
OP_FAILED = 'FAILED'
OP_STATUS_CHOICES = [
    (OP_PENDING, 'Pending'),
    (OP_APPROVED, 'Approved'),
    (OP_REJECTED, 'Rejected'),
    (OP_APPLIED, 'Applied'),
    (OP_FAILED, 'Failed'),
]

# Audit event types.
EVENT_TOOL_CALL = 'TOOL_CALL'
EVENT_STATE_CHANGE = 'STATE_CHANGE'
EVENT_DECISION = 'DECISION'
EVENT_APPLY = 'APPLY'
EVENT_CHOICES = [
    (EVENT_TOOL_CALL, 'Tool call'),
    (EVENT_STATE_CHANGE, 'State change'),
    (EVENT_DECISION, 'Approval decision'),
    (EVENT_APPLY, 'Apply outcome'),
]

# A staged operation whose target is another staged operation references
# it by a client-supplied temp ref of the form `@new:<name>`.
TEMP_REF_PREFIX = '@new:'


def _hash_token(raw_token):
    """One-way hash for at-rest credential storage."""
    return hashlib.sha256(raw_token.encode('utf-8')).hexdigest()


class McpCredential(models.Model):
    """A creator-scoped bearer token that binds an MCP session to one user.

    The raw token is shown once at issue time and only its SHA-256 hash
    is stored. Every MCP tool call runs as `created_by`; the LLM can
    never act outside that user's authoring scope.
    """

    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='mcp_credentials',
    )
    label = models.CharField(max_length=120, blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        state = 'active' if self.is_active else 'revoked'
        return f'MCP credential #{self.pk} for {self.created_by} ({state})'

    @classmethod
    def issue(cls, user, label=''):
        """Create a credential; return (instance, raw_token) once."""
        raw_token = f'mcp_{secrets.token_urlsafe(32)}'
        credential = cls.objects.create(
            token_hash=_hash_token(raw_token),
            created_by=user,
            label=label,
        )
        return credential, raw_token

    @classmethod
    def verify(cls, raw_token):
        """Resolve an active credential from a raw bearer token, or None."""
        if not raw_token:
            return None
        credential = cls.objects.filter(
            token_hash=_hash_token(raw_token), is_active=True,
        ).select_related('created_by').first()
        if credential is None:
            return None
        credential.last_used_at = timezone.now()
        credential.save(update_fields=['last_used_at'])
        return credential

    def revoke(self):
        self.is_active = False
        self.revoked_at = timezone.now()
        self.save(update_fields=['is_active', 'revoked_at'])


class AuthoringSession(models.Model):
    """One LLM conversation/context, grouping proposals for the audit trail."""

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='authoring_sessions',
    )
    credential = models.ForeignKey(
        McpCredential,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sessions',
    )
    target_game = models.ForeignKey(
        'organize.Game',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authoring_sessions',
    )
    client_name = models.CharField(max_length=120, blank=True, default='')
    llm_model = models.CharField(max_length=120, blank=True, default='')
    started_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f'Authoring session #{self.pk} ({self.created_by})'


class AuthoringProposal(models.Model):
    """A staged, ordered change set awaiting human approval."""

    session = models.ForeignKey(
        AuthoringSession,
        on_delete=models.CASCADE,
        related_name='proposals',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='authoring_proposals',
    )
    status = models.CharField(
        max_length=20, choices=PROPOSAL_STATUS_CHOICES, default=PROPOSAL_DRAFT,
    )
    # When true the apply engine wraps every operation in one transaction
    # and rolls the whole proposal back on the first failure.
    atomic = models.BooleanField(default=True)
    summary = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authoring_decisions',
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'Proposal #{self.pk} ({self.status}) by {self.created_by}'

    @property
    def is_open(self):
        return self.status in PROPOSAL_OPEN_STATES


class ProposedOperation(models.Model):
    """One staged create/update/link, with a rationale and a temp ref.

    `target_ref` is either the string PK of an existing object (for
    UPDATE/LINK) or a `@new:<name>` temp ref that CREATE operations
    define and later operations resolve against.
    """

    proposal = models.ForeignKey(
        AuthoringProposal,
        on_delete=models.CASCADE,
        related_name='operations',
    )
    entity_type = models.CharField(max_length=16, choices=ENTITY_CHOICES)
    action = models.CharField(max_length=8, choices=ACTION_CHOICES)
    # The temp ref this operation defines (CREATE) — lets later ops
    # reference it before the row exists. Blank for UPDATE/LINK.
    temp_ref = models.CharField(max_length=120, blank=True, default='')
    # Existing PK (UPDATE/LINK) or a `@new:` ref to a sibling CREATE.
    target_ref = models.CharField(max_length=120, blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    rationale = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=10, choices=OP_STATUS_CHOICES, default=OP_PENDING,
    )
    applied_object_type = models.CharField(max_length=32, blank=True, default='')
    applied_object_id = models.PositiveBigIntegerField(null=True, blank=True)
    error = models.TextField(blank=True, default='')
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['proposal_id', 'order', 'id']

    def __str__(self):
        return f'{self.action} {self.entity_type} (op #{self.pk})'


class _InsertOnlyQuerySet(models.QuerySet):
    """QuerySet that refuses bulk update/delete — audit is append-only."""

    def update(self, *args, **kwargs):
        raise NotImplementedError('AuthoringAuditEvent is append-only.')

    def delete(self, *args, **kwargs):
        raise NotImplementedError('AuthoringAuditEvent is append-only.')


_InsertOnlyManager = models.Manager.from_queryset(_InsertOnlyQuerySet)


class AuthoringAuditEvent(models.Model):
    """Append-only record of every tool call and lifecycle transition."""

    session = models.ForeignKey(
        AuthoringSession,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_events',
    )
    proposal = models.ForeignKey(
        AuthoringProposal,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_events',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authoring_audit_events',
    )
    event_type = models.CharField(max_length=16, choices=EVENT_CHOICES)
    tool_name = models.CharField(max_length=80, blank=True, default='')
    # The LLM/client identity captured at call time (never trusted for
    # authz — only recorded).
    client_name = models.CharField(max_length=120, blank=True, default='')
    llm_model = models.CharField(max_length=120, blank=True, default='')
    args = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = _InsertOnlyManager()

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f'{self.event_type}:{self.tool_name or "-"} @ {self.created_at:%Y-%m-%d %H:%M}'

    def save(self, *args, **kwargs):
        # Immutable once written: block field updates, allow only insert.
        if self.pk is not None:
            raise NotImplementedError('AuthoringAuditEvent rows are immutable.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise NotImplementedError('AuthoringAuditEvent rows cannot be deleted.')


def record_event(
    event_type,
    *,
    created_by=None,
    session=None,
    proposal=None,
    tool_name='',
    client_name='',
    llm_model='',
    args=None,
    result=None,
):
    """Append one audit event. Convenience wrapper used across the app."""
    return AuthoringAuditEvent.objects.create(
        event_type=event_type,
        created_by=created_by,
        session=session,
        proposal=proposal,
        tool_name=tool_name or '',
        client_name=client_name or '',
        llm_model=llm_model or '',
        args=args or {},
        result=result or {},
    )
