from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bots", "0014_remove_billing_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="bot",
            name="budget",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text=(
                    "Hard ceiling for anonymous public deployment spend on this "
                    "bot (in USD). Required when is_publicly_deployed=True."
                ),
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="bot",
            name="budget_used",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text=(
                    "Cumulative anonymous public deployment spend attributed to "
                    "this bot (in USD)."
                ),
                max_digits=10,
            ),
        ),
    ]
