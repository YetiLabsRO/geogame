from django.contrib import admin

from organize.models import (
    Game,
    GameRole,
    Invite,
    Session,
    TeamJoinRequest,
    TeamMembership,
    TeamRole,
    UserProfile,
)


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'slug', 'is_active', 'proximity_meters', 'cooloff_minutes',
        'allow_player_team_creation', 'team_join_confirmation',
    )
    list_filter = ('is_active', 'allow_player_team_creation')
    search_fields = ('name', 'slug')


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('name', 'game', 'slug', 'state', 'is_active', 'start_time', 'scheduled_start', 'end_time')
    list_filter = ('state', 'game')
    search_fields = ('name', 'slug', 'game__name')
    autocomplete_fields = ('game', 'created_by')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_session', 'created_at')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name')
    list_filter = ('current_session',)
    autocomplete_fields = ('user', 'current_session')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(GameRole)
class GameRoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'game', 'slug', 'builtin_power', 'created_at')
    list_filter = ('game', 'builtin_power')
    search_fields = ('name', 'slug', 'game__name')
    readonly_fields = ('created_at',)


class TeamRoleInline(admin.TabularInline):
    model = TeamRole
    extra = 0
    autocomplete_fields = ('role', 'assigned_by')
    readonly_fields = ('assigned_at',)


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ('team', 'user', 'is_active', 'joined_at', 'left_at')
    list_filter = ('is_active', 'team')
    search_fields = ('team__name', 'user__user__username', 'user__user__email')
    autocomplete_fields = ('team', 'user')
    readonly_fields = ('joined_at',)
    inlines = (TeamRoleInline,)


@admin.register(TeamRole)
class TeamRoleAdmin(admin.ModelAdmin):
    list_display = ('membership', 'role', 'assigned_by', 'assigned_at')
    list_filter = ('role__game', 'role')
    search_fields = ('membership__team__name', 'membership__user__user__username', 'role__slug')
    autocomplete_fields = ('membership', 'role', 'assigned_by')
    readonly_fields = ('assigned_at',)


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = (
        'team', 'email', 'kind', 'created_by', 'created_at', 'expires_at',
        'accepted_by', 'revoked',
    )
    list_filter = ('revoked', 'kind', 'team')
    search_fields = ('email', 'team__name', 'token')
    autocomplete_fields = ('team', 'created_by', 'accepted_by')
    readonly_fields = ('token', 'created_at', 'accepted_at')


@admin.register(TeamJoinRequest)
class TeamJoinRequestAdmin(admin.ModelAdmin):
    list_display = (
        'team', 'user', 'status', 'source', 'requested_at',
        'decided_by', 'decided_at',
    )
    list_filter = ('status', 'source', 'team')
    search_fields = ('team__name', 'user__user__username', 'user__user__email')
    autocomplete_fields = ('team', 'user', 'decided_by')
    readonly_fields = ('requested_at',)
