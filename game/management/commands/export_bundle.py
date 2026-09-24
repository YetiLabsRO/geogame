"""Write selected Games and Collections to a portable content bundle."""
import sys

from django.core.management.base import BaseCommand, CommandError

from game import bundles
from game.models import Collection
from organize.models import Game


def resolve(model, tokens, label):
    """Resolve slugs or numeric ids to rows, naming what it could not find."""
    found, missing = [], []
    for token in tokens:
        row = None
        if token.isdigit():
            row = model.objects.filter(pk=int(token)).first()
        if row is None:
            row = model.objects.filter(slug=token).first()
        if row is None:
            missing.append(token)
        else:
            found.append(row)
    if missing:
        raise CommandError(
            f'No {label} matching {", ".join(repr(m) for m in missing)}. '
            f'Available: {", ".join(model.objects.values_list("slug", flat=True)) or "none"}',
        )
    return found


class Command(BaseCommand):
    help = (
        'Export Games and Collections, with the repository content they '
        'depend on, into one portable bundle. Run data (sessions, teams, '
        'scores, submissions) is never included.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--game', action='append', default=[], metavar='SLUG_OR_ID',
            help='A Game to export. Repeatable.',
        )
        parser.add_argument(
            '--collection', action='append', default=[], metavar='SLUG_OR_ID',
            help='A Collection to export. Repeatable. A Game already brings '
                 'the Collections it links.',
        )
        # `-o -` rather than a `--stdout` flag: argparse would map that
        # flag's name onto `call_command(stdout=...)`, so every scripted
        # call asking for captured output would get a zip on stdout.
        parser.add_argument(
            '-o', '--output', metavar='PATH',
            help="Where to write the bundle; '-' writes it to stdout.",
        )

    def handle(self, *args, **options):
        if not options['game'] and not options['collection']:
            raise CommandError('Name at least one --game or --collection.')
        if not options['output']:
            raise CommandError("Give --output PATH, or '-o -' to pipe it.")

        games = resolve(Game, options['game'], 'Game')
        collections = resolve(Collection, options['collection'], 'Collection')

        payload, files = bundles.build_bundle(games=games, collections=collections)

        if options['output'] == '-':
            bundles.write_bundle(payload, files, sys.stdout.buffer)
            return

        with open(options['output'], 'wb') as fh:
            bundles.write_bundle(payload, files, fh)

        counts = ', '.join(
            f'{len(rows)} {key}' for key, rows in payload['content'].items()
        )
        self.stdout.write(
            f'Wrote {options["output"]}: {counts or "nothing"}'
            + (f', {len(files)} media file(s)' if files else ''),
        )
