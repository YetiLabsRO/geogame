from django.contrib import admin, messages
from django.urls import reverse
from django.conf import settings
from leaflet.admin import LeafletGeoAdmin

# Register your models here.
from django.utils.safestring import mark_safe

from geogame.models import Zone, Tower, Team, Challenge, TeamTowerChallenge, TeamTowerOwnership


class ZoneAdmin(LeafletGeoAdmin):
    list_display = ['__str__', 'scoring_type', 'color', 'get_zone_control']

    def get_zone_control(self, instance):
        output = "<ul>"
        for option, title in Team.CATEGORY_CHOICES:
            zone_control_teams = instance.zone_control(option)
            zone_control_teams = Team.objects.filter(pk__in=zone_control_teams)
            output += "<li>{}: {}</li>\n".format(title, ",".join([t.__str__() for t in zone_control_teams]))

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
        for option, title in Team.CATEGORY_CHOICES:
            try:
                t = TeamTowerOwnership.objects.get(tower=instance, timestamp_end__isnull=True, team__category=option).team
            except TeamTowerOwnership.DoesNotExist:
                t = "NOT CONTROLLED"
            output += "<li>{}: {}</li>\n".format(title, t)
        output += "</ul>"

        return mark_safe(output)

    get_tower_control.allow_tags = True
    get_tower_control.short_description = "Controlled by"

    def get_rfid_url(self, obj):
        if obj.category == Tower.CATEGORY_RFID:
            return settings.BASE_URL + reverse('tower-rfid', kwargs={"rfid_code": obj.rfid_code})
        return "-"

    get_rfid_url.short_description = "RFID URL"


class TeamAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'category', 'score', 'floating_score', 'description']
    list_filter = ['category']
    readonly_fields = ["score", ]


class ChallengeAdmin(admin.ModelAdmin):
    list_display = ['__str__', 'tower', 'difficulty', 'incercari_total', 'incercari_reusite']
    list_filter = ['tower', ]

    def incercari_total(self, obj):
        return TeamTowerChallenge.objects.filter(challenge=obj).count()

    def incercari_reusite(self, obj):
        return TeamTowerChallenge.objects.filter(challenge=obj, outcome=TeamTowerChallenge.CONFIRMED).count()


class TeamTowerChallangeAdmin(admin.ModelAdmin):
    list_filter = ['checked_by', 'outcome', 'team']
    list_display = ['id', 'team', 'tower', 'challenge_text', 'checked_by', 'timestamp_submitted', 'timestamp_verified', 'time_diff', 'outcome']
    readonly_fields = ['response_text', 'photo', 'timestamp_verified', 'team', 'challenge', 'tower']

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

admin.site.register(Zone, ZoneAdmin)
admin.site.register(Tower, TowerAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Challenge, ChallengeAdmin)
admin.site.register(TeamTowerChallenge, TeamTowerChallangeAdmin)
admin.site.register(TeamTowerOwnership, TeamTowerOwnershipAdmin)
