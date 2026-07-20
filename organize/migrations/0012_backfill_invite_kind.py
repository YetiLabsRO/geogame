# Backfill Invite.kind: email-targeted invites become recipient-bound
# LINKs; the rest keep the QR default (today's shareable QR image).

from django.db import migrations


def forwards(apps, schema_editor):
    Invite = apps.get_model('organize', 'Invite')
    Invite.objects.exclude(email__isnull=True).exclude(email='').update(kind='LINK')


def backwards(apps, schema_editor):
    Invite = apps.get_model('organize', 'Invite')
    Invite.objects.update(kind='QR')


class Migration(migrations.Migration):

    dependencies = [
        ('organize', '0011_player_team_formation'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
