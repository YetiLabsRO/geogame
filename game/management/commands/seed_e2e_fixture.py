"""Seed a deterministic fixture for Playwright E2E tests.

Idempotent: safe to rerun. Wipes prior e2e state (identified by the
`__e2e__` marker fields on names/slugs/codes) and reseeds from scratch.

Prints a single JSON manifest to stdout so Playwright's globalSetup can
pick up the staff credentials, invite URL, and tower id.
"""

import json
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point, Polygon
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from game.models import Challenge, Tower, Zone
from organize.models import Game, Invite, Team, TeamGroup

User = get_user_model()

MARKER = 'e2e'


class Command(BaseCommand):
    help = 'Seed deterministic fixtures for Playwright E2E tests.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--base-url',
            default='http://localhost:4200',
            help='Base URL the invite link should point at.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        base_url = options['base_url']

        # ---- Wipe previous e2e state -------------------------------------
        Invite.objects.filter(team__name__startswith=MARKER).delete()
        Challenge.objects.filter(text__startswith=MARKER).delete()
        Tower.objects.filter(name__startswith=MARKER).delete()
        Zone.objects.filter(name__startswith=MARKER).delete()
        Team.objects.filter(name__startswith=MARKER).delete()
        TeamGroup.objects.filter(slug__startswith=MARKER).delete()
        Game.objects.filter(name__startswith=MARKER).delete()
        User.objects.filter(username__startswith=MARKER).delete()

        # ---- Game / group / team -----------------------------------------
        now = timezone.now()
        game = Game.objects.create(
            name=f'{MARKER}-game',
            is_active=True,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=4),
            base_point=Point(23.571797, 46.068374),
            base_zoom_level=17,
        )
        group = TeamGroup.objects.create(
            name=f'{MARKER} Explorers', game=game, slug=f'{MARKER}-explo',
        )
        team = Team.objects.create(
            name=f'{MARKER} team alpha',
            game=game,
            code=f'{MARKER[:4].upper()}A1',
            group=group,
            color='#ff3366',
        )

        # ---- Zone / tower / challenge ------------------------------------
        zone = Zone.objects.create(
            name=f'{MARKER}-zone',
            game=game,
            color='#224466',
            scoring_type=Zone.SCORE_LIN,
            shape=Polygon.from_bbox((23.5, 46.0, 23.7, 46.15)),
        )
        tower = Tower.objects.create(
            name=f'{MARKER}-tower-alpha',
            game=game,
            zone=zone,
            location=Point(23.571797, 46.068374),
            is_active=True,
            category=Tower.CATEGORY_NORMAL,
            initial_bonus=10,
        )
        Challenge.objects.create(
            text=f'{MARKER} challenge text — do a thing at the tower',
            tower=tower,
            difficulty=1,
        )

        # ---- Staff + player user scaffolding -----------------------------
        staff_password = 'e2e-staff-pass'
        staff = User.objects.create_user(
            username=f'{MARKER}-staff',
            email=f'{MARKER}-staff@example.com',
            password=staff_password,
            is_staff=True,
        )
        staff_token = Token.objects.create(user=staff)

        # ---- Invite for the player journey -------------------------------
        invite = Invite.objects.create(
            team=team,
            email=f'{MARKER}-player@example.com',
            created_by=staff,
        )
        invite_url = f'{base_url}/invite/{invite.token}'

        # ---- Manifest for Playwright globalSetup -------------------------
        manifest = {
            'base_url': base_url,
            'game_id': game.id,
            'team_id': team.id,
            'team_name': team.name,
            'group_slug': group.slug,
            'tower_id': tower.id,
            'tower_name': tower.name,
            'staff': {
                'username': staff.username,
                'password': staff_password,
                'token': staff_token.key,
            },
            'invite': {
                'id': invite.id,
                'token': str(invite.token),
                'url': invite_url,
            },
            'player': {
                # Suggested; tests generate these fresh to exercise the
                # unauthenticated accept flow too.
                'username': f'{MARKER}-player-{uuid.uuid4().hex[:6]}',
                'email': f'{MARKER}-player-{uuid.uuid4().hex[:6]}@example.com',
                'password': 'e2e-player-pass',
            },
        }
        self.stdout.write(json.dumps(manifest))
