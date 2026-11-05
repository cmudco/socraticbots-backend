"""
Remove the per-bot billing fields.

Spend caps are redundant now that deployment-level budget limits are the
source of truth, and the per-bot ``billing_source`` enum has been replaced
by a simple rule: the chatter pays; if the bot is publicly deployed and
the chatter is anonymous, the bot owner pays. That rule is applied on the
DARE side using ``ownerId`` + ``isPubliclyDeployed`` from
``get_bot_billing_config``.

Drops ``budget``, ``budget_used``, ``billing_source``, and
``billing_target_id`` from the ``Bot`` model.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("bots", "0013_picker_model_ids"),
    ]

    operations = [
        migrations.RemoveField(model_name="bot", name="billing_source"),
        migrations.RemoveField(model_name="bot", name="billing_target_id"),
        migrations.RemoveField(model_name="bot", name="budget"),
        migrations.RemoveField(model_name="bot", name="budget_used"),
    ]
