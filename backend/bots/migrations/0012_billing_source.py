"""
Bot billing source + target_id.

Adds the configurable billing-source enum to ``Bot`` so a professor can pick
who pays for LLM calls on the bot:

- ``OWNER_WALLET`` (default) — debit the bot creator's DARE wallet
- ``GROUP_WALLET`` — debit the AccessCodeGroup's GroupWallet (institutional)
- ``USER_WALLET`` — debit the calling student's wallet (rare, opt-in)
- ``LITELLM_KEY`` — route through a LiteLLMKey, no DARE wallet impact

``billing_target_id`` holds the access_code string (GROUP_WALLET) or the
LiteLLMKey UUID (LITELLM_KEY); null otherwise.

Existing bots backfill to ``OWNER_WALLET`` to preserve current behavior; this
matches what the new DARE wallet router will resolve for them by default.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bots", "0011_add_bot_quick_prompt"),
    ]

    operations = [
        migrations.AddField(
            model_name="bot",
            name="billing_source",
            field=models.CharField(
                choices=[
                    ("OWNER_WALLET", "Owner's DARE Wallet"),
                    ("GROUP_WALLET", "Access-Code Group Wallet"),
                    ("USER_WALLET", "Calling User's Wallet"),
                    ("LITELLM_KEY", "LiteLLM Proxy Key"),
                ],
                default="OWNER_WALLET",
                help_text=(
                    "Who pays for LLM calls on this bot. OWNER_WALLET is the "
                    "default and the only choice valid for public bots. "
                    "GROUP_WALLET / LITELLM_KEY require billing_target_id."
                ),
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="bot",
            name="billing_target_id",
            field=models.CharField(
                blank=True,
                help_text=(
                    "When billing_source=GROUP_WALLET, the AccessCodeGroup "
                    "access_code string. When billing_source=LITELLM_KEY, the "
                    "LiteLLMKey UUID. Null for OWNER_WALLET / USER_WALLET."
                ),
                max_length=255,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="bot",
            name="budget",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text=(
                    "Hard ceiling for total LLM spend on this bot (in USD). "
                    "Required when is_publicly_deployed=True. Once budget_used "
                    "reaches this number, calls return HTTP 402 "
                    "BOT_CAP_REACHED. Independent of who actually pays — "
                    "that's billing_source."
                ),
                max_digits=10,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="bot",
            name="budget_used",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text=(
                    "Cumulative LLM spend attributed to this bot (in USD). "
                    "Updated atomically via F() expression by the DARE "
                    "billing finalizer. Reset only by raising the cap; "
                    "cycles are not supported."
                ),
                max_digits=10,
            ),
        ),
    ]
