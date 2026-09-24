from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.db import transaction

# Register your models here.
from django.utils.html import format_html, format_html_join
from django.utils.safestring import mark_safe
from leaflet.admin import LeafletGeoAdmin

from game.challenge_types import SCAN_TYPES, TYPE_NFC_QR
from game.models import (
    NFC_MODE_SECURE_TOKEN,
    BadgeAssignment,
    BadgeDevice,
    BadgeTelemetry,
    Challenge,
    Collection,
    DementorFlip,
    DementorState,
    GatewayNode,
    LocationConsent,
    LocationPing,
    NfcTag,
    PauseWindow,
    PresenceCheck,
    PresenceRequirement,
    ProximityEvent,
    ProximityIdentity,
    ProximityReport,
    ScoreMultiplier,
    TagScan,
    TeamTowerChallenge,
    TeamTowerFailCounter,
    TeamTowerOwnership,
    TeamTrailProgress,
    TeamTrailRoute,
    TeamZoneCoverage,
    Tower,
    TowerDiscovery,
    TowerLock,
    TowerPhoto,
    TowerType,
    Trail,
    TrailEdge,
    TrailStep,
    Zone,
)
from organize.models import Team, TeamGroup


class ZoneAdmin(LeafletGeoAdmin):
    list_display = [
        '__str__', 'scoring_type', 'color', 'conquest_rule',
        'fog_reveal_coverage_pct',
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


@admin.register(TowerType)
class TowerTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon', 'color', 'proximity_meters', 'order')
    list_editable = ('order',)
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name', 'slug')


class TowerPhotoInline(admin.TabularInline):
    model = TowerPhoto
    extra = 0
    readonly_fields = ['captured_by', 'captured_at']


class TowerAdmin(LeafletGeoAdmin):
    form = TowerAdminForm
    list_display = [
        '__str__', 'is_active', 'tower_type', 'get_zones', 'category',
        'get_tower_control', 'get_rfid_url',
        'get_capture_mode', 'get_nfc_payload', 'id',
        'initial_bonus', 'decrease_initial_bonus',
        'discoverability', 'challenge_visibility',
    ]
    # `zones` is the many-to-many membership (tower-zone-topology): the
    # list filters by member zone and the edit form uses a multi-select.
    list_filter = [
        'zones', 'is_active', 'tower_type', 'category',
        'discoverability', 'challenge_visibility',
    ]
    filter_horizontal = ['zones']
    # readonly_fields = ['rfid_code']
    actions = [unassign_all, ]
    inlines = [TowerPhotoInline]

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

    # nfc-native-and-secure-links (task 7.2): which capture mode the
    # tower uses, plus the secure payload + QR next to the legacy URL.
    def _active_tags(self, obj):
        return obj.nfc_tags.filter(is_active=True)

    def get_capture_mode(self, obj):
        modes = sorted({tag.mode for tag in self._active_tags(obj)})
        if modes:
            return ' + '.join(modes)
        return 'LEGACY_URL' if obj.category == Tower.CATEGORY_RFID else '-'

    get_capture_mode.short_description = 'Capture mode'

    def get_nfc_payload(self, obj):
        tags = [
            tag for tag in self._active_tags(obj)
            if tag.mode == NFC_MODE_SECURE_TOKEN
        ]
        if not tags:
            return '-'
        return format_html_join(
            mark_safe('<br>'),
            '<code>{}</code> (<a href="{}" target="_blank">QR</a>)',
            (
                (tag.app_link(), f'/api/staff/nfc-tags/{tag.pk}/qr/')
                for tag in tags
            ),
        )

    get_nfc_payload.short_description = 'Secure NFC payload'


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


class TowerPhotoAdmin(admin.ModelAdmin):
    list_display = ('tower', 'caption', 'captured_by', 'captured_at')
    list_filter = ('tower',)
    readonly_fields = ('captured_at',)


class NfcTagAdmin(admin.ModelAdmin):
    list_display = (
        'token', 'mode', 'tower', 'challenge', 'label', 'is_active',
        'last_counter', 'get_app_link', 'created_at',
    )
    list_filter = ('mode', 'is_active')
    search_fields = ('token', 'label', 'hidden_hint', 'tower__name')
    readonly_fields = ('token', 'last_counter', 'created_at')

    def get_app_link(self, obj):
        return format_html(
            '<a href="{0}" target="_blank">{0}</a> '
            '(<a href="/api/staff/nfc-tags/{1}/qr/" target="_blank">QR</a>)',
            obj.app_link(), obj.pk,
        )

    get_app_link.short_description = 'App link'


class TagScanAdmin(admin.ModelAdmin):
    """Read-only scan audit — one leg of the documented threat model."""

    list_display = (
        'timestamp', 'tag', 'player', 'session', 'outcome',
        'lat', 'lng', 'accuracy', 'counter',
    )
    list_filter = ('outcome', 'session')
    readonly_fields = [field.name for field in TagScan._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class TowerLockAdmin(admin.ModelAdmin):
    list_display = (
        'tower', 'team', 'group', 'started_at', 'expires_at',
        'released_at', 'release_reason',
    )
    list_filter = ('release_reason', 'group')
    search_fields = ('tower__name', 'team__name')


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


class TowerDiscoveryAdmin(admin.ModelAdmin):
    list_display = ('session', 'team', 'tower', 'method', 'discovered_by', 'discovered_at')
    list_filter = ('session', 'method', 'team')
    readonly_fields = ('discovered_at',)


class TeamZoneCoverageAdmin(admin.ModelAdmin):
    list_display = ('session', 'team', 'zone', 'coverage_pct', 'revealed', 'updated_at')
    list_filter = ('session', 'revealed')
    readonly_fields = ('updated_at',)


admin.site.register(TowerDiscovery, TowerDiscoveryAdmin)
admin.site.register(TeamZoneCoverage, TeamZoneCoverageAdmin)
admin.site.register(LocationPing, LocationPingAdmin)
admin.site.register(LocationConsent, LocationConsentAdmin)
admin.site.register(PresenceRequirement, PresenceRequirementAdmin)
admin.site.register(PresenceCheck, PresenceCheckAdmin)


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


class ScoreMultiplierAdmin(admin.ModelAdmin):
    list_display = (
        '__str__', 'game', 'session', 'scope', 'tower', 'zone',
        'multiplier_type', 'factor', 'is_active',
    )
    list_filter = ('multiplier_type', 'scope', 'is_active')
    readonly_fields = ('created_at',)


admin.site.register(ScoreMultiplier, ScoreMultiplierAdmin)
admin.site.register(Collection, CollectionAdmin)


class ProximityIdentityAdmin(admin.ModelAdmin):
    list_display = ('token', 'player', 'session', 'active', 'issued_at', 'rotates_at', 'retired_at')
    list_filter = ('session', 'active')
    search_fields = ('token', 'player__user__username')


class ProximityReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'player', 'session', 'received_at', 'observation_count')
    list_filter = ('session',)
    readonly_fields = ('observations',)

    def observation_count(self, obj):
        return len(obj.observations)


class ProximityEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'player_a', 'player_b', 'distance_bucket', 'confidence', 'corroborated', 'derived_at')
    list_filter = ('session', 'distance_bucket', 'corroborated')


class DementorStateAdmin(admin.ModelAdmin):
    list_display = ('player', 'session', 'role', 'energy', 'alive', 'last_delta', 'last_tick_at')
    list_filter = ('session', 'role', 'alive')
    search_fields = ('player__user__username',)


class DementorFlipAdmin(admin.ModelAdmin):
    list_display = ('state', 'from_role', 'to_role', 'cause', 'happened_at')
    list_filter = ('cause',)


class BadgeDeviceAdmin(admin.ModelAdmin):
    list_display = (
        'badge_id', 'status', 'battery_pct', 'firmware_version',
        'hardware_mac', 'last_seen_at',
    )
    list_filter = ('status',)
    search_fields = ('badge_id', 'hardware_mac')


class GatewayNodeAdmin(admin.ModelAdmin):
    list_display = ('name', 'transport', 'active', 'last_seen_at')
    list_filter = ('transport', 'active')
    search_fields = ('name',)


class BadgeAssignmentAdmin(admin.ModelAdmin):
    list_display = ('badge', 'session', 'player', 'team', 'assigned_at', 'released_at')
    list_filter = ('session',)
    search_fields = ('badge__badge_id', 'player__user__username', 'team__name')


class BadgeTelemetryAdmin(admin.ModelAdmin):
    list_display = ('badge', 'session', 'battery_pct', 'activity', 'gesture', 'recorded_at')
    list_filter = ('activity', 'gesture')
    readonly_fields = ('imu',)


admin.site.register(Zone, ZoneAdmin)
admin.site.register(ProximityIdentity, ProximityIdentityAdmin)
admin.site.register(ProximityReport, ProximityReportAdmin)
admin.site.register(ProximityEvent, ProximityEventAdmin)
admin.site.register(DementorState, DementorStateAdmin)
admin.site.register(DementorFlip, DementorFlipAdmin)
admin.site.register(Tower, TowerAdmin)
admin.site.register(TowerPhoto, TowerPhotoAdmin)
admin.site.register(Team, TeamAdmin)
admin.site.register(Challenge, ChallengeAdmin)
admin.site.register(TeamTowerChallenge, TeamTowerChallangeAdmin)
admin.site.register(TeamTowerOwnership, TeamTowerOwnershipAdmin)
admin.site.register(PauseWindow, PauseWindowAdmin)
admin.site.register(TeamTowerFailCounter, TeamTowerFailCounterAdmin)
admin.site.register(NfcTag, NfcTagAdmin)
admin.site.register(TagScan, TagScanAdmin)
admin.site.register(TowerLock, TowerLockAdmin)
admin.site.register(BadgeDevice, BadgeDeviceAdmin)
admin.site.register(GatewayNode, GatewayNodeAdmin)
admin.site.register(BadgeAssignment, BadgeAssignmentAdmin)
admin.site.register(BadgeTelemetry, BadgeTelemetryAdmin)
