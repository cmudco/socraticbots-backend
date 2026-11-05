"""
Voice session orchestration.

Owns provider selection, launch eligibility, and provider-neutral conversation
completion so views stay focused on request/response handling.
"""

import logging
from datetime import timedelta

from asgiref.sync import async_to_sync
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from voice.access import (
    CAN_LAUNCH_EXAM,
    STAFF_ACCESS_LEVELS,
    resolve_access,
)
from voice.constants import (
    VOICE_RUNTIME_SESSION_TOKEN_TTL_SECONDS,
    ConversationStatus,
    VoiceAgentStatus,
    VoiceProvider,
)
from voice.dtos import MistralConversationEndedPayload, VoiceSessionStartResponse
from voice.models import VoiceAgent, VoiceAgentAccess, VoiceConversation
from voice.services.elevenlabs_service import ElevenLabsService
from voice.services.providers import get_voice_provider
from voice.services.webhook_service import WebhookService

logger = logging.getLogger(__name__)
STARTUP_LEASE_SECONDS = 90


class VoiceSessionError(Exception):
    """Raised when a voice session cannot be started or completed."""

    def __init__(self, message: str, status_code: int = 400, code: str = 'voice_session_error'):
        self.message = message
        self.status_code = status_code
        self.code = code
        super().__init__(message)


class VoiceSessionService:
    """Provider-neutral service for launching and ending voice sessions."""

    def start_session(self, agent: VoiceAgent, user) -> VoiceSessionStartResponse:
        """Validate launch permissions and return provider-specific session data."""
        provider = get_voice_provider(agent.voice_provider)
        if agent.voice_provider == VoiceProvider.MISTRAL_VOICE:
            with transaction.atomic():
                locked_agent = VoiceAgent.objects.select_for_update().get(pk=agent.pk)
                if getattr(settings, 'VOICE_RUNTIME_STARTUP_CLAIMS_ENABLED', False):
                    self._release_unstarted_reservations(locked_agent, user)
                self._ensure_can_launch(locked_agent, user)
                return provider.start_session(locked_agent, user)

        self._ensure_can_launch(agent, user)
        return provider.start_session(agent, user)

    def record_elevenlabs_start(
        self,
        agent: VoiceAgent,
        user,
        conversation_id: str,
    ) -> VoiceConversation:
        """Record an ElevenLabs conversation after the SDK returns its ID."""
        if VoiceConversation.objects.filter(
            elevenlabs_conversation_id=conversation_id,
        ).exists():
            raise VoiceSessionError("Conversation already recorded")

        return VoiceConversation.objects.create(
            agent=agent,
            user=user,
            elevenlabs_conversation_id=conversation_id,
            provider_conversation_id=conversation_id,
            status=ConversationStatus.IN_PROGRESS,
        )

    def end_elevenlabs_conversation(
        self,
        agent: VoiceAgent,
        user,
        conversation_id: str,
    ) -> VoiceConversation:
        """Fetch and store an ElevenLabs transcript when a browser session ends."""
        try:
            conversation = VoiceConversation.objects.get(
                elevenlabs_conversation_id=conversation_id,
                agent=agent,
                user=user,
            )
        except VoiceConversation.DoesNotExist:
            raise VoiceSessionError("Conversation not found", status_code=404)

        if conversation.status == ConversationStatus.COMPLETED and conversation.transcript:
            return conversation

        try:
            service = ElevenLabsService()
            conv_data = async_to_sync(service.get_conversation)(conversation_id)

            conversation.transcript = conv_data.get('transcript', [])
            conversation.ended_at = timezone.now()
            conversation.duration_seconds = int(
                (conversation.ended_at - conversation.started_at).total_seconds()
            )
            conversation.status = ConversationStatus.COMPLETED
            conversation.save()
            return conversation
        except Exception as exc:
            logger.exception("Failed to fetch ElevenLabs transcript")
            conversation.status = ConversationStatus.FAILED
            conversation.ended_at = timezone.now()
            conversation.save(update_fields=['status', 'ended_at'])
            raise VoiceSessionError(f"Failed to fetch transcript: {exc}", status_code=500)

    @transaction.atomic
    def complete_mistral_conversation(
        self,
        payload: MistralConversationEndedPayload,
    ) -> bool:
        """Apply the Mistral runtime completion callback to the local conversation."""
        try:
            conversation = VoiceConversation.objects.select_for_update(of=('self',)).select_related('agent', 'user').get(
                provider_conversation_id=payload.session_id,
            )
        except VoiceConversation.DoesNotExist:
            logger.error("Mistral voice conversation not found: %s", payload.session_id)
            return False

        receipt = conversation.compliance_receipt or {}
        # Terminal callbacks are idempotent. A replaced startup must never revive.
        if receipt.get('runtimeFinalizedAt') or receipt.get('endedReason') in (
            'startup_replaced', 'reserved_session_expired', 'start_failed',
        ):
            logger.info("Ignored late/duplicate terminal callback for %s", payload.session_id)
            return True

        if payload.status == ConversationStatus.FAILED:
            conversation.status = ConversationStatus.FAILED
        elif payload.status == ConversationStatus.CANCELLED:
            conversation.status = ConversationStatus.CANCELLED
        else:
            conversation.status = ConversationStatus.COMPLETED

        transcript = payload.transcript_as_list()
        if transcript or conversation.status == ConversationStatus.COMPLETED:
            conversation.transcript = transcript
        conversation.ended_at = timezone.now()
        conversation.duration_seconds = payload.duration_seconds or int(
            (conversation.ended_at - conversation.started_at).total_seconds()
        )
        conversation.compliance_receipt = {
            **receipt,
            "conversationId": payload.session_id,
            "provider": VoiceProvider.MISTRAL_VOICE,
            "storedInSbAt": conversation.ended_at.isoformat(),
            "endedReason": payload.ended_reason,
            "metrics": payload.metrics,
            "runtimeFinalizedAt": conversation.ended_at.isoformat(),
        }
        conversation.save()

        if conversation.status == ConversationStatus.COMPLETED:
            # Persist/release the row lock before an optional external upload.
            # A slow DARE upload must not block confirmation of a saved attempt.
            transaction.on_commit(
                lambda: WebhookService().upload_transcript_to_dare(conversation),
                robust=True,
            )

        return True

    @transaction.atomic
    def start_mistral_conversation(self, session_id: str) -> bool:
        """Mark a reserved Mistral runtime session as a started exam attempt."""
        try:
            conversation = VoiceConversation.objects.select_for_update(of=('self',)).select_related('agent').get(
                provider_conversation_id=session_id,
            )
        except VoiceConversation.DoesNotExist:
            logger.error("Mistral voice conversation not found for start: %s", session_id)
            return False

        if conversation.agent.voice_provider != VoiceProvider.MISTRAL_VOICE:
            logger.error("Runtime start callback received for non-Mistral session: %s", session_id)
            return False

        if conversation.status == ConversationStatus.IN_PROGRESS:
            return True

        if conversation.status != ConversationStatus.RESERVED:
            logger.info(
                "Runtime start callback ignored for session %s in status %s",
                session_id,
                conversation.status,
            )
            return False

        now = timezone.now()
        receipt = conversation.compliance_receipt or {}
        claimed_at = parse_datetime(receipt.get('runtimeClaimedAt', ''))
        if claimed_at and claimed_at < now - timedelta(seconds=STARTUP_LEASE_SECONDS):
            logger.info("Expired runtime startup activation rejected for %s", session_id)
            return False
        receipt.update(
            {
                "conversationId": session_id,
                "provider": VoiceProvider.MISTRAL_VOICE,
                "startedAt": now.isoformat(),
            }
        )
        conversation.status = ConversationStatus.IN_PROGRESS
        conversation.started_at = now
        conversation.compliance_receipt = receipt
        conversation.save(update_fields=['status', 'started_at', 'compliance_receipt'])
        return True

    @transaction.atomic
    def cancel_conversation(
        self,
        agent: VoiceAgent,
        user,
        conversation_id: str,
        ended_reason: str = "client_cancelled",
    ) -> VoiceConversation:
        """Cancel an unfinished provider conversation without consuming a completed attempt."""
        try:
            conversation = VoiceConversation.objects.select_for_update().get(
                provider_conversation_id=conversation_id,
                agent=agent,
                user=user,
            )
        except VoiceConversation.DoesNotExist:
            raise VoiceSessionError("Conversation not found", status_code=404)

        receipt = conversation.compliance_receipt or {}
        if (conversation.status == ConversationStatus.CANCELLED
                and receipt.get('endedReason') == 'unknown_disconnect'
                and ended_reason == 'route_change'
                and conversation.ended_at
                and timezone.now() - conversation.ended_at <= timedelta(minutes=1)):
            # An authenticated navigation report can arrive just after transport loss.
            # Preserve the runtime observation and never change the terminal outcome.
            receipt.update(runtimeEndedReason='unknown_disconnect', endedReason='route_change')
            conversation.compliance_receipt = receipt
            conversation.save(update_fields=['compliance_receipt'])
            return conversation
        if conversation.status not in [ConversationStatus.RESERVED, ConversationStatus.IN_PROGRESS]:
            return conversation
        if ended_reason == 'start_failed' and conversation.status == ConversationStatus.IN_PROGRESS:
            # A late browser cleanup must not cancel an already activated call.
            return conversation

        conversation.status = ConversationStatus.CANCELLED
        conversation.ended_at = timezone.now()
        conversation.duration_seconds = int(
            (conversation.ended_at - conversation.started_at).total_seconds()
        )
        receipt = conversation.compliance_receipt or {}
        receipt.update(
            {
                "conversationId": conversation_id,
                "provider": agent.voice_provider,
                "storedInSbAt": conversation.ended_at.isoformat(),
                "endedReason": ended_reason,
            }
        )
        conversation.compliance_receipt = receipt
        conversation.save(
            update_fields=[
                'status',
                'ended_at',
                'duration_seconds',
                'compliance_receipt',
            ]
        )
        return conversation

    def _ensure_can_launch(self, agent: VoiceAgent, user) -> None:
        access = resolve_access(user, agent)
        if not access or access not in CAN_LAUNCH_EXAM:
            raise VoiceSessionError("You do not have permission to launch this exam", 403)

        if agent.status != VoiceAgentStatus.ACTIVE and access not in STAFF_ACCESS_LEVELS:
            raise VoiceSessionError("This agent is not active", 403)

        if access in STAFF_ACCESS_LEVELS:
            return

        self._expire_stale_reserved_sessions(agent, user)
        self._expire_stale_in_progress_attempts(agent, user)

        attempts = VoiceConversation.objects.filter(
            agent=agent,
            user=user,
            is_deleted=False,
            is_active=True,
            status__in=[
                ConversationStatus.RESERVED,
                ConversationStatus.IN_PROGRESS,
                ConversationStatus.COMPLETED,
            ],
        )
        if attempts.filter(status=ConversationStatus.IN_PROGRESS).exists():
            raise VoiceSessionError(
                "An exam session is still active. Return to that session, or retry after it disconnects.",
                409, 'session_active',
            )
        if attempts.filter(status=ConversationStatus.RESERVED).exists():
            raise VoiceSessionError(
                "Your previous connection is still starting. Please wait briefly, then retry.",
                409, 'session_starting',
            )
        attempt_count = attempts.count()

        student_access = VoiceAgentAccess.objects.filter(agent=agent, user=user).first()
        max_attempts = student_access.max_attempts if student_access else 1

        if attempt_count >= max_attempts:
            raise VoiceSessionError(
                "You have reached the maximum number of attempts for this exam.",
                403,
                'attempt_limit_reached',
            )

    def _release_unstarted_reservations(self, agent, user, *, expired_only=False) -> None:
        """Retry replaces only unclaimed or expired startups, never active audio.

        Runtime context claiming and activation lock the same conversation rows.
        Old signed tokens remain cryptographically valid but cannot claim a cancelled row.
        """
        cutoff = timezone.now() - timedelta(seconds=STARTUP_LEASE_SECONDS)
        for conversation in VoiceConversation.objects.select_for_update().filter(
            agent=agent, user=user, status=ConversationStatus.RESERVED,
        ):
            receipt = conversation.compliance_receipt or {}
            if expired_only and conversation.created_at >= cutoff:
                continue
            claimed_at = parse_datetime(receipt.get('runtimeClaimedAt', ''))
            if claimed_at and claimed_at >= cutoff:
                continue
            conversation.status = ConversationStatus.CANCELLED
            conversation.ended_at = timezone.now()
            conversation.duration_seconds = 0
            conversation.compliance_receipt = {
                **receipt, 'endedReason': 'reserved_session_expired' if expired_only else 'startup_replaced',
                'storedInSbAt': conversation.ended_at.isoformat(),
            }
            conversation.save(update_fields=['status', 'ended_at', 'duration_seconds', 'compliance_receipt'])
            logger.info("Released unstarted voice reservation %s", conversation.provider_conversation_id)

    def _expire_stale_reserved_sessions(self, agent: VoiceAgent, user) -> None:
        """Release runtime reservations whose short-lived session token has expired."""
        stale_after = timezone.now() - timedelta(
            seconds=VOICE_RUNTIME_SESSION_TOKEN_TTL_SECONDS + 300,
        )
        stale_conversations = VoiceConversation.objects.filter(
            agent=agent,
            user=user,
            status=ConversationStatus.RESERVED,
            created_at__lt=stale_after,
        )
        for conversation in stale_conversations:
            conversation.status = ConversationStatus.CANCELLED
            conversation.ended_at = timezone.now()
            conversation.duration_seconds = 0
            conversation.compliance_receipt = {
                **(conversation.compliance_receipt or {}),
                "conversationId": conversation.provider_conversation_id
                or conversation.elevenlabs_conversation_id,
                "provider": conversation.agent.voice_provider,
                "storedInSbAt": conversation.ended_at.isoformat(),
                "endedReason": "reserved_session_expired",
            }
            conversation.save(
                update_fields=[
                    'status',
                    'ended_at',
                    'duration_seconds',
                    'compliance_receipt',
                ]
            )

    def _expire_stale_in_progress_attempts(self, agent: VoiceAgent, user) -> None:
        """Release attempts left open by browser crashes, tab closes, or callback failures."""
        stale_after = timezone.now() - timedelta(seconds=agent.max_duration_seconds + 300)
        stale_conversations = VoiceConversation.objects.filter(
            agent=agent,
            user=user,
            status=ConversationStatus.IN_PROGRESS,
            started_at__lt=stale_after,
        )
        for conversation in stale_conversations:
            conversation.status = ConversationStatus.CANCELLED
            conversation.ended_at = timezone.now()
            conversation.duration_seconds = int(
                (conversation.ended_at - conversation.started_at).total_seconds()
            )
            conversation.compliance_receipt = {
                **(conversation.compliance_receipt or {}),
                "conversationId": conversation.provider_conversation_id
                or conversation.elevenlabs_conversation_id,
                "provider": conversation.agent.voice_provider,
                "storedInSbAt": conversation.ended_at.isoformat(),
                "endedReason": "stale_in_progress_expired",
            }
            conversation.save(
                update_fields=[
                    'status',
                    'ended_at',
                    'duration_seconds',
                    'compliance_receipt',
                ]
            )
