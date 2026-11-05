# Migration to rename AccessCode -> SubscriptionCode, AccessCodeAcceptance -> SubscriptionCodeAcceptance.
# Removes is_professor and sync_with_dare fields.
# Renames access_code FK to subscription_code on SubscriptionCodeAcceptance.
# Uses db_table to keep the existing database table names.

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('access_codes', '0004_add_limit'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Step 1: Rename the models (keeps existing db tables via Meta.db_table)
        migrations.RenameModel(
            old_name='AccessCode',
            new_name='SubscriptionCode',
        ),
        migrations.RenameModel(
            old_name='AccessCodeAcceptance',
            new_name='SubscriptionCodeAcceptance',
        ),

        # Step 2: Rename the FK on SubscriptionCodeAcceptance from access_code to subscription_code
        migrations.RenameField(
            model_name='subscriptioncodeacceptance',
            old_name='access_code',
            new_name='subscription_code',
        ),

        # Step 3: Remove is_professor field from SubscriptionCode
        migrations.RemoveField(
            model_name='subscriptioncode',
            name='is_professor',
        ),

        # Step 4: Remove sync_with_dare field from SubscriptionCode
        migrations.RemoveField(
            model_name='subscriptioncode',
            name='sync_with_dare',
        ),

        # Step 5: Update related names on SubscriptionCode FKs
        migrations.AlterField(
            model_name='subscriptioncode',
            name='bot_group',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='subscription_codes',
                to='bots.botgroup',
            ),
        ),
        migrations.AlterField(
            model_name='subscriptioncode',
            name='bot',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='subscription_codes',
                to='bots.bot',
            ),
        ),
        migrations.AlterField(
            model_name='subscriptioncode',
            name='created_by',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='created_subscription_codes',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # Step 6: Update related names on SubscriptionCodeAcceptance FKs
        migrations.AlterField(
            model_name='subscriptioncodeacceptance',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='subscription_code_acceptances',
                to=settings.AUTH_USER_MODEL,
            ),
        ),

        # Step 7: Update unique_together for SubscriptionCodeAcceptance
        migrations.AlterUniqueTogether(
            name='subscriptioncodeacceptance',
            unique_together={('subscription_code', 'user')},
        ),

        # Step 8: Update verbose names
        migrations.AlterModelOptions(
            name='subscriptioncode',
            options={
                'ordering': ['-created_at'],
                'verbose_name': 'Subscription Code',
                'verbose_name_plural': 'Subscription Codes',
            },
        ),
        migrations.AlterModelOptions(
            name='subscriptioncodeacceptance',
            options={
                'ordering': ['-created_at'],
                'verbose_name': 'Subscription Code Acceptance',
                'verbose_name_plural': 'Subscription Code Acceptances',
            },
        ),

        # Step 9: Set db_table to keep existing table names
        migrations.AlterModelTable(
            name='subscriptioncode',
            table='access_codes_accesscode',
        ),
        migrations.AlterModelTable(
            name='subscriptioncodeacceptance',
            table='access_codes_accesscodeacceptance',
        ),
    ]
