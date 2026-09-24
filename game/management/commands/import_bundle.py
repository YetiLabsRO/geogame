"""Apply a portable content bundle to this install."""
from django.core.management.base import BaseCommand, CommandError

from game import bundles


class Command(BaseCommand):
    help = (
        'Import a content bundle. In sync mode (the default) content this '
        'install already holds is updated in place; in copy mode the bundle '
        'lands as an independent second copy with fresh identities and '
        'suffixed slugs. Either way it is one transaction: it applies whole '
        'or not at all.'
    )

    def add_arguments(self, parser):
        parser.add_argument('path', help='The bundle file to read.')
        parser.add_argument(
            '--mode', choices=bundles.MODES, default=bundles.MODE_SYNC,
            help='sync: update what is already here. copy: land an '
                 'independent copy beside it.',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Report what the bundle holds and what would happen, '
                 'without writing anything.',
        )

    def handle(self, *args, **options):
        try:
            fh = open(options['path'], 'rb')
        except OSError as exc:
            raise CommandError(f'Cannot read {options["path"]}: {exc}') from exc

        with fh:
            try:
                bundle = bundles.read_bundle(fh)
            except bundles.BundleError as exc:
                raise CommandError(str(exc)) from exc

            with bundle:
                if options['dry_run']:
                    self._report_inspection(
                        bundles.inspect_bundle(bundle, mode=options['mode']),
                    )
                    return
                try:
                    report = bundles.import_bundle(bundle, mode=options['mode'])
                except bundles.BundleError as exc:
                    raise CommandError(str(exc)) from exc

        self.stdout.write(report.summary())

    def _report_inspection(self, inspection):
        self.stdout.write(
            f'bundle written {inspection["exported_at"]} '
            f'(format version {inspection["format_version"]}), '
            f'mode {inspection["mode"]}',
        )
        for kind in inspection['kinds']:
            self.stdout.write(
                f'  {kind["kind"]}: {kind["in_bundle"]} in bundle, '
                f'{kind["already_here"]} already here → '
                f'{kind["would_create"]} created, {kind["would_update"]} updated',
            )
        if inspection['media_files']:
            self.stdout.write(f'  media files: {inspection["media_files"]}')
        for clash in inspection['slug_collisions']:
            self.stdout.write(
                self.style.WARNING(
                    f'  ! {clash["kind"]} slug {clash["slug"]!r} is held here '
                    f'by {clash["name"]} — sync would refuse; import as a copy.',
                ),
            )
        self.stdout.write('Nothing was written.')
