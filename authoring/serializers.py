"""DRF serializers for the staff "AI authoring review" surface."""
from rest_framework import serializers

from .models import (
    AuthoringAuditEvent,
    AuthoringProposal,
    McpCredential,
    ProposedOperation,
)


class ProposedOperationSerializer(serializers.ModelSerializer):
    current = serializers.SerializerMethodField()

    class Meta:
        model = ProposedOperation
        fields = (
            'id', 'entity_type', 'action', 'temp_ref', 'target_ref',
            'payload', 'rationale', 'status', 'order',
            'applied_object_type', 'applied_object_id', 'error', 'current',
        )

    def get_current(self, op):
        """A shallow snapshot of the existing target for UPDATE diffs."""
        if op.action == 'CREATE' or not op.target_ref or op.target_ref.startswith('@new:'):
            return None
        try:
            from .engine import _MODELS
            model = _MODELS.get(op.entity_type)
            if model is None:
                return None
            obj = model.objects.filter(pk=int(op.target_ref)).first()
        except (ValueError, TypeError):
            return None
        if obj is None:
            return None
        return {key: str(getattr(obj, key, None)) for key in op.payload.keys()}


class AuthoringProposalListSerializer(serializers.ModelSerializer):
    operation_count = serializers.IntegerField(source='operations.count', read_only=True)
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True, default=None,
    )
    client_name = serializers.CharField(source='session.client_name', read_only=True, default='')
    llm_model = serializers.CharField(source='session.llm_model', read_only=True, default='')

    class Meta:
        model = AuthoringProposal
        fields = (
            'id', 'status', 'atomic', 'summary', 'created_by', 'created_by_username',
            'client_name', 'llm_model', 'created_at', 'updated_at',
            'decided_by', 'decided_at', 'operation_count',
        )


class AuthoringProposalDetailSerializer(AuthoringProposalListSerializer):
    operations = ProposedOperationSerializer(many=True, read_only=True)

    class Meta(AuthoringProposalListSerializer.Meta):
        fields = AuthoringProposalListSerializer.Meta.fields + ('operations',)


class AuthoringAuditEventSerializer(serializers.ModelSerializer):
    created_by_username = serializers.CharField(
        source='created_by.username', read_only=True, default=None,
    )

    class Meta:
        model = AuthoringAuditEvent
        fields = (
            'id', 'event_type', 'tool_name', 'client_name', 'llm_model',
            'created_by', 'created_by_username', 'session', 'proposal',
            'args', 'result', 'created_at',
        )


class McpCredentialSerializer(serializers.ModelSerializer):
    class Meta:
        model = McpCredential
        fields = (
            'id', 'label', 'is_active', 'created_at', 'last_used_at', 'revoked_at',
        )
