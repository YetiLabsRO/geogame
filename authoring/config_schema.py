"""Machine-readable config-knob catalog, generated from live fields.

The LLM only builds games from valid options, so the schema is derived
from the Game model's own field definitions (types, enums, defaults,
help text) — never a hand-maintained list that could drift.
"""
from django.db import models

from organize.models import OVERRIDABLE_CONFIG_FIELDS, Game


def _field_type(field):
    if field.choices:
        return 'enum'
    if isinstance(field, models.BooleanField):
        return 'boolean'
    if isinstance(field, (models.IntegerField, models.SmallIntegerField)):
        return 'integer'
    if isinstance(field, models.FloatField):
        return 'number'
    if isinstance(field, (models.CharField, models.TextField)):
        return 'string'
    return field.get_internal_type()


def describe_config_schema():
    """Return the overridable config knobs with type/enum/default/docs.

    Reads the Game model (the source of defaults); each knob is also
    overridable per Session. Order follows OVERRIDABLE_CONFIG_FIELDS.
    """
    knobs = []
    for name in OVERRIDABLE_CONFIG_FIELDS:
        try:
            field = Game._meta.get_field(name)
        except Exception:  # noqa: BLE001 - a stray/removed field name
            continue
        entry = {
            'name': name,
            'type': _field_type(field),
            'default': field.get_default(),
            'help': str(getattr(field, 'help_text', '') or ''),
            'overridable_per_session': True,
        }
        if field.choices:
            entry['enum'] = [
                {'value': value, 'label': str(label)}
                for value, label in field.choices
            ]
        knobs.append(entry)
    return {'knobs': knobs, 'count': len(knobs)}
