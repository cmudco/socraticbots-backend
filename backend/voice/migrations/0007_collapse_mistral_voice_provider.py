# Collapses the realtime Pipecat provider into the single Mistral Voice
# provider. The legacy turn-based runtime is removed; `mistral_pipecat`
# now always means the full-duplex Pipecat runtime. Any existing agents
# on `mistral_pipecat_rt` are migrated to `mistral_pipecat`.

from django.db import migrations, models


def collapse_rt_to_mistral(apps, schema_editor):
    VoiceAgent = apps.get_model('voice', 'VoiceAgent')
    VoiceAgent.objects.filter(voice_provider='mistral_pipecat_rt').update(
        voice_provider='mistral_pipecat'
    )


def noop_reverse(apps, schema_editor):
    # Irreversible by design: the two providers are now one.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('voice', '0006_voiceagent_mistral_pipecat_rt_provider'),
    ]

    operations = [
        migrations.RunPython(collapse_rt_to_mistral, noop_reverse),
        migrations.AlterField(
            model_name='voiceagent',
            name='voice_provider',
            field=models.CharField(
                choices=[
                    ('elevenlabs', 'ElevenLabs'),
                    ('mistral_pipecat', 'Mistral Voice'),
                ],
                default='elevenlabs',
                help_text='Voice runtime/provider for this agent',
                max_length=30,
            ),
        ),
    ]
