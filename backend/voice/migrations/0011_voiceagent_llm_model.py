from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('voice', '0010_voiceagent_mistral_advanced_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='voiceagent',
            name='llm_model',
            field=models.CharField(
                blank=True,
                default='gemini-3.1-flash-lite',
                help_text='Brain model id (see VOICE_BRAIN_MODELS)',
                max_length=100,
            ),
        ),
    ]
