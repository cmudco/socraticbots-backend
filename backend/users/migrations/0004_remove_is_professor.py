# Remove is_professor field from CustomUser.
# Role is now sourced from DARE JWT token (platform_role claim).
#
# IMPORTANT: This migration MUST run after 0003_migrate_professors_to_dare,
# which propagates is_professor=True data to DARE before this column is dropped.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_migrate_professors_to_dare'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='customuser',
            name='is_professor',
        ),
    ]
