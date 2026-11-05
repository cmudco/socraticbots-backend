"""
Webhook Processing Service.

Handles ElevenLabs webhook events with business logic separated from views.
Includes transcript PDF generation and upload to DARE.
"""
import hashlib
import hmac
import logging
import os
import tempfile
from typing import Optional

import weasyprint
from asgiref.sync import async_to_sync
from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from utils.dare_api.files import DareFilesClient, DareApiError
from utils.helpers import slugify, get_user_display_name
from voice.constants import ConversationStatus
from voice.dtos import ElevenLabsWebhookPayload
from voice.models import VoiceConversation
from voice.services.elevenlabs_service import ElevenLabsService

logger = logging.getLogger(__name__)


class WebhookService:
    """
    Service for processing ElevenLabs webhooks.

    Handles signature verification, transcript storage, and cleanup.
    """

    def __init__(self, webhook_secret: Optional[str] = None):
        """
        Initialize webhook service.

        Args:
            webhook_secret: HMAC secret for signature verification.
                           Falls back to settings if not provided.
        """
        self.webhook_secret = webhook_secret or getattr(
            settings,
            'ELEVENLABS_WEBHOOK_SECRET',
            ''
        )
        self._elevenlabs_service: Optional[ElevenLabsService] = None

    @property
    def elevenlabs_service(self) -> ElevenLabsService:
        """Lazy-load ElevenLabs service."""
        if self._elevenlabs_service is None:
            self._elevenlabs_service = ElevenLabsService()
        return self._elevenlabs_service

    # ============================================================================
    # Signature Verification
    # ============================================================================

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify HMAC-SHA256 signature from ElevenLabs.

        ElevenLabs signature format: "t=<timestamp>,v0=<signature>"
        The signature is computed as: HMAC-SHA256(secret, "<timestamp>.<payload>")

        Args:
            payload: Raw request body bytes
            signature: ElevenLabs-Signature header value

        Returns:
            True if signature is valid
        """
        if not self.webhook_secret:
            logger.error("Webhook secret not configured; webhook rejected")
            return False

        # Parse signature header: "t=1234567890,v0=abc123..."
        parts = {}
        for part in signature.split(','):
            if '=' in part:
                key, value = part.split('=', 1)
                parts[key] = value

        timestamp = parts.get('t', '')
        received_sig = parts.get('v0', '')

        if not timestamp or not received_sig:
            logger.info("Invalid webhook signature format")
            return False

        # Compute expected signature: HMAC-SHA256(secret, "timestamp.payload")
        signed_payload = f"{timestamp}.".encode('utf-8') + payload
        expected_signature = hmac.new(
            self.webhook_secret.encode('utf-8'),
            signed_payload,
            hashlib.sha256
        ).hexdigest()


        return hmac.compare_digest(expected_signature, received_sig)

    # ============================================================================
    # Webhook Processing
    # ============================================================================

    def process_conversation_end(self, payload: ElevenLabsWebhookPayload) -> bool:
        """
        Process conversation end webhook.

        1. Find conversation in database
        2. Save transcript locally
        3. Upload transcript PDF to DARE (against agent creator)
        4. Delete from ElevenLabs (privacy)

        Args:
            payload: Parsed webhook payload DTO

        Returns:
            True if processed successfully, False if conversation not found
        """
        logger.info(f"Processing webhook for conversation: {payload.conversation_id}")

        try:
            conversation = VoiceConversation.objects.get(
                elevenlabs_conversation_id=payload.conversation_id
            )
        except VoiceConversation.DoesNotExist:
            logger.exception("Webhook conversation not found: %s", payload.conversation_id)
            return False

        # Save transcript locally
        self._update_conversation(conversation, payload)

        # Upload transcript PDF to DARE (non-blocking - don't fail webhook if this fails)
        self.upload_transcript_to_dare(conversation)

        # Delete from ElevenLabs after successful save and record compliance
        self._cleanup_elevenlabs(conversation, payload.conversation_id)

        return True

    def _update_conversation(
        self,
        conversation: VoiceConversation,
        payload: ElevenLabsWebhookPayload
    ) -> None:
        """
        Update conversation with transcript and completion status.

        Args:
            conversation: VoiceConversation model instance
            payload: Webhook payload with transcript data
        """
        conversation.transcript = payload.transcript_as_list()
        conversation.status = ConversationStatus.COMPLETED
        conversation.ended_at = timezone.now()

        if conversation.started_at:
            conversation.duration_seconds = int(
                (conversation.ended_at - conversation.started_at).total_seconds()
            )

        conversation.save()
        logger.info(
            f"Saved transcript for {payload.conversation_id}: "
            f"{len(payload.transcript)} messages"
        )

    def _cleanup_elevenlabs(self, conversation: VoiceConversation, conversation_id: str) -> None:
        """
        Delete conversation from ElevenLabs servers and record FERPA compliance.

        Logs errors but doesn't raise - transcript is already saved.

        Args:
            conversation: VoiceConversation model instance
            conversation_id: ElevenLabs conversation ID
        """
        try:
            async_to_sync(self.elevenlabs_service.delete_conversation)(conversation_id)
            deleted_at = timezone.now()
            conversation.elevenlabs_deleted_at = deleted_at
            conversation.compliance_receipt = {
                'conversationId': conversation_id,
                'storedInSbAt': conversation.ended_at.isoformat() if conversation.ended_at else None,
                'deletedFromElevenLabs': True,
                'deletedFromElevenLabsAt': deleted_at.isoformat(),
            }
            conversation.save(update_fields=['elevenlabs_deleted_at', 'compliance_receipt'])
            logger.info(f"Deleted conversation {conversation_id} from ElevenLabs (FERPA compliance recorded)")
        except Exception as e:
            logger.error(f"Failed to delete from ElevenLabs: {e}")

    # ============================================================================
    # DARE Transcript Upload
    # ============================================================================

    def upload_transcript_to_dare(self, conversation: VoiceConversation) -> None:
        """
        Generate transcript PDF and upload to DARE.

        Uploads against the voice agent creator (external_user_id).
        Logs errors but doesn't raise - transcript is already saved locally.

        Args:
            conversation: VoiceConversation with transcript data
        """
        try:
            # Get agent creator's DARE user ID
            agent = conversation.agent
            if not agent or not agent.user:
                logger.error(
                    f"Cannot upload transcript: no agent/user for conversation {conversation.id}"
                )
                return

            dare_user_id = agent.user.external_user_id
            if not dare_user_id:
                logger.info(
                    f"Cannot upload transcript: user {agent.user.id} has no external_user_id"
                )
                return

            # Generate PDF
            pdf_content, filename = self._generate_transcript_pdf(conversation)

            # Upload to DARE with "Exam Transcript" tag for filtering
            client = DareFilesClient()
            result = client.upload_file_internal(
                user_id=dare_user_id,
                file_content=pdf_content,
                filename=filename,
                content_type='application/pdf',
                tag_labels=['Exam Transcript']
            )
            logger.info(
                f"Uploaded transcript to DARE for user {dare_user_id}: {filename}"
            )

        except DareApiError as e:
            logger.error(f"Failed to upload transcript to DARE: {e}")
        except Exception as e:
            logger.error(f"Unexpected error uploading transcript to DARE: {e}")

    def _generate_transcript_pdf(
        self,
        conversation: VoiceConversation
    ) -> tuple[bytes, str]:
        """
        Generate PDF from conversation transcript.

        Args:
            conversation: VoiceConversation with transcript data

        Returns:
            Tuple of (pdf_bytes, filename)
        """
        # Format duration
        duration = '-'
        if conversation.duration_seconds:
            mins = conversation.duration_seconds // 60
            secs = conversation.duration_seconds % 60
            duration = f'{mins}m {secs}s'

        # Format transcript messages with time
        transcript = conversation.transcript or []
        for message in transcript:
            time_secs = message.get('timeInCallSecs', message.get('time_in_call_secs', 0))
            mins = int(time_secs // 60)
            secs = int(time_secs % 60)
            message['time_formatted'] = f'{mins}:{secs:02d}'

        # Prepare context
        context = {
            'agent_name': conversation.agent.name,
            'student_name': get_user_display_name(conversation.user),
            'status': conversation.status,
            'duration': duration,
            'started_at': conversation.started_at,
            'ended_at': conversation.ended_at,
            'transcript': transcript,
            'generated_at': timezone.now(),
        }

        # Render HTML template
        html_content = render_to_string('voice/transcript_export.html', context)

        # Generate PDF
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            weasyprint.HTML(string=html_content).write_pdf(tmp_file.name)

            with open(tmp_file.name, 'rb') as pdf_file:
                pdf_content = pdf_file.read()

            os.unlink(tmp_file.name)

        # Generate filename with student name
        agent_slug = slugify(conversation.agent.name)
        student_slug = slugify(get_user_display_name(conversation.user))
        stamp = conversation.started_at.strftime('%Y-%m-%d-%H%M%S') if conversation.started_at else 'unknown'
        filename = f'transcript-{agent_slug}-{student_slug}-{stamp}.pdf'

        return pdf_content, filename
