from django.conf import settings
from django.db import migrations


def create_missing_profiles(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    UserProfile = apps.get_model('organize', 'UserProfile')
    for user in User.objects.filter(profile__isnull=True):
        UserProfile.objects.create(user=user)


class Migration(migrations.Migration):

    dependencies = [
        ('organize', '0002_accounts_invites'),
    ]

    operations = [
        migrations.RunPython(create_missing_profiles, reverse_code=migrations.RunPython.noop),
    ]
