from django.db import migrations


LEGACY_COLUMN = "mistral_voice_instructions"
TABLE_NAME = "voice_voiceagent"


def drop_legacy_mistral_voice_instructions(apps, schema_editor):
    """Remove a legacy DB-only column left by older local Mistral experiments."""
    existing_columns = {
        column.name
        for column in schema_editor.connection.introspection.get_table_description(
            schema_editor.connection.cursor(),
            TABLE_NAME,
        )
    }
    if LEGACY_COLUMN not in existing_columns:
        return

    schema_editor.execute(f'ALTER TABLE "{TABLE_NAME}" DROP COLUMN "{LEGACY_COLUMN}"')


class Migration(migrations.Migration):
    dependencies = [
        ("voice", "0008_voiceconversation_reserved_status"),
    ]

    operations = [
        migrations.RunPython(
            drop_legacy_mistral_voice_instructions,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
