# Adds the full-duplex Pipecat runtime as a side-by-side provider choice.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('voice', '0005_mistral_pipecat_provider'),
    ]

    operations = [
        migrations.AlterField(
            model_name='voiceagent',
            name='voice_provider',
            field=models.CharField(
                choices=[
                    ('elevenlabs', 'ElevenLabs'),
                    ('mistral_pipecat', 'Mistral Voice'),
                    ('mistral_pipecat_rt', 'Mistral Voice (Realtime)'),
                ],
                default='elevenlabs',
                help_text='Voice runtime/provider for this agent',
                max_length=30,
            ),
        ),
    ]
