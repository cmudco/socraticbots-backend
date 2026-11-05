"""Run every minute after the coordinated startup-claim rollout is enabled."""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from voice.constants import ConversationStatus, VoiceProvider
from voice.models import VoiceAgent, VoiceConversation
from voice.services.session_service import STARTUP_LEASE_SECONDS, VoiceSessionService


class Command(BaseCommand):
    help = 'Expire abandoned voice startup leases; never touches active exams.'

    def handle(self, **options):
        if not settings.VOICE_RUNTIME_STARTUP_CLAIMS_ENABLED:
            raise CommandError('Enable startup claims only after backend/runtime rollout is verified.')
        pairs = VoiceConversation.objects.filter(
            status=ConversationStatus.RESERVED, agent__voice_provider=VoiceProvider.MISTRAL_VOICE,
            created_at__lt=timezone.now() - timedelta(seconds=STARTUP_LEASE_SECONDS),
        ).values_list('agent_id', 'user_id').distinct()
        for agent_id, user_id in pairs.iterator():
            with transaction.atomic():
                agent = VoiceAgent.objects.select_for_update().get(pk=agent_id)
                user = get_user_model().objects.get(pk=user_id)
                VoiceSessionService()._release_unstarted_reservations(agent, user, expired_only=True)
        self.stdout.write('Expired startup leases reconciled.')
