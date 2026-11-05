"""Voice Data Transfer Objects."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class TranscriptMessage:
    """Single message in a conversation transcript."""

    role: str
    message: str
    time_in_call_secs: float

    @classmethod
    def from_dict(cls, raw_message: Dict) -> "TranscriptMessage":
        """Parse a transcript message from a provider callback."""
        return cls(
            role=raw_message.get("role", ""),
            message=raw_message.get("message", raw_message.get("content", "")),
            time_in_call_secs=raw_message.get(
                "timeInCallSecs",
                raw_message.get("time_in_call_secs", 0.0),
            ),
        )

    def to_dict(self) -> Dict:
        """Convert this message to the normalized JSON shape stored locally."""
        return {
            "role": self.role,
            "message": self.message,
            "timeInCallSecs": self.time_in_call_secs,
        }


@dataclass(frozen=True)
class VoiceAgentProviderConfig:
    """Provider-neutral voice agent configuration."""

    name: str
    system_prompt: str
    first_message: str
    voice_id: str
    temperature: float
    max_duration_seconds: int
    language: str
    conversation_config: Dict = field(default_factory=dict)


@dataclass(frozen=True)
class VoiceSessionStartResponse:
    """Provider-aware response for starting a voice session."""

    provider: str
    agent_id: Optional[str] = None
    signed_url: Optional[str] = None
    session_id: Optional[str] = None
    webrtc_url: Optional[str] = None
    ice_servers: Optional[List[str]] = None
    token: Optional[str] = None
    expires_at: Optional[str] = None

    def to_response_data(self) -> Dict:
        """Convert to API response data; DRF camelCase renderer handles casing."""
        data = {
            "provider": self.provider,
            "agent_id": self.agent_id,
            "signed_url": self.signed_url,
            "session_id": self.session_id,
            "webrtc_url": self.webrtc_url,
            "ice_servers": self.ice_servers,
            "token": self.token,
            "expires_at": self.expires_at,
        }
        return {key: value for key, value in data.items() if value is not None}


@dataclass(frozen=True)
class MistralConversationEndedPayload:
    """Payload posted by the Mistral voice runtime when a session ends."""

    session_id: str
    transcript: List[TranscriptMessage] = field(default_factory=list)
    duration_seconds: Optional[int] = None
    status: str = "completed"
    ended_reason: str = ""
    metrics: Dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw_payload: Dict) -> "MistralConversationEndedPayload":
        """Parse the voice runtime completion callback into a typed DTO."""
        transcript = [
            TranscriptMessage.from_dict(message)
            for message in raw_payload.get("transcript", [])
        ]
        return cls(
            session_id=raw_payload.get("session_id", raw_payload.get("sessionId", "")),
            transcript=transcript,
            duration_seconds=raw_payload.get(
                "duration_seconds",
                raw_payload.get("durationSeconds"),
            ),
            status=raw_payload.get("status", "completed"),
            ended_reason=raw_payload.get("ended_reason", raw_payload.get("endedReason", "")),
            metrics=raw_payload.get("metrics", {}),
        )

    def transcript_as_list(self) -> List[Dict]:
        """Convert transcript to list of dicts for JSON storage."""
        return [message.to_dict() for message in self.transcript]


@dataclass(frozen=True)
class WebhookMetadata:
    """Metadata from ElevenLabs webhook."""

    duration_seconds: Optional[int] = None
    ended_reason: Optional[str] = None


@dataclass(frozen=True)
class ElevenLabsWebhookPayload:
    """
    Parsed webhook payload from ElevenLabs.

    Represents the conversation end event data.
    """

    conversation_id: str
    agent_id: str
    transcript: List[TranscriptMessage] = field(default_factory=list)
    metadata: Optional[WebhookMetadata] = None

    @classmethod
    def from_dict(cls, raw_payload: Dict) -> "ElevenLabsWebhookPayload":
        """
        Parse webhook JSON into typed DTO.

        ElevenLabs webhook structure:
        {
            "type": "post_call_transcription",
            "data": {
                "conversation_id": "...",
                "agent_id": "...",
                "transcript": [...],
                "metadata": {...},
                ...
            },
            "event_timestamp": 1234567890
        }

        Args:
            raw_payload: Raw webhook JSON data (full payload with type/data/event_timestamp)

        Returns:
            Typed ElevenLabsWebhookPayload instance
        """
        # Extract nested data - ElevenLabs wraps payload in "data" field
        data = raw_payload.get("data", raw_payload)

        transcript = [
            TranscriptMessage(
                role=msg.get("role", ""),
                message=msg.get("message", ""),
                time_in_call_secs=msg.get(
                    "timeInCallSecs",
                    msg.get("time_in_call_secs", 0.0),
                ),
            )
            for msg in data.get("transcript", [])
        ]

        metadata_dict = data.get("metadata", {})
        metadata = (
            WebhookMetadata(
                duration_seconds=metadata_dict.get("duration_seconds"),
                ended_reason=metadata_dict.get("ended_reason"),
            )
            if metadata_dict
            else None
        )

        return cls(
            conversation_id=data.get("conversation_id", ""),
            agent_id=data.get("agent_id", ""),
            transcript=transcript,
            metadata=metadata,
        )

    def transcript_as_list(self) -> List[Dict]:
        """
        Convert transcript to list of dicts for JSON storage.

        Returns:
            List of transcript message dicts
        """
        return [
            {
                "role": msg.role,
                "message": msg.message,
                "timeInCallSecs": msg.time_in_call_secs,
            }
            for msg in self.transcript
        ]
