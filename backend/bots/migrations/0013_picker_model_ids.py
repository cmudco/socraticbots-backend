"""
Widen ``BotModelPreference.chat_model_dare_id`` and ``tracking_model_dare_id``
from IntegerField to CharField so they can hold either:

* a stringified DARE LLM PK ("42"), or
* a LiteLLM-routed picker handle ("litellm:<key_pk>:<model_name>").

Mirrors the DARE FE's ``LLMModel`` (id: number) vs ``PickerModel`` (id: str)
distinction — pickers and dispatch use the opaque string form, DB lookups
use the integer PK. SB only ever needs the picker form, so we just store
the string verbatim and let DARE's ``parse_model_id`` decode it on dispatch.

PostgreSQL can ALTER an integer column to varchar in-place via ``USING``,
so this is a single SQL statement per column with no Python pass.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('bots', '0012_billing_source'),
    ]

    operations = [
        migrations.AlterField(
            model_name='botmodelpreference',
            name='chat_model_dare_id',
            field=models.CharField(
                max_length=255,
                null=True,
                blank=True,
                help_text="Opaque DARE model id (LLM PK or 'litellm:<key>:<name>')",
            ),
        ),
        migrations.AlterField(
            model_name='botmodelpreference',
            name='tracking_model_dare_id',
            field=models.CharField(
                max_length=255,
                null=True,
                blank=True,
                help_text="Opaque DARE model id (LLM PK or 'litellm:<key>:<name>')",
            ),
        ),
    ]
