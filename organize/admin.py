from django.contrib import admin

from organize.models import Game, Invite, Session, TeamMembership, UserProfile


@admin.register(Game)
class GameAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'proximity_meters', 'cooloff_minutes')
    list_filter = ('is_active',)
    search_fields = ('name', 'slug')


@admin.register(Session)
class SessionAdmin(admin.ModelAdmin):
    list_display = ('name', 'game', 'slug', 'is_active', 'start_time', 'end_time')
    list_filter = ('is_active', 'game')
    search_fields = ('name', 'slug', 'game__name')
    autocomplete_fields = ('game', 'created_by')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'current_session', 'created_at')
    search_fields = ('user__username', 'user__email', 'user__first_name', 'user__last_name')
    list_filter = ('current_session',)
    autocomplete_fields = ('user', 'current_session')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(TeamMembership)
class TeamMembershipAdmin(admin.ModelAdmin):
    list_display = ('team', 'user', 'is_active', 'joined_at', 'left_at')
    list_filter = ('is_active', 'team')
    search_fields = ('team__name', 'user__user__username', 'user__user__email')
    autocomplete_fields = ('team', 'user')
    readonly_fields = ('joined_at',)


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ('team', 'email', 'created_by', 'created_at', 'expires_at', 'accepted_by', 'revoked')
    list_filter = ('revoked', 'team')
    search_fields = ('email', 'team__name', 'token')
    autocomplete_fields = ('team', 'created_by', 'accepted_by')
    readonly_fields = ('token', 'created_at', 'accepted_at')
