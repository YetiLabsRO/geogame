"""Drop the deprecated Team.code column (Phase 2 team_code retirement).

The team_code join flow was retired at Phase 2 launch (P2D.4 / Req 13.2)
and has been inert since. T3.11 removes the column from the schema.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('organize', '0008_teammembership_game'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='team',
            name='code',
        ),
    ]
