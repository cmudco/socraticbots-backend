# ElevenLabs is retired from the provider picker. Mistral Voice becomes
# the default, and any existing ElevenLabs agents are moved over so no
# agent is left on a runtime the UI can no longer select.

from django.db import migrations, models


def elevenlabs_to_mistral(apps, schema_editor):
    VoiceAgent = apps.get_model('voice', 'VoiceAgent')
    VoiceAgent.objects.filter(voice_provider='elevenlabs').update(
        voice_provider='mistral_pipecat'
    )


def noop_reverse(apps, schema_editor):
    # Irreversible: original provider assignments are not recorded.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('voice', '0012_voiceagent_default_max_attempts'),
    ]

    operations = [
        migrations.RunPython(elevenlabs_to_mistral, noop_reverse),
        migrations.AlterField(
            model_name='voiceagent',
            name='voice_provider',
            field=models.CharField(
                choices=[
                    ('elevenlabs', 'ElevenLabs'),
                    ('mistral_pipecat', 'Mistral Voice'),
                ],
                default='mistral_pipecat',
                help_text='Voice runtime/provider for this agent',
                max_length=30,
            ),
        ),
    ]
