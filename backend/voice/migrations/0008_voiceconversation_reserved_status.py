from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('voice', '0007_collapse_mistral_voice_provider'),
    ]

    operations = [
        migrations.AlterField(
            model_name='voiceconversation',
            name='status',
            field=models.CharField(
                choices=[
                    ('reserved', 'Reserved'),
                    ('in_progress', 'In Progress'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                    ('cancelled', 'Cancelled'),
                ],
                default='in_progress',
                max_length=20,
            ),
        ),
    ]
