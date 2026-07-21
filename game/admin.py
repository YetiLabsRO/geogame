from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction

# Register your models here.
from django.utils.safestring import mark_safe
from leaflet.admin import LeafletGeoAdmin

from game.models import (
    Challenge,
    Collection,
    LocationConsent,
    LocationPing,
    PauseWindow,
    PresenceCheck,
    PresenceRequirement,
    TeamTowerChallenge,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    Tower,
    Zone,
)
from organize.models import Team, TeamGroup


class ZoneAdmin(LeafletGeoAdmin):
    list_display = [
        '__str__', 'scoring_type', 'color', 'conquest_rule',
        'get_member_towers', 'get_zone_control',
    ]

    def get_member_towers(self, instance: Zone):
        """Member towers via the many-to-many (tower-zone-topology)."""
        names = list(instance.towers.values_list('name', flat=True))
        if not names:
            return 'NO TOWERS (invalid)'
        return f'{len(names)}: {", ".join(names)}'

    get_member_towers.short_description = 'Member towers'

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


class TowerAdminForm(forms.ModelForm):
    """Form-level at-least-one-tower guard (tower-zone-topology).

    Rejecting the removal in `clean_zones` surfaces a friendly field
    error instead of letting the model-layer m2m guard blow up inside
    the admin's atomic save.
    """

    class Meta:
        model = Tower
        fields = '__all__'

    def clean_zones(self):
        zones = self.cleaned_data.get('zones') or []
        if self.instance.pk:
            kept = {z.pk for z in zones}
            removed = self.instance.zones.exclude(pk__in=kept)
            blocked = [
                z.name for z in removed
                if set(z.towers.values_list('pk', flat=True)) == {self.instance.pk}
            ]
            if blocked:
                raise forms.ValidationError(
                    'A zone must retain at least one member tower. '
                    f'This tower is the last member of: {", ".join(blocked)}.',
                )
        return zones


class TowerAdmin(LeafletGeoAdmin):
    form = TowerAdminForm
    list_display = [
        '__str__', 'is_active', 'get_zones', 'category', 'get_tower_control', 'get_rfid_url', 'id',
        'initial_bonus', 'decrease_initial_bonus'
    ]
    # `zones` is the many-to-many membership (tower-zone-topology): the
    # list filters by member zone and the edit form uses a multi-select.
    list_filter = ['zones', 'is_active', 'category']
    filter_horizontal = ['zones']
    # readonly_fields = ['rfid_code']
    actions = [unassign_all, ]

    def get_zones(self, instance):
        return ', '.join(instance.zones.values_list('name', flat=True)) or '-'

    get_zones.short_description = 'Zones'

    def save_related(self, request, form, formsets, change):
        """Re-run the autocreate-circle-zone hook after the form's M2M save.

        The admin persists many-to-many selections *after* model.save(),
        and `form.save_m2m()` resets the membership to the form's
        selection — so the autocreate hook must be (re)applied here for
        a tower saved with `autocreate_zone` and no zones selected.
        """
        super().save_related(request, form, formsets, change)
        form.instance.ensure_autocreated_zone()

    def delete_model(self, request, obj):
        # The savepoint keeps the admin's wrapping transaction usable
        # when the last-member guard rejects the delete.
        try:
            with transaction.atomic():
                super().delete_model(request, obj)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))

    def delete_queryset(self, request, queryset):
        try:
            with transaction.atomic():
                super().delete_queryset(request, queryset)
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))

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


class LocationPingAdmin(LeafletGeoAdmin):
    list_display = ('user', 'session', 'team', 'accuracy', 'recorded_at', 'received_at')
    list_filter = ('session', 'team')
    readonly_fields = ('received_at',)


class LocationConsentAdmin(admin.ModelAdmin):
    list_display = ('user', 'session', 'agreed_at', 'withdrawn_at')
    list_filter = ('session',)
    readonly_fields = ('consent_text', 'consent_text_hash')


class PresenceRequirementAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'min_members_present', 'method',
        'geofence_radius_meters', 'window_seconds',
    )
    list_filter = ('method',)


class PresenceCheckAdmin(admin.ModelAdmin):
    list_display = (
        'team_tower_challenge', 'required_count', 'present_count',
        'method', 'window_satisfied', 'satisfied', 'reason_code', 'created_at',
    )
    list_filter = ('method', 'satisfied')
    readonly_fields = ('created_at',)


admin.site.register(LocationPing, LocationPingAdmin)
admin.site.register(LocationConsent, LocationConsentAdmin)
admin.site.register(PresenceRequirement, PresenceRequirementAdmin)
admin.site.register(PresenceCheck, PresenceCheckAdmin)
admin.site.register(Collection, CollectionAdmin)
admin.site.register(Zone, ZoneAdmin)
admin.site.register(Tower, TowerAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Challenge, ChallengeAdmin)
admin.site.register(TeamTowerChallenge, TeamTowerChallangeAdmin)
admin.site.register(TeamTowerOwnership, TeamTowerOwnershipAdmin)
admin.site.register(PauseWindow, PauseWindowAdmin)
admin.site.register(TeamTowerFailCounter, TeamTowerFailCounterAdmin)
