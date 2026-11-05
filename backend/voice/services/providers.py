"""
Voice provider implementations.

Keeps external provider details out of DRF views so the voice app can run
ElevenLabs and Mistral Voice agents side by side during rollout.
"""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Optional

from asgiref.sync import async_to_sync
from django.conf import settings
from django.utils import timezone

from voice.constants import (
    ConversationStatus,
    VOICE_RUNTIME_SESSION_TOKEN_TTL_SECONDS,
    VoiceProvider,
    build_elevenlabs_agent_name,
)
from voice.dtos import VoiceAgentProviderConfig, VoiceSessionStartResponse
from voice.models import VoiceAgent, VoiceConversation
from voice.services.elevenlabs_service import ElevenLabsService

logger = logging.getLogger(__name__)


class BaseVoiceProvider(ABC):
    """Abstract interface for voice providers."""

    provider_name: str

    @abstractmethod
    def create_agent(self, agent: VoiceAgent) -> None:
        """Create or provision the provider-side agent."""

    @abstractmethod
    def update_agent(self, agent: VoiceAgent) -> None:
        """Update the provider-side agent."""

    @abstractmethod
    def delete_agent(self, agent: VoiceAgent) -> None:
        """Delete the provider-side agent."""

    @abstractmethod
    def start_session(self, agent: VoiceAgent, user) -> VoiceSessionStartResponse:
        """Create a provider session for browser voice transport."""

    def build_config(self, agent: VoiceAgent) -> VoiceAgentProviderConfig:
        """Build a provider-neutral config DTO from the model."""
        return VoiceAgentProviderConfig(
            name=agent.name,
            system_prompt=agent.system_prompt,
            first_message=agent.first_message or agent.exam_instructions,
            voice_id=agent.voice_id,
            temperature=agent.temperature,
            max_duration_seconds=agent.max_duration_seconds,
            language=agent.language,
            conversation_config=agent.conversation_config or {},
        )


class ElevenLabsVoiceProvider(BaseVoiceProvider):
    """ElevenLabs Conversational AI provider wrapper."""

    provider_name = VoiceProvider.ELEVENLABS

    def __init__(self, service: Optional[ElevenLabsService] = None):
        self.service = service or ElevenLabsService()

    def create_agent(self, agent: VoiceAgent) -> None:
        config = self._build_elevenlabs_config(agent)
        result = async_to_sync(self.service.create_agent)(config)
        agent.elevenlabs_agent_id = result.get('agent_id')
        agent.save(update_fields=['elevenlabs_agent_id'])
        logger.info("Created ElevenLabs agent: %s", agent.elevenlabs_agent_id)

    def update_agent(self, agent: VoiceAgent) -> None:
        if not agent.elevenlabs_agent_id:
            return
        config = self._build_elevenlabs_config(agent)
        async_to_sync(self.service.update_agent)(agent.elevenlabs_agent_id, config)
        logger.info("Updated ElevenLabs agent: %s", agent.elevenlabs_agent_id)

    def delete_agent(self, agent: VoiceAgent) -> None:
        if not agent.elevenlabs_agent_id:
            return
        async_to_sync(self.service.delete_agent)(agent.elevenlabs_agent_id)
        logger.info("Deleted ElevenLabs agent: %s", agent.elevenlabs_agent_id)

    def start_session(self, agent: VoiceAgent, user) -> VoiceSessionStartResponse:
        if not agent.elevenlabs_agent_id:
            raise ValueError("Agent not configured with ElevenLabs")

        try:
            async_to_sync(self.service.ensure_webhook)(agent.elevenlabs_agent_id)
        except Exception as exc:
            logger.exception(
                "Failed to ensure webhook for agent %s: %s",
                agent.elevenlabs_agent_id,
                exc,
            )

        signed_url = async_to_sync(self.service.get_signed_url)(agent.elevenlabs_agent_id)
        return VoiceSessionStartResponse(
            provider=VoiceProvider.ELEVENLABS,
            signed_url=signed_url,
            agent_id=agent.elevenlabs_agent_id,
        )

    def _build_elevenlabs_config(self, agent: VoiceAgent) -> dict:
        owner_email = agent.user.email
        elevenlabs_name = build_elevenlabs_agent_name(owner_email, agent.name)
        return self.service.build_agent_config(
            name=elevenlabs_name,
            system_prompt=agent.system_prompt,
            voice_id=agent.voice_id,
            temperature=agent.temperature,
            first_message=agent.first_message or agent.exam_instructions,
            max_duration_seconds=agent.max_duration_seconds,
            conversation_config=agent.conversation_config or None,
        )


class MistralVoiceProvider(BaseVoiceProvider):
    """Mistral Voxtral via the full-duplex Pipecat voice runtime.

    Mints a short-lived signed session token and points the browser at the
    Pipecat runtime (``VOICE_RUNTIME_PUBLIC_URL``), which owns WebRTC mic
    transport, server-side VAD, barge-in, and TTS artifact playback. The
    runtime reports the completed transcript back via the conversation-ended
    callback.
    """

    provider_name = VoiceProvider.MISTRAL_VOICE

    def create_agent(self, agent: VoiceAgent) -> None:
        logger.info("Prepared Mistral Voice agent locally: %s", agent.id)

    def update_agent(self, agent: VoiceAgent) -> None:
        logger.info("Updated Mistral Voice agent locally: %s", agent.id)

    def delete_agent(self, agent: VoiceAgent) -> None:
        logger.info("Deleted Mistral Voice agent locally: %s", agent.id)

    def start_session(self, agent: VoiceAgent, user) -> VoiceSessionStartResponse:
        session_id = uuid.uuid4().hex
        expires_at = timezone.now() + timedelta(seconds=VOICE_RUNTIME_SESSION_TOKEN_TTL_SECONDS)
        token = self._sign_session_token(
            session_id=session_id,
            agent=agent,
            user_id=user.id,
            expires_at=expires_at,
        )
        webrtc_url = self._build_webrtc_url(session_id)

        VoiceConversation.objects.create(
            agent=agent,
            user=user,
            elevenlabs_conversation_id=session_id,
            provider_conversation_id=session_id,
            status=ConversationStatus.RESERVED,
            compliance_receipt={
                "conversationId": session_id,
                "provider": VoiceProvider.MISTRAL_VOICE,
                "reservedAt": timezone.now().isoformat(),
            },
        )

        return VoiceSessionStartResponse(
            provider=VoiceProvider.MISTRAL_VOICE,
            session_id=session_id,
            webrtc_url=webrtc_url,
            ice_servers=getattr(settings, 'VOICE_RUNTIME_ICE_SERVERS', []),
            token=token,
            expires_at=expires_at.isoformat(),
        )

    def _build_webrtc_url(self, session_id: str) -> str:
        return build_runtime_webrtc_url(session_id)

    def _sign_session_token(
        self,
        session_id: str,
        agent: VoiceAgent,
        user_id: int,
        expires_at,
    ) -> str:
        return sign_runtime_session_token(
            session_id=session_id,
            agent_id=agent.id,
            user_id=user_id,
            expires_at=expires_at,
        )


def build_runtime_webrtc_url(session_id: str) -> str:
    """Browser-facing WebRTC offer URL on the standalone voice runtime."""
    public_url = getattr(settings, 'VOICE_RUNTIME_PUBLIC_URL', '')
    if not public_url:
        raise ValueError("VOICE_RUNTIME_PUBLIC_URL is not configured")
    return f"{public_url.rstrip('/')}/sessions/{session_id}/webrtc/offer"


def sign_runtime_session_token(
    session_id: str,
    agent_id: int,
    user_id: int,
    expires_at,
    mode: Optional[str] = None,
) -> str:
    """Sign a voice runtime session token.

    Auth-only claims. Anything bigger (system_prompt, first_message,
    voice_id, etc.) is looked up server-to-server by the runtime via
    /api/voice/runtime/sessions/<id>/context/ — keeps the token small
    enough to fit safely in URL/POST headers and avoids the multi-KB
    token bloat that breaks the HTTP request line.

    ``mode="lab"`` selects the runtime's isolated STT Lab pipeline instead
    of the exam pipeline; exam tokens omit the claim entirely so existing
    runtime deployments are unaffected.
    """
    secret = getattr(settings, 'VOICE_RUNTIME_SESSION_SECRET', '') or getattr(
        settings,
        'DARE_INTERNAL_KEY',
        '',
    )
    if not secret:
        raise ValueError(
            "VOICE_RUNTIME_SESSION_SECRET or DARE_INTERNAL_KEY is not configured"
        )

    payload = {
        "session_id": session_id,
        "agent_id": agent_id,
        "user_id": user_id,
        "expires_at": expires_at.isoformat(),
    }
    if mode:
        payload["mode"] = mode
    payload_bytes = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    encoded_payload = base64.urlsafe_b64encode(payload_bytes).decode('utf-8').rstrip('=')
    signature = hmac.new(
        secret.encode('utf-8'),
        encoded_payload.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded_payload}.{signature}"


def get_voice_provider(provider: str) -> BaseVoiceProvider:
    """Return the provider implementation for a provider name."""
    if provider == VoiceProvider.MISTRAL_VOICE:
        return MistralVoiceProvider()
    return ElevenLabsVoiceProvider()
