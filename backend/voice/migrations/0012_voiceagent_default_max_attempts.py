from django.core.validators import MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('voice', '0011_voiceagent_llm_model'),
    ]

    operations = [
        migrations.AddField(
            model_name='voiceagent',
            name='default_max_attempts',
            field=models.PositiveIntegerField(
                default=1,
                help_text=(
                    'Maximum attempts assigned to students when they first unlock this agent'
                ),
                validators=[MinValueValidator(1)],
            ),
        ),
        migrations.AlterField(
            model_name='voiceagentaccess',
            name='max_attempts',
            field=models.PositiveIntegerField(
                default=1,
                help_text='Maximum number of attempts allowed for this student',
                validators=[MinValueValidator(1)],
            ),
        ),
    ]
