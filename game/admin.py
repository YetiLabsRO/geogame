from django.conf import settings
from django.contrib import admin, messages

# Register your models here.
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from leaflet.admin import LeafletGeoAdmin

from game.challenge_types import SCAN_TYPES, TYPE_NFC_QR
from game.models import (
    Challenge,
    Collection,
    PauseWindow,
    TeamTowerChallenge,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    TeamTrailProgress,
    TeamTrailRoute,
    Tower,
    Trail,
    TrailEdge,
    TrailStep,
    Zone,
)
from organize.models import Team, TeamGroup


class ZoneAdmin(LeafletGeoAdmin):
    list_display = ['__str__', 'scoring_type', 'color', 'get_zone_control']

    def get_zone_control(self, instance: Zone):
        output = "<ul>"
        for group in TeamGroup.objects.filter(game__collections__zones=instance).distinct():
            zone_control_teams = instance.zone_control(group.id)
            zone_control_teams = Team.objects.filter(pk__in=zone_control_teams)
            output += "<li>{}: {}</li>\n".format(group.name, ",".join([t.__str__() for t in zone_control_teams]))

        output += "</ul>"

        return mark_safe(output)

    get_zone_control.allow_tags = True
    get_zone_control.short_description = "Controlled by"


def unassign_all(modeladmin, request, queryset):
    tower_names = []
    for tower in queryset:
        tower.unassign()
        tower_names.append(tower.name)

    messages.success(request, f"Finalizat posesii pentru turnurile {', '.join(tower_names)}")
unassign_all.short_description = "Închide toate deținerile de Zone (selectează toate turnurile pentru a închide jocul)"


class TowerAdmin(LeafletGeoAdmin):
    list_display = [
        '__str__', 'is_active', 'zone', 'category', 'get_tower_control', 'get_rfid_url', 'id',
        'initial_bonus', 'decrease_initial_bonus'
    ]
    list_filter = ['zone', 'is_active', 'category']
    # readonly_fields = ['rfid_code']
    actions = [unassign_all, ]

    def get_tower_control(self, instance):
        output = "<ul>"
        for group in TeamGroup.objects.filter(game__collections__towers=instance).distinct():
            try:
                t = TeamTowerOwnership.objects.get(tower=instance, timestamp_end__isnull=True, team__group=group).team
            except TeamTowerOwnership.DoesNotExist:
                t = "NOT CONTROLLED"
            output += "<li>{}: {}</li>\n".format(group.name, t)
        output += "</ul>"

        return mark_safe(output)

    get_tower_control.allow_tags = True
    get_tower_control.short_description = "Controlled by"

    def get_rfid_url(self, obj):
        if obj.category == Tower.CATEGORY_RFID:
            return f"{settings.BASE_URL}/tower/rfid/{obj.rfid_code}"
        return "-"

    get_rfid_url.short_description = "RFID URL"


class TeamAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'group', 'score', 'floating_score', 'description']
    list_filter = ['group', 'session', 'session__game']
    search_fields = ['name']
    readonly_fields = ["score", ]


class ChallengeAdmin(admin.ModelAdmin):
    list_display = [
        '__str__', 'type', 'tower', 'difficulty', 'get_handout_code',
        'incercari_total', 'incercari_reusite',
    ]
    list_filter = ['type', 'tower']

    # The scan-type configuration fieldset is only shown for the types
    # that use it (NFC_QR / RFID) — see get_fieldsets.
    base_fieldsets = (
        (None, {
            'fields': ('game', 'text', 'tower', 'difficulty', 'type', 'review_mode'),
        }),
        ('Role requirements', {
            'fields': (
                'role_requirement_mode', 'required_roles', 'require_holders_present',
            ),
        }),
    )
    scan_fieldset = (
        'Scan validation (NFC/QR)', {
            'description': (
                'validation_code is the code embedded in the QR/NFC handed '
                'out at the venue — print it from the list column. '
                "type_config holds per-type extras, e.g. "
                '{"venue_label": "Bar X", "single_use": true}.'
            ),
            'fields': ('validation_code', 'type_config'),
        },
    )

    def get_fieldsets(self, request, obj=None):
        # On add the type is not yet known, so offer the full form; when
        # editing, only scan types surface the scan configuration.
        if obj is None or obj.type in SCAN_TYPES:
            return self.base_fieldsets + (self.scan_fieldset,)
        return self.base_fieldsets

    def get_handout_code(self, obj):
        """Printable/handout venue code for NFC_QR challenges (task 4.3)."""
        if obj.type == TYPE_NFC_QR and obj.validation_code:
            return format_html('<code>{}</code>', obj.validation_code)
        return '-'

    get_handout_code.short_description = 'Handout code'

    def incercari_total(self, obj):
        return TeamTowerChallenge.objects.filter(challenge=obj).count()

    def incercari_reusite(self, obj):
        return TeamTowerChallenge.objects.filter(challenge=obj, outcome=TeamTowerChallenge.CONFIRMED).count()


class TeamTowerChallangeAdmin(admin.ModelAdmin):
    list_filter = ['checked_by', 'outcome', 'team']
    list_display = ['id', 'team', 'tower', 'challenge_text', 'submitted_code', 'checked_by', 'timestamp_submitted', 'timestamp_verified', 'time_diff', 'outcome']
    readonly_fields = ['response_text', 'photo', 'timestamp_verified', 'team', 'challenge', 'tower', 'submitted_code']

    def challenge_text(self, obj):
        if obj.challenge:
            text = obj.challenge.text[:200]
            if len(text) > 200:
                text += " ..."
        else:
            text = "RFID Challenge"
        return text

    def time_diff(self, obj):
        if obj.timestamp_verified:
            return (obj.timestamp_verified - obj.timestamp_submitted).seconds
        return None

    time_diff.short_description = "Diff (s)"

class TeamTowerOwnershipAdmin(admin.ModelAdmin):
    pass


class PauseWindowAdmin(admin.ModelAdmin):
    list_display = ('session', 'started_at', 'ended_at', 'restore_on_resume')
    list_filter = ('session', 'restore_on_resume')
    readonly_fields = ('tower_ownerships', 'zone_ownerships')


class TeamTowerFailCounterAdmin(admin.ModelAdmin):
    list_display = ('team', 'tower', 'consecutive_fails', 'last_failed_at', 'locked_until')
    list_filter = ('tower',)
    search_fields = ('team__name', 'tower__name')


class CollectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'tower_count', 'zone_count', 'created_by', 'created_at')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    filter_horizontal = ('towers', 'zones')
    readonly_fields = ('created_at',)

    def tower_count(self, obj):
        return obj.towers.count()

    def zone_count(self, obj):
        return obj.zones.count()


# --- mode-trail-discovery ---------------------------------------------------


class TrailStepInline(admin.TabularInline):
    model = TrailStep
    extra = 0
    fields = ('order', 'tower', 'is_start', 'is_finish', 'gate_challenge', 'clue_text', 'start_hint')


class TrailEdgeInline(admin.TabularInline):
    model = TrailEdge
    extra = 0
    fields = ('from_step', 'to_step', 'clue')


class TrailAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'game', 'structure', 'starting_knowledge', 'participation', 'step_count')
    list_filter = ('structure', 'starting_knowledge', 'participation')
    inlines = [TrailStepInline, TrailEdgeInline]

    def step_count(self, obj):
        return obj.steps.count()


class TeamTrailRouteAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'session', 'start_step', 'finished_at')
    list_filter = ('session',)


class TeamTrailProgressAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'session', 'state', 'revealed_at', 'arrived_at', 'unlocked_at')
    list_filter = ('session', 'state')


admin.site.register(Trail, TrailAdmin)
admin.site.register(TeamTrailRoute, TeamTrailRouteAdmin)
admin.site.register(TeamTrailProgress, TeamTrailProgressAdmin)
admin.site.register(Collection, CollectionAdmin)
admin.site.register(Zone, ZoneAdmin)
admin.site.register(Tower, TowerAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Challenge, ChallengeAdmin)
admin.site.register(TeamTowerChallenge, TeamTowerChallangeAdmin)
admin.site.register(TeamTowerOwnership, TeamTowerOwnershipAdmin)
admin.site.register(PauseWindow, PauseWindowAdmin)
admin.site.register(TeamTowerFailCounter, TeamTowerFailCounterAdmin)
