"""
Management command to update all ElevenLabs agents with the current webhook.

Run this after updating ELEVENLABS_WEBHOOK_ID in .env to link all existing
agents to the new webhook.

Usage:
    python manage.py update_agent_webhooks
    python manage.py update_agent_webhooks --dry-run  # Preview without changes
"""
import logging

from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.management.base import BaseCommand

from voice.models import VoiceAgent
from voice.services.elevenlabs_service import ElevenLabsService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Update all ElevenLabs agents with the current webhook configuration'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview changes without actually updating agents',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        webhook_id = getattr(settings, 'ELEVENLABS_WEBHOOK_ID', '')

        if not webhook_id:
            self.stderr.write(
                self.style.ERROR('ELEVENLABS_WEBHOOK_ID not configured in settings')
            )
            return

        self.stdout.write(f"Webhook ID: {webhook_id}")
        self.stdout.write(f"Dry run: {dry_run}\n")

        # Get all agents with ElevenLabs agent IDs
        agents = VoiceAgent.objects.exclude(
            elevenlabs_agent_id__isnull=True
        ).exclude(
            elevenlabs_agent_id=''
        )

        total = agents.count()
        self.stdout.write(f"Found {total} agents to update\n")

        if total == 0:
            self.stdout.write(self.style.WARNING('No agents found'))
            return

        service = ElevenLabsService()
        updated = 0
        failed = 0

        for agent in agents:
            self.stdout.write(
                f"Processing: {agent.name} (ID: {agent.id}, "
                f"ElevenLabs: {agent.elevenlabs_agent_id})"
            )

            if dry_run:
                self.stdout.write(self.style.SUCCESS('  [DRY RUN] Would update'))
                updated += 1
                continue

            try:
                async_to_sync(service.link_webhook_to_agent)(
                    agent.elevenlabs_agent_id,
                    webhook_id
                )
                self.stdout.write(self.style.SUCCESS('  Updated successfully'))
                updated += 1
            except Exception as e:
                self.stderr.write(self.style.ERROR(f'  Failed: {e}'))
                failed += 1

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'Updated: {updated}'))
        if failed:
            self.stdout.write(self.style.ERROR(f'Failed: {failed}'))
        self.stdout.write(f'Total: {total}')
