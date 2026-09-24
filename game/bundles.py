"""Portable content bundles — moving maps and game templates between installs.

A bundle is one zip holding `bundle.json` plus the media its content
references. It carries the *authored* half of the system — repository
geometry, collections, and Game templates with their challenge banks —
and none of the half that belongs to a run.

Everything here is driven by `MANIFEST`, one `BundleSpec` per exported
model. Export walks it in order; import walks it in the same order,
resolving references through the uuids the rows carry. Adding a model
to bundles is an entry in that list, not a new pair of functions — the
alternative drifts the moment someone adds a field and remembers to
update only one side of it.

Scalar fields are *derived* from the model rather than listed, so a new
config field travels without anyone having to remember. The cost of
that choice is that a field which should NOT travel has to be named in
`exclude`; `validate_manifest()` makes a forgotten relation loud rather
than silent.
"""
import io
import json
import posixpath
import zipfile
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timezone
from uuid import UUID, uuid4

from django.contrib.gis.db.models import GeometryField
from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, models, transaction
from django.utils.dateparse import parse_datetime, parse_duration
from django.utils.duration import duration_iso_string

FORMAT = 'cercetador-content-bundle'
FORMAT_VERSION = 1

BUNDLE_JSON = 'bundle.json'
MEDIA_ROOT = 'media/'

# Every geometry in this project is stored in WGS84; GeoJSON carries no
# SRID of its own, so it is re-applied on the way back in.
SRID = 4326

# Caps applied to an uploaded archive before anything is read out of it.
# Staff-gated is not the same as trusted: staff paste files from elsewhere.
MAX_ENTRIES = 5_000
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_JSON_BYTES = 32 * 1024 * 1024

MODE_SYNC = 'sync'
MODE_COPY = 'copy'
MODES = (MODE_SYNC, MODE_COPY)


class BundleError(Exception):
    """A bundle that cannot be read, or cannot be applied as asked."""


class ManifestError(Exception):
    """The manifest itself is inconsistent — a programming error, not input."""


@dataclass(frozen=True)
class BundleSpec:
    """How one model is carried in a bundle.

    `exclude` names concrete fields that deliberately do not travel.
    Relation fields must appear in `refs`, `m2m` or `exclude`; anything
    else is a manifest bug and `validate_manifest` says so.
    """

    key: str
    model: type
    refs: dict = dataclass_field(default_factory=dict)
    m2m: dict = dataclass_field(default_factory=dict)
    files: tuple = ()
    exclude: tuple = ()
    # Unique scalar fields that may collide with a row already here. On
    # collision the incumbent keeps the value and the arriving row gives
    # it up, rather than the whole import failing over it.
    yielding_uniques: tuple = ()
    # A globally unique slug, suffixed in copy mode so a second copy can
    # land beside the first.
    slug_field: str = None
    # Refs (plus optional scalar fields) that identify this row within its
    # owner when the uuid does not match anything here. Two installs can
    # each grow their own `cook` role on the same Game, or their own Trail
    # for it; without this, syncing one into the other hits a unique
    # constraint and refuses a bundle that is not actually in conflict.
    # In sync mode such a row is adopted: updated in place, and given the
    # bundle's uuid so the two installs converge instead of colliding
    # again on the next sync.
    owner_key: tuple = ()
    # Fields written only AFTER the row's m2m sets are populated, because
    # writing them earlier fires an authoring side effect. The only case
    # today is `Tower.autocreate_zone`: `Tower.save()` conjures a
    # circular zone for a tower that belongs to none, which during an
    # import is every tower until its `zones` set lands.
    post_m2m_fields: tuple = ()

    @property
    def label(self):
        return self.model._meta.verbose_name_plural


# Order is load-bearing: every `refs` and `m2m` target must appear
# earlier than the spec that points at it, so one ordered pass resolves
# everything. `validate_manifest` enforces it.
MANIFEST = []


def _build_manifest():
    from game.models import (
        Challenge,
        Collection,
        PresenceRequirement,
        ScoreMultiplier,
        Tower,
        TowerPhoto,
        TowerType,
        Trail,
        TrailEdge,
        TrailStep,
        Zone,
    )
    from organize.models import Game, GameRole, TeamGroup

    return [
        BundleSpec(key='tower_types', model=TowerType, slug_field='slug'),
        BundleSpec(key='zones', model=Zone),
        BundleSpec(
            key='towers',
            model=Tower,
            refs={'tower_type': 'tower_types'},
            m2m={'zones': 'zones'},
            # Physically bound to one town's hardware, but an install's
            # second database should keep it; on collision the incumbent
            # wins (see `yielding_uniques`).
            yielding_uniques=('rfid_code',),
            post_m2m_fields=('autocreate_zone',),
        ),
        BundleSpec(
            key='tower_photos',
            model=TowerPhoto,
            refs={'tower': 'towers'},
            files=('image',),
            # A user id from another install names nobody here.
            exclude=('captured_by',),
        ),
        BundleSpec(
            key='collections',
            model=Collection,
            m2m={'towers': 'towers', 'zones': 'zones'},
            exclude=('created_by',),
            slug_field='slug',
        ),
        BundleSpec(key='presence_requirements', model=PresenceRequirement),
        BundleSpec(
            key='games',
            model=Game,
            m2m={'collections': 'collections'},
            # `is_active` and `cloned_from` are local facts: whether a
            # template is live here, and what it was copied from here.
            # An imported Game lands inactive and unattributed.
            exclude=('created_by', 'cloned_from', 'is_active'),
            slug_field='slug',
        ),
        BundleSpec(
            key='game_roles', model=GameRole, refs={'game': 'games'},
            owner_key=('game', 'slug'),
        ),
        BundleSpec(
            key='team_groups', model=TeamGroup, refs={'game': 'games'},
            owner_key=('game', 'slug'),
        ),
        BundleSpec(
            key='challenges',
            model=Challenge,
            refs={
                'game': 'games',
                'tower': 'towers',
                'presence_requirement': 'presence_requirements',
            },
            m2m={'required_roles': 'game_roles'},
        ),
        BundleSpec(
            key='score_multipliers',
            model=ScoreMultiplier,
            refs={'game': 'games', 'tower': 'towers', 'zone': 'zones'},
            # Session-owned multipliers belong to one run and never travel.
            exclude=('session', 'created_by'),
        ),
        # One trail per Game (OneToOne), so the Game identifies it.
        BundleSpec(
            key='trails', model=Trail, refs={'game': 'games'},
            owner_key=('game',),
        ),
        BundleSpec(
            key='trail_steps',
            model=TrailStep,
            refs={
                'trail': 'trails',
                'tower': 'towers',
                'gate_challenge': 'challenges',
            },
        ),
        BundleSpec(
            key='trail_edges',
            model=TrailEdge,
            refs={
                'trail': 'trails',
                'from_step': 'trail_steps',
                'to_step': 'trail_steps',
            },
        ),
    ]


def manifest():
    """The manifest, built lazily so this module imports before the apps do."""
    if not MANIFEST:
        MANIFEST.extend(_build_manifest())
    return MANIFEST


def spec_for(key):
    for spec in manifest():
        if spec.key == key:
            return spec
    raise ManifestError(f'No bundle spec named {key!r}.')


# ---------------------------------------------------------------------------
# Field derivation
# ---------------------------------------------------------------------------


def _is_auto_timestamp(f):
    return getattr(f, 'auto_now_add', False) or getattr(f, 'auto_now', False)


def scalar_fields(spec):
    """The concrete, non-relational fields this spec carries.

    Derived rather than listed. Excluded by construction: the primary
    key, `uuid` (carried separately as identity), auto timestamps (which
    record when the *source* row was written, not anything about the
    content), file fields (carried as archive entries), relations (in
    `refs`/`m2m`), and whatever the spec names in `exclude`.
    """
    skip = (
        {'uuid'}
        | set(spec.refs)
        | set(spec.m2m)
        | set(spec.files)
        | set(spec.exclude)
    )
    out = []
    for f in spec.model._meta.concrete_fields:
        if f.primary_key or f.name in skip or _is_auto_timestamp(f):
            continue
        if f.is_relation:
            continue
        out.append(f)
    return out


def validate_manifest():
    """Raise if the manifest is inconsistent. Cheap; called before use."""
    seen = set()
    for index, spec in enumerate(manifest()):
        if spec.key in seen:
            raise ManifestError(f'Duplicate spec key {spec.key!r}.')
        seen.add(spec.key)

        if not hasattr(spec.model, 'uuid'):
            raise ManifestError(
                f'{spec.model.__name__} has no uuid field; bundles identify '
                f'rows by uuid and cannot carry it.',
            )

        declared = set(spec.refs) | set(spec.m2m) | set(spec.exclude) | set(spec.files)
        relations = [
            f for f in spec.model._meta.concrete_fields if f.is_relation
        ] + list(spec.model._meta.many_to_many)
        for f in relations:
            if f.name in declared:
                continue
            raise ManifestError(
                f'{spec.model.__name__}.{f.name} is a relation that the '
                f'bundle manifest neither carries nor excludes. Add it to '
                f'refs/m2m if it should travel, or to exclude if it should '
                f'not — silence here would export a primary key from '
                f'another database.',
            )

        field_names = {f.name for f in spec.model._meta.concrete_fields}
        for name in spec.owner_key:
            if name not in spec.refs and name not in field_names:
                raise ManifestError(
                    f'{spec.key}.owner_key names {name!r}, which is neither '
                    f'a carried ref nor a field of {spec.model.__name__}.',
                )

        for name, target in list(spec.refs.items()) + list(spec.m2m.items()):
            positions = [i for i, s in enumerate(manifest()) if s.key == target]
            if not positions:
                raise ManifestError(
                    f'{spec.key}.{name} points at unknown spec {target!r}.',
                )
            if positions[0] > index:
                raise ManifestError(
                    f'{spec.key}.{name} points at {target!r}, which comes '
                    f'later in the manifest; one ordered pass could not '
                    f'resolve it.',
                )


# ---------------------------------------------------------------------------
# Value encoding
# ---------------------------------------------------------------------------


def encode_value(f, value):
    if value is None:
        return None
    if isinstance(f, GeometryField):
        # GeoJSON carries no SRID; every geometry here is WGS84.
        return json.loads(value.geojson)
    if isinstance(f, models.DurationField):
        return duration_iso_string(value)
    if isinstance(f, (models.DateTimeField, models.DateField)):
        return value.isoformat()
    if isinstance(f, models.UUIDField):
        return str(value)
    if isinstance(f, models.DecimalField):
        return str(value)
    return value


def decode_value(f, value):
    if value is None:
        return None
    if isinstance(f, GeometryField):
        return GEOSGeometry(json.dumps(value), srid=SRID)
    if isinstance(f, models.DurationField):
        return parse_duration(value)
    if isinstance(f, models.DateTimeField):
        return parse_datetime(value)
    if isinstance(f, models.DateField):
        return parse_datetime(value).date() if 'T' in value else value
    return value


# ---------------------------------------------------------------------------
# Selection closure
# ---------------------------------------------------------------------------


def collect(games=(), collections=()):
    """Everything the selection needs, keyed by spec, in manifest order.

    A Game pulls the Collections it links, which pull their Towers and
    Zones. Challenges, multipliers and trail steps can also point at
    geometry that has since left those Collections — that geometry is
    pulled in too, because a bundle with a dangling reference is not a
    bundle.
    """
    from game.models import (
        Challenge,
        Collection,
        PresenceRequirement,
        ScoreMultiplier,
        Tower,
        TowerPhoto,
        TowerType,
        Trail,
        TrailEdge,
        TrailStep,
        Zone,
    )
    from organize.models import GameRole, TeamGroup

    games = list(games)
    game_ids = [g.pk for g in games]

    collection_ids = {c.pk for c in collections}
    for game in games:
        collection_ids.update(game.collections.values_list('pk', flat=True))
    collections = list(Collection.objects.filter(pk__in=collection_ids))

    challenges = list(
        Challenge.objects.filter(game_id__in=game_ids).prefetch_related('required_roles'),
    )
    multipliers = list(ScoreMultiplier.objects.filter(game_id__in=game_ids))
    trails = list(Trail.objects.filter(game_id__in=game_ids))
    trail_ids = [t.pk for t in trails]
    steps = list(TrailStep.objects.filter(trail_id__in=trail_ids))
    edges = list(TrailEdge.objects.filter(trail_id__in=trail_ids))

    tower_ids = set(
        Tower.objects.filter(collections__pk__in=collection_ids).values_list('pk', flat=True),
    )
    zone_ids = set(
        Zone.objects.filter(collections__pk__in=collection_ids).values_list('pk', flat=True),
    )
    tower_ids.update(c.tower_id for c in challenges if c.tower_id)
    tower_ids.update(m.tower_id for m in multipliers if m.tower_id)
    tower_ids.update(s.tower_id for s in steps if s.tower_id)
    zone_ids.update(m.zone_id for m in multipliers if m.zone_id)
    # A tower's zone membership is part of the tower; carrying the tower
    # without the zones it sits in would import a tower into nowhere.
    zone_ids.update(
        Zone.objects.filter(towers__pk__in=tower_ids).values_list('pk', flat=True),
    )

    towers = list(Tower.objects.filter(pk__in=tower_ids).prefetch_related('zones'))
    zones = list(Zone.objects.filter(pk__in=zone_ids))
    type_ids = {t.tower_type_id for t in towers if t.tower_type_id}
    requirement_ids = {
        c.presence_requirement_id for c in challenges if c.presence_requirement_id
    }

    return {
        'tower_types': list(TowerType.objects.filter(pk__in=type_ids)),
        'zones': zones,
        'towers': towers,
        'tower_photos': list(TowerPhoto.objects.filter(tower_id__in=tower_ids)),
        'collections': collections,
        'presence_requirements': list(
            PresenceRequirement.objects.filter(pk__in=requirement_ids),
        ),
        'games': games,
        'game_roles': list(GameRole.objects.filter(game_id__in=game_ids)),
        'team_groups': list(TeamGroup.objects.filter(game_id__in=game_ids)),
        'challenges': challenges,
        'score_multipliers': multipliers,
        'trails': trails,
        'trail_steps': steps,
        'trail_edges': edges,
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def _row_for(spec, obj, files):
    row = {'uuid': str(obj.uuid)}
    for f in scalar_fields(spec):
        row[f.name] = encode_value(f, getattr(obj, f.name))
    for name, target in spec.refs.items():
        related = getattr(obj, name, None)
        row[name] = str(related.uuid) if related is not None else None
    for name, target in spec.m2m.items():
        row[name] = [str(u) for u in getattr(obj, name).values_list('uuid', flat=True)]
    for name in spec.files:
        row[name] = _stash_file(spec, obj, name, files)
    return row


def _stash_file(spec, obj, name, files):
    """Record a file field's bytes for the archive; None when absent."""
    handle = getattr(obj, name, None)
    if not handle:
        return None
    basename = posixpath.basename(handle.name)
    arcname = f'{MEDIA_ROOT}{spec.key}/{obj.uuid}/{basename}'
    try:
        with handle.open('rb') as fh:
            files[arcname] = fh.read()
    except (FileNotFoundError, OSError, ValueError):
        # The database says there is a photo and storage disagrees. Export
        # the row without it rather than failing the whole bundle.
        return None
    return arcname


def build_bundle(games=(), collections=()):
    """The bundle payload and its media, as (dict, {arcname: bytes})."""
    validate_manifest()
    selection = collect(games=games, collections=collections)
    files = {}
    content = {}
    for spec in manifest():
        rows = [_row_for(spec, obj, files) for obj in selection.get(spec.key, [])]
        if rows:
            content[spec.key] = rows
    payload = {
        'format': FORMAT,
        'format_version': FORMAT_VERSION,
        'exported_at': datetime.now(timezone.utc).isoformat(),
        'selection': {
            'games': sorted(g.slug for g in games),
            'collections': sorted(c.slug for c in selection['collections']),
        },
        'content': content,
    }
    return payload, files


def write_bundle(payload, files, fileobj):
    with zipfile.ZipFile(fileobj, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            BUNDLE_JSON, json.dumps(payload, ensure_ascii=False, indent=2),
        )
        for arcname, data in files.items():
            archive.writestr(arcname, data)
    return fileobj


def export_bundle(games=(), collections=(), fileobj=None):
    """Export a selection into `fileobj` (a BytesIO when not given)."""
    payload, files = build_bundle(games=games, collections=collections)
    return write_bundle(payload, files, fileobj or io.BytesIO()), payload


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


class Bundle:
    """A validated archive: its payload, and access to its media."""

    def __init__(self, payload, archive):
        self.payload = payload
        self.archive = archive

    @property
    def content(self):
        return self.payload.get('content', {})

    def rows(self, key):
        return self.content.get(key, [])

    def read_file(self, arcname):
        return self.archive.read(arcname)

    def close(self):
        self.archive.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _safe_entry(name):
    """True when an archive entry name stays inside the archive."""
    if not name or name.startswith('/') or '\\' in name:
        return False
    parts = name.split('/')
    return '..' not in parts and not any(p == '' for p in parts[:-1])


def read_bundle(fileobj):
    """Open and validate an archive, without applying anything.

    Refuses before reading content: a non-zip, a missing or oversized
    `bundle.json`, entries that escape the archive root, too many
    entries, too much uncompressed data, an unknown format or version,
    and content naming a kind the manifest does not know.
    """
    validate_manifest()
    try:
        archive = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile as exc:
        raise BundleError(f'Not a readable bundle archive: {exc}') from exc

    infos = archive.infolist()
    if len(infos) > MAX_ENTRIES:
        archive.close()
        raise BundleError(
            f'Archive has {len(infos)} entries; the limit is {MAX_ENTRIES}.',
        )
    total = 0
    for info in infos:
        if not _safe_entry(info.filename):
            archive.close()
            raise BundleError(f'Unsafe archive entry name: {info.filename!r}')
        if info.filename != BUNDLE_JSON and not info.filename.startswith(MEDIA_ROOT):
            archive.close()
            raise BundleError(
                f'Unexpected archive entry {info.filename!r}; a bundle holds '
                f'{BUNDLE_JSON} and {MEDIA_ROOT} only.',
            )
        total += info.file_size
        if total > MAX_UNCOMPRESSED_BYTES:
            archive.close()
            raise BundleError(
                f'Archive expands past the {MAX_UNCOMPRESSED_BYTES} byte limit.',
            )

    try:
        info = archive.getinfo(BUNDLE_JSON)
    except KeyError:
        archive.close()
        raise BundleError(f'Archive has no {BUNDLE_JSON}.') from None
    if info.file_size > MAX_JSON_BYTES:
        archive.close()
        raise BundleError(f'{BUNDLE_JSON} is larger than {MAX_JSON_BYTES} bytes.')

    try:
        payload = json.loads(archive.read(BUNDLE_JSON).decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        archive.close()
        raise BundleError(f'{BUNDLE_JSON} is not readable JSON: {exc}') from exc

    if not isinstance(payload, dict) or payload.get('format') != FORMAT:
        archive.close()
        raise BundleError(
            f'Not a {FORMAT}; found format {payload.get("format")!r}.'
            if isinstance(payload, dict) else f'{BUNDLE_JSON} is not an object.',
        )
    version = payload.get('format_version')
    if version != FORMAT_VERSION:
        archive.close()
        raise BundleError(
            f'Bundle format version {version!r}; this install reads version '
            f'{FORMAT_VERSION}. Nothing was imported.',
        )

    content = payload.get('content')
    if not isinstance(content, dict):
        archive.close()
        raise BundleError(f'{BUNDLE_JSON} has no content object.')
    known = {spec.key for spec in manifest()}
    for key, rows in content.items():
        if key not in known:
            archive.close()
            raise BundleError(f'Bundle carries unknown content kind {key!r}.')
        if not isinstance(rows, list):
            archive.close()
            raise BundleError(f'Content {key!r} is not a list.')
        for row in rows:
            if not isinstance(row, dict) or not row.get('uuid'):
                archive.close()
                raise BundleError(f'A {key!r} row has no uuid.')
            try:
                UUID(str(row['uuid']))
            except ValueError:
                archive.close()
                raise BundleError(
                    f'A {key!r} row has an unreadable uuid {row["uuid"]!r}.',
                ) from None

    return Bundle(payload, archive)


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------


def _slug_collisions(bundle, mode):
    """Slugs held here by a DIFFERENT row than the bundle's.

    Only a problem in sync mode; copy mode suffixes its way around them.
    """
    out = []
    if mode == MODE_COPY:
        return out
    for spec in manifest():
        if not spec.slug_field:
            continue
        for row in bundle.rows(spec.key):
            slug = row.get(spec.slug_field)
            if not slug:
                continue
            clash = (
                spec.model.objects.filter(**{spec.slug_field: slug})
                .exclude(uuid=row['uuid'])
                .first()
            )
            if clash is not None:
                out.append({
                    'kind': spec.key,
                    'slug': slug,
                    'name': str(clash),
                    'incoming_uuid': row['uuid'],
                })
    return out


def inspect_bundle(bundle, mode=MODE_SYNC):
    """What this bundle holds and what importing it would do. Writes nothing."""
    kinds = []
    for spec in manifest():
        rows = bundle.rows(spec.key)
        if not rows:
            continue
        uuids = [row['uuid'] for row in rows]
        present = spec.model.objects.filter(uuid__in=uuids).count()
        kinds.append({
            'kind': spec.key,
            'label': str(spec.label),
            'in_bundle': len(rows),
            'already_here': present,
            'would_create': len(rows) if mode == MODE_COPY else len(rows) - present,
            'would_update': 0 if mode == MODE_COPY else present,
        })
    return {
        'format_version': bundle.payload.get('format_version'),
        'exported_at': bundle.payload.get('exported_at'),
        'selection': bundle.payload.get('selection', {}),
        'mode': mode,
        'kinds': kinds,
        'slug_collisions': _slug_collisions(bundle, mode),
        'media_files': sum(
            1 for n in bundle.archive.namelist() if n.startswith(MEDIA_ROOT)
        ),
    }


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


@dataclass
class ImportReport:
    mode: str = MODE_SYNC
    created: dict = dataclass_field(default_factory=dict)
    updated: dict = dataclass_field(default_factory=dict)
    conflicts: list = dataclass_field(default_factory=list)
    media: int = 0

    def record(self, key, was_created):
        bucket = self.created if was_created else self.updated
        bucket[key] = bucket.get(key, 0) + 1

    def conflict(self, kind, message):
        self.conflicts.append({'kind': kind, 'message': message})

    def as_dict(self):
        return {
            'mode': self.mode,
            'created': self.created,
            'updated': self.updated,
            'conflicts': self.conflicts,
            'media': self.media,
            'total_created': sum(self.created.values()),
            'total_updated': sum(self.updated.values()),
        }

    def summary(self):
        lines = [f'mode: {self.mode}']
        for key in sorted(set(self.created) | set(self.updated)):
            lines.append(
                f'  {key}: {self.created.get(key, 0)} created, '
                f'{self.updated.get(key, 0)} updated',
            )
        if self.media:
            lines.append(f'  media files: {self.media}')
        for conflict in self.conflicts:
            lines.append(f'  ! {conflict["kind"]}: {conflict["message"]}')
        return '\n'.join(lines)


def _unique_slug(spec, slug):
    base, counter = slug, 2
    field = spec.slug_field
    max_length = spec.model._meta.get_field(field).max_length or 80
    while spec.model.objects.filter(**{field: slug}).exists():
        suffix = f'-{counter}'
        slug = f'{base[:max_length - len(suffix)]}{suffix}'
        counter += 1
    return slug


def _adopt(spec, row, resolved, mode):
    """An existing row this bundle row means, found by its owner key.

    Only in sync mode, and only when the uuid matched nothing: the
    bundle's uuid then replaces the local one so the next sync matches
    directly.
    """
    if mode != MODE_SYNC or not spec.owner_key:
        return None
    lookup = {}
    for name in spec.owner_key:
        if name in spec.refs:
            related = _resolve_ref(
                spec, name, spec.refs[name], row.get(name), resolved, mode,
            )
            if related is None:
                return None
            lookup[name] = related
        else:
            if row.get(name) is None:
                return None
            lookup[name] = row[name]
    return spec.model.objects.filter(**lookup).first()


def _resolve_ref(spec, name, target_key, value, resolved, mode):
    if value is None:
        return None
    key = (target_key, str(value))
    if key in resolved:
        return resolved[key]
    if mode == MODE_COPY:
        raise BundleError(
            f'{spec.key}.{name} points at a {target_key} row the bundle does '
            f'not carry; a copy cannot be made from an incomplete bundle.',
        )
    target = spec_for(target_key)
    instance = target.model.objects.filter(uuid=value).first()
    if instance is None:
        raise BundleError(
            f'{spec.key}.{name} points at {target_key} {value}, which is '
            f'neither in the bundle nor in this database.',
        )
    resolved[key] = instance
    return instance


def _apply_yielding_uniques(spec, instance, report):
    for name in spec.yielding_uniques:
        value = getattr(instance, name, None)
        if value in (None, ''):
            continue
        clash = spec.model.objects.filter(**{name: value})
        if instance.pk:
            clash = clash.exclude(pk=instance.pk)
        if clash.exists():
            setattr(instance, name, None)
            report.conflict(
                spec.key,
                f'{instance.name if hasattr(instance, "name") else instance}: '
                f'{name} {value!r} is already held here; kept the existing '
                f'one and imported the rest.',
            )


def import_bundle(bundle, mode=MODE_SYNC):
    """Apply a bundle. One transaction: it lands whole or not at all."""
    if mode not in MODES:
        raise BundleError(f'Unknown import mode {mode!r}; expected one of {MODES}.')
    validate_manifest()

    collisions = _slug_collisions(bundle, mode)
    if collisions:
        listed = '; '.join(
            f'{c["kind"]} {c["slug"]!r} (held by {c["name"]})' for c in collisions
        )
        raise BundleError(
            f'Importing would collide with content already here: {listed}. '
            f'Import as a copy to land it alongside, or rename what is here. '
            f'Nothing was imported.',
        )

    report = ImportReport(mode=mode)
    resolved = {}

    # One ordered pass: the manifest is topologically sorted, so every
    # reference a row makes — FK or m2m — points at a spec already done.
    try:
        with transaction.atomic():
            for spec in manifest():
                for row in bundle.rows(spec.key):
                    instance, created = _import_row(
                        spec, row, bundle, mode, resolved, report,
                    )
                    resolved[(spec.key, str(row['uuid']))] = instance
                    _set_m2m(spec, instance, row, resolved, mode)
                    _apply_post_m2m(spec, instance, row)
                    report.record(spec.key, created)
    except ValidationError as exc:
        # A model invariant refused the shape the bundle describes — the
        # at-least-one-tower-per-zone guard is the one that can fire here.
        raise BundleError(
            f'A model invariant refused this bundle: '
            f'{"; ".join(exc.messages)} Nothing was imported.',
        ) from exc
    except IntegrityError as exc:
        # A unique constraint this layer does not know about. Reported
        # rather than raised raw, because the operator's next move is the
        # same either way: import as a copy, or reconcile by hand.
        raise BundleError(
            f'A database constraint refused this bundle: {exc} '
            f'Import as a copy to land it alongside what is here. '
            f'Nothing was imported.',
        ) from exc
    return report


def _set_m2m(spec, instance, row, resolved, mode):
    for name, target_key in spec.m2m.items():
        if name not in row:
            continue
        related = [
            _resolve_ref(spec, name, target_key, value, resolved, mode)
            for value in row.get(name) or []
        ]
        getattr(instance, name).set([r for r in related if r is not None])


def _apply_post_m2m(spec, instance, row):
    """Write the fields that had to wait for the m2m sets to land."""
    if not spec.post_m2m_fields:
        return
    changed = []
    for name in spec.post_m2m_fields:
        if name not in row:
            continue
        f = spec.model._meta.get_field(name)
        setattr(instance, name, decode_value(f, row[name]))
        changed.append(name)
    if changed:
        instance.save(update_fields=changed)


def _import_row(spec, row, bundle, mode, resolved, report):
    row_uuid = str(row['uuid'])
    instance = None
    if mode == MODE_SYNC:
        instance = spec.model.objects.filter(uuid=row_uuid).first()
        if instance is None:
            instance = _adopt(spec, row, resolved, mode)
            if instance is not None:
                instance.uuid = UUID(row_uuid)
    created = instance is None
    if instance is None:
        instance = spec.model()
        instance.uuid = uuid4() if mode == MODE_COPY else UUID(row_uuid)

    for f in scalar_fields(spec):
        if f.name in row and f.name not in spec.post_m2m_fields:
            setattr(instance, f.name, decode_value(f, row[f.name]))
    if spec.slug_field and mode == MODE_COPY:
        setattr(
            instance,
            spec.slug_field,
            _unique_slug(spec, getattr(instance, spec.slug_field) or ''),
        )
    for name, target_key in spec.refs.items():
        setattr(
            instance,
            name,
            _resolve_ref(spec, name, target_key, row.get(name), resolved, mode),
        )
    _apply_yielding_uniques(spec, instance, report)

    for name in spec.files:
        arcname = row.get(name)
        if not arcname:
            continue
        try:
            data = bundle.read_file(arcname)
        except KeyError:
            report.conflict(
                spec.key, f'{arcname} is named by the bundle but not in it.',
            )
            continue
        # The storage backend names the file; a path from the archive is
        # never used as a destination.
        getattr(instance, name).save(
            posixpath.basename(arcname), ContentFile(data), save=False,
        )
        report.media += 1

    instance.save()
    return instance, created
