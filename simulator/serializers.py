from rest_framework import serializers

from simulator.models import SimulatedPlayer, SimulationEvent, SimulationRun


class SimulationRunSerializer(serializers.ModelSerializer):
    class Meta:
        model = SimulationRun
        fields = (
            'id', 'name', 'created_by', 'game', 'session',
            'status', 'seed', 'config', 'tick_count', 'created_at',
        )
        read_only_fields = (
            'id', 'created_by', 'game', 'session', 'status', 'tick_count', 'created_at',
        )


class SimulatedPlayerSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='profile.user.username', read_only=True)

    class Meta:
        model = SimulatedPlayer
        fields = ('id', 'run', 'profile', 'username', 'team', 'role', 'lat', 'lng', 'state')


class SimulationEventSerializer(serializers.ModelSerializer):
    actor_username = serializers.SerializerMethodField()

    class Meta:
        model = SimulationEvent
        fields = ('id', 'tick', 'ts', 'actor', 'actor_username', 'action', 'payload', 'outcome')

    def get_actor_username(self, event):
        return event.actor.username if event.actor_id else None
