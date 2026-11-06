"""Internal callbacks from the Mistral voice runtime."""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    renderer_classes,
)
from rest_framework.permissions import AllowAny
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from voice.api.serializers import (
    MistralConversationEndedSerializer,
    MistralConversationStartedSerializer,
)
from voice.models import VoiceConversation
from voice.constants import ConversationStatus
from voice.services.session_service import VoiceSessionService

logger = logging.getLogger(__name__)


def _has_valid_runtime_key(request) -> bool:
    expected_key = getattr(settings, 'DARE_INTERNAL_KEY', '')
    received_key = request.headers.get('X-Internal-Key', '')
    return bool(expected_key and received_key == expected_key)


def _reject_invalid_runtime_key() -> Response:
    logger.info("Invalid voice runtime callback internal key")
    return Response(
        {"error": "Invalid internal key"},
        status=status.HTTP_401_UNAUTHORIZED,
    )


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def voice_runtime_conversation_started(request) -> Response:
    """Mark a reserved Mistral session as an active exam attempt."""
    if not _has_valid_runtime_key(request):
        return _reject_invalid_runtime_key()

    serializer = MistralConversationStartedSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    processed = VoiceSessionService().start_mistral_conversation(
        serializer.validated_data['session_id'],
    )
    if not processed:
        return Response(
            {"error": "Conversation not found or not startable"},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response({"status": "ok"})


@api_view(['POST'])
@authentication_classes([])
@permission_classes([AllowAny])
def voice_runtime_conversation_ended(request) -> Response:
    """Receive a completed Mistral voice conversation transcript."""
    if not _has_valid_runtime_key(request):
        return _reject_invalid_runtime_key()

    try:
        serializer = MistralConversationEndedSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        payload = serializer.to_dto()

        processed = VoiceSessionService().complete_mistral_conversation(payload)
        if not processed:
            return Response(
                {"error": "Conversation not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        return Response({"status": "ok"})
    except Exception as exc:
        logger.exception("Voice runtime callback processing error")
        return Response(
            {"error": str(exc)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(['GET', 'POST'])
@authentication_classes([])
@permission_classes([AllowAny])
# Server-to-server endpoint — bypass the project-wide camelCase renderer
# so the runtime can read the snake_case keys it expects.
@renderer_classes([JSONRenderer])
@transaction.atomic
def voice_runtime_session_context(request, session_id: str) -> Response:
    """Rich per-session config fetched server-to-server by the runtime.

    The runtime calls this immediately after a browser session opens, so
    the signed session token only needs to carry tiny auth claims (the
    full agent prompt would otherwise blow past URL/header limits).
    Authenticated with the same X-Internal-Key as the other runtime
    callbacks.
    """
    if not _has_valid_runtime_key(request):
        return _reject_invalid_runtime_key()

    try:
        conversation = VoiceConversation.objects.select_for_update(of=('self',)).select_related('agent').get(
            provider_conversation_id=session_id,
        )
    except VoiceConversation.DoesNotExist:
        return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)

    agent = conversation.agent
    if settings.VOICE_RUNTIME_STARTUP_CLAIMS_ENABLED and request.method != 'POST':
        return Response({'error': 'Runtime must claim startup using POST'}, status=409)
    if conversation.status != ConversationStatus.RESERVED:
        return Response({'error': 'Session is no longer startable'}, status=409)
    if request.method == 'POST':
        receipt = conversation.compliance_receipt or {}
        if receipt.get('runtimeClaimedAt'):
            return Response({'error': 'Session startup is already claimed'}, status=409)
        receipt['runtimeClaimedAt'] = timezone.now().isoformat()
        conversation.compliance_receipt = receipt
        conversation.save(update_fields=['compliance_receipt'])
    return Response({
        "first_message": agent.first_message or "",
        "system_prompt": agent.system_prompt or "",
        "exam_instructions": agent.exam_instructions or "",
        "temperature": agent.temperature,
        "language": agent.language or "en",
        "voice_id": agent.voice_id or "",
        "eagerness": agent.voice_eagerness,
        "turn_mode": agent.voice_turn_mode,
        "turn_timeout_secs": agent.voice_turn_timeout_secs,
        "llm_model": agent.llm_model or "",
    })
