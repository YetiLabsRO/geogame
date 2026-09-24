"""Import content from a pre-Session PostgreSQL dump into the repository.

The 2021–2026 schema kept geometry on a flat `geogame_*` set of tables,
with one zone per tower, no Collections, no Sessions, and team categories
hardcoded as a smallint. This reads such a dump and lands its zones,
towers and challenges in the current schema, inside a named Collection
that a named Game links.

Reading strategy: `pg_restore` into a scratch database, read it with
plain SQL, drop the scratch database. Parsing the custom-format dump
directly would mean re-implementing PostgreSQL's COPY encoding and WKB
parsing to save one `createdb`.
"""
import subprocess

import psycopg
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from game.models import Challenge, Collection, Tower, Zone
from organize.models import Game, TeamGroup

LEGACY_TABLES = ('geogame_zone', 'geogame_tower', 'geogame_challenge')

# The categories that preceded per-Game TeamGroups, from the schema this
# dump was written by (geogame.models.Team.CATEGORY_CHOICES).
LEGACY_CATEGORIES = {
    1: ('eXplo', 'explo'),
    2: ('Temerari', 'temerari'),
    3: ('Seniori', 'seniori'),
}


class Command(BaseCommand):
    help = (
        'Import zones, towers and challenges from a pre-Session database '
        'dump into a named Collection and Game. Legacy teams, rosters and '
        'scores are not imported; their categories become TeamGroups.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'dump', nargs='?',
            help='Path to a pg_dump custom-format file. Omit with --from-db.',
        )
        parser.add_argument(
            '--collection', required=True,
            help='Name of the Collection the imported content lands in.',
        )
        parser.add_argument(
            '--game', required=True,
            help='Name of the Game that links the Collection.',
        )
        parser.add_argument(
            '--game-slug', help='Slug for the Game (derived from its name by default).',
        )
        parser.add_argument(
            '--from-db', metavar='NAME',
            help='Read an already-restored legacy database instead of a dump.',
        )
        parser.add_argument(
            '--scratch-db', metavar='NAME', default='geogame_legacy_import',
            help='Name of the scratch database the dump is restored into.',
        )
        parser.add_argument(
            '--keep-scratch-db', action='store_true',
            help='Leave the scratch database in place for inspection.',
        )
        parser.add_argument(
            '--replace', action='store_true',
            help='Replace the content of a Collection that already holds some.',
        )

    # -- plumbing -------------------------------------------------------

    def _dsn(self, dbname):
        db = settings.DATABASES['default']
        return {
            'dbname': dbname,
            'user': db['USER'],
            'password': db['PASSWORD'],
            'host': db['HOST'],
            'port': db['PORT'],
        }

    def _psql_env_args(self):
        db = settings.DATABASES['default']
        return (
            ['-h', str(db['HOST']), '-p', str(db['PORT']), '-U', str(db['USER'])],
            {'PGPASSWORD': str(db['PASSWORD'])},
        )

    def _run(self, argv, env_extra, allow_failure=False):
        import os
        env = dict(os.environ, **env_extra)
        result = subprocess.run(argv, env=env, capture_output=True, text=True)
        if result.returncode != 0 and not allow_failure:
            raise CommandError(
                f'{argv[0]} failed ({result.returncode}): '
                f'{result.stderr.strip() or result.stdout.strip()}',
            )
        return result

    def _restore(self, dump, scratch):
        args, env = self._psql_env_args()
        self.stdout.write(f'Restoring {dump} into scratch database {scratch}…')
        self._run(['dropdb', *args, '--if-exists', scratch], env)
        self._run(['createdb', *args, scratch], env)
        # PostGIS first: the dump's own CREATE EXTENSION may be refused or
        # may be absent, and the legacy tables declare geometry columns.
        self._run(
            ['psql', *args, '-d', scratch, '-c',
             'CREATE EXTENSION IF NOT EXISTS postgis'],
            env,
        )
        # Not --exit-on-error: a dump carries ownership, ACL and extension
        # statements that fail harmlessly against a fresh local database.
        # What matters is whether the tables arrived, which is checked next.
        result = self._run(
            ['pg_restore', *args, '-d', scratch, '--no-owner', '--no-privileges',
             dump],
            env, allow_failure=True,
        )
        if result.returncode != 0:
            self.stdout.write(
                self.style.WARNING(
                    f'pg_restore reported {result.stderr.count("error")} error(s); '
                    f'continuing, and verifying the tables it needed to create.',
                ),
            )

    def _drop(self, scratch):
        args, env = self._psql_env_args()
        self._run(['dropdb', *args, '--if-exists', scratch], env)

    # -- reading --------------------------------------------------------

    def _read_legacy(self, dbname):
        with psycopg.connect(**self._dsn(dbname)) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT table_name FROM information_schema.tables '
                    "WHERE table_schema = 'public'",
                )
                present = {row[0] for row in cur.fetchall()}
                missing = [t for t in LEGACY_TABLES if t not in present]
                if missing:
                    raise CommandError(
                        f'{dbname} does not look like a legacy geogame '
                        f'database: missing {", ".join(missing)}. '
                        f'Nothing was imported.',
                    )

                cur.execute(
                    'SELECT id, name, color, scoring_type, ST_AsEWKT(shape) '
                    'FROM geogame_zone ORDER BY id',
                )
                zones = cur.fetchall()

                cur.execute(
                    'SELECT id, name, ST_AsEWKT(location), category, is_active, '
                    'zone_id, rfid_code FROM geogame_tower ORDER BY id',
                )
                towers = cur.fetchall()

                cur.execute(
                    'SELECT id, text, difficulty, tower_id '
                    'FROM geogame_challenge ORDER BY id',
                )
                challenges = cur.fetchall()

                categories = []
                if 'geogame_team' in present:
                    cur.execute(
                        'SELECT DISTINCT category FROM geogame_team ORDER BY category',
                    )
                    categories = [row[0] for row in cur.fetchall()]

        return zones, towers, challenges, categories

    # -- writing --------------------------------------------------------

    def _unique_slug(self, model, name, fallback):
        base = slugify(name)[:60] or fallback
        slug, counter = base, 2
        while model.objects.filter(slug=slug).exists():
            slug = f'{base}-{counter}'
            counter += 1
        return slug

    def handle(self, *args, **options):
        dump, from_db = options['dump'], options['from_db']
        if bool(dump) == bool(from_db):
            raise CommandError('Give either a dump path or --from-db NAME, not both.')

        scratch = options['scratch_db']
        try:
            if dump:
                self._restore(dump, scratch)
                source = scratch
            else:
                source = from_db
            zones, towers, challenges, categories = self._read_legacy(source)
        finally:
            if dump and not options['keep_scratch_db']:
                self._drop(scratch)

        self.stdout.write(
            f'Read {len(zones)} zones, {len(towers)} towers, '
            f'{len(challenges)} challenges from the legacy schema.',
        )

        with transaction.atomic():
            collection = self._target_collection(options)
            game = self._target_game(options, collection)
            zone_map = self._import_zones(zones, collection)
            tower_map = self._import_towers(towers, zone_map, collection)
            self._import_challenges(challenges, tower_map, game)
            self._import_team_groups(categories, game)
            self._set_base_point(game, tower_map.values())

        self.stdout.write(
            self.style.SUCCESS(
                f'Imported into collection "{collection.name}" '
                f'(slug {collection.slug}) and game "{game.name}" '
                f'(slug {game.slug}).',
            ),
        )

    def _target_collection(self, options):
        name = options['collection']
        collection = Collection.objects.filter(name=name).first()
        if collection is None:
            return Collection.objects.create(
                name=name,
                slug=self._unique_slug(Collection, name, 'collection'),
                description='Imported from a legacy database dump.',
            )
        occupied = collection.towers.exists() or collection.zones.exists()
        if occupied and not options['replace']:
            raise CommandError(
                f'Collection "{name}" already holds '
                f'{collection.towers.count()} tower(s) and '
                f'{collection.zones.count()} zone(s). Re-run with --replace '
                f'to replace them, or name a different collection. '
                f'Nothing was imported.',
            )
        if occupied:
            # Zones FIRST. The at-least-one-tower-per-zone guard refuses
            # to delete a tower that is some zone's last member, so
            # deleting towers first cannot replace anything; dropping the
            # zones takes their membership rows with it and leaves the
            # towers free to go. Deleting the towers then cascades their
            # tower-bound challenges.
            Zone.objects.filter(collections=collection).delete()
            try:
                Tower.objects.filter(collections=collection).delete()
            except DjangoValidationError as exc:
                raise CommandError(
                    f'Cannot replace "{collection.name}": '
                    f'{" ".join(exc.messages)} Nothing was imported.',
                ) from exc
        return collection

    def _target_game(self, options, collection):
        name = options['game']
        game = Game.objects.filter(name=name).first()
        if game is None:
            game = Game.objects.create(
                name=name,
                slug=options['game_slug'] or self._unique_slug(Game, name, 'game'),
            )
        game.collections.add(collection)
        return game

    def _import_zones(self, rows, collection):
        zone_map = {}
        for legacy_id, name, color, scoring_type, ewkt in rows:
            zone = Zone.objects.create(
                name=(name or '').strip() or f'Zone {legacy_id}',
                color=color or '#000000',
                scoring_type=scoring_type,
                shape=GEOSGeometry(ewkt) if ewkt else None,
            )
            collection.zones.add(zone)
            zone_map[legacy_id] = zone
        return zone_map

    def _import_towers(self, rows, zone_map, collection):
        tower_map = {}
        for legacy_id, name, ewkt, category, is_active, zone_id, rfid_code in rows:
            code = (rfid_code or '').strip() or None
            if code and Tower.objects.filter(rfid_code=code).exists():
                self.stdout.write(
                    self.style.WARNING(
                        f'Tower "{name}": rfid code {code} is already held '
                        f'here; imported without it.',
                    ),
                )
                code = None
            tower = Tower.objects.create(
                name=(name or '').strip() or f'Tower {legacy_id}',
                location=GEOSGeometry(ewkt),
                category=category,
                is_active=bool(is_active),
                rfid_code=code,
            )
            zone = zone_map.get(zone_id)
            if zone is not None:
                tower.zones.add(zone)
            elif zone_id is not None:
                self.stdout.write(
                    self.style.WARNING(
                        f'Tower "{tower.name}" named legacy zone {zone_id}, '
                        f'which is not in the dump; imported with no zone.',
                    ),
                )
            collection.towers.add(tower)
            tower_map[legacy_id] = tower
        return tower_map

    def _import_challenges(self, rows, tower_map, game):
        floating = 0
        for legacy_id, text, difficulty, tower_id in rows:
            tower = tower_map.get(tower_id) if tower_id else None
            if tower_id and tower is None:
                self.stdout.write(
                    self.style.WARNING(
                        f'Challenge {legacy_id} named legacy tower {tower_id}, '
                        f'which is not in the dump; skipped.',
                    ),
                )
                continue
            if tower is None:
                floating += 1
            Challenge.objects.create(
                game=game,
                tower=tower,
                text=(text or '').strip(),
                difficulty=difficulty or 1,
            )
        if floating:
            self.stdout.write(
                f'{floating} challenge(s) had no tower and became '
                f'game-wide challenges.',
            )

    def _import_team_groups(self, categories, game):
        for category in categories:
            name, slug = LEGACY_CATEGORIES.get(
                category, (f'Group {category}', f'group-{category}'),
            )
            TeamGroup.objects.get_or_create(
                game=game, slug=slug, defaults={'name': name},
            )
        if categories:
            self.stdout.write(
                f'Created {len(categories)} TeamGroup(s) from the legacy '
                f'team categories; no teams, rosters or scores were imported.',
            )

    def _set_base_point(self, game, towers):
        """Open the staff map on the town rather than on null island."""
        towers = [t for t in towers if t.location]
        if not towers or game.base_point is not None:
            return
        game.base_point = GEOSGeometry(
            'POINT({} {})'.format(
                sum(t.location.x for t in towers) / len(towers),
                sum(t.location.y for t in towers) / len(towers),
            ),
            srid=4326,
        )
        game.save(update_fields=['base_point'])
