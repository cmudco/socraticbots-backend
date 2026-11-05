"""STT Lab session endpoint.

Mints a short-lived lab-mode token for the standalone voice runtime. A lab
session is the isolated mic → Voxtral test bench (no agent, no exam, no
conversation record): the runtime sees ``mode="lab"`` in the token and runs
its lab pipeline, mirroring transcripts, audio levels, VAD activity, STT
socket lifecycle, and every error back to the browser so transcription
quality can be debugged with all other variables removed.
"""

import logging
import uuid
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from voice.constants import VOICE_RUNTIME_SESSION_TOKEN_TTL_SECONDS, VoiceProvider
from voice.dtos import VoiceSessionStartResponse
from voice.services.providers import (
    build_runtime_webrtc_url,
    sign_runtime_session_token,
)
from django.conf import settings

logger = logging.getLogger(__name__)

# Lab sessions have no VoiceAgent; the runtime ignores the agent claim in
# lab mode but the token schema requires an integer.
LAB_AGENT_ID = 0


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_stt_lab_session(request):
    """Start an isolated STT Lab session against the voice runtime."""
    session_id = uuid.uuid4().hex
    expires_at = timezone.now() + timedelta(
        seconds=VOICE_RUNTIME_SESSION_TOKEN_TTL_SECONDS
    )
    try:
        token = sign_runtime_session_token(
            session_id=session_id,
            agent_id=LAB_AGENT_ID,
            user_id=request.user.id,
            expires_at=expires_at,
            mode="lab",
        )
        webrtc_url = build_runtime_webrtc_url(session_id)
    except ValueError as exc:
        logger.error("STT Lab session could not be created: %s", exc)
        return Response(
            {"error": str(exc)},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    logger.info(
        "STT Lab session %s minted for user %s", session_id, request.user.id
    )
    return Response(
        VoiceSessionStartResponse(
            provider=VoiceProvider.MISTRAL_VOICE,
            session_id=session_id,
            webrtc_url=webrtc_url,
            ice_servers=getattr(settings, 'VOICE_RUNTIME_ICE_SERVERS', []),
            token=token,
            expires_at=expires_at.isoformat(),
        ).to_response_data()
    )
