from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('voice', '0009_drop_legacy_mistral_voice_instructions'),
    ]

    operations = [
        migrations.AddField(
            model_name='voiceagent',
            name='voice_eagerness',
            field=models.CharField(
                choices=[
                    ('low', 'Low (patient — waits longer before responding)'),
                    ('normal', 'Normal'),
                    ('high', 'High (snappy — jumps in quickly)'),
                ],
                default='normal',
                help_text='How quickly the agent jumps in after the student pauses',
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name='voiceagent',
            name='voice_turn_timeout_secs',
            field=models.PositiveIntegerField(
                default=7,
                help_text='Max silence (seconds) before the agent prompts the student',
                validators=[MinValueValidator(1), MaxValueValidator(60)],
            ),
        ),
    ]
